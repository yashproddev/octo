"""The schema's whole job is to keep one uploaded CSV row traceable all the way
to the decision a human made about it. This test walks that chain end to end and
then walks it back, because a break anywhere in it makes the audit log worthless.
"""

import hashlib
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    DecisionAction,
    DecisionLogEntry,
    Grn,
    GrnLine,
    IngestionRun,
    IngestionStatus,
    Invoice,
    InvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ReconciliationResult,
    ReconciliationRun,
    ResultStatus,
    StagingRecord,
    UploadedFile,
    Vendor,
)

RAW_ROW = {
    "po_number": "PO-1001",
    "vendor": "Acme Industrial Ltd",
    "item": "Bearing 6205",
    "po_quantity": "100",
    "grn_quantity": "98",
    "invoice_quantity": "100",
    "po_unit_price": "450.00",
    "invoice_unit_price": "455.00",
    "invoice_number": "INV-77",
}


def _build_chain(db):
    content = b"po_number,vendor,item\nPO-1001,Acme,Bearing 6205\n"

    file = UploadedFile(
        original_filename="vendor-data.csv",
        content=content,
        content_type="text/csv",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by="tester",
    )
    db.add(file)
    db.flush()

    run = IngestionRun(
        uploaded_file_id=file.id,
        status=IngestionStatus.NORMALIZED,
        source_filename=file.original_filename,
        row_count=1,
        valid_row_count=1,
        error_row_count=0,
        column_mapping={"po_number": {"source_column": "PO No", "match": "alias"}},
    )
    db.add(run)
    db.flush()

    staging = StagingRecord(
        ingestion_run_id=run.id, row_number=1, raw_data=RAW_ROW, mapped_data=RAW_ROW, is_valid=True
    )
    db.add(staging)
    db.flush()

    vendor = Vendor(
        ingestion_run_id=run.id,
        name="Acme Industrial Ltd",
        normalized_name="acme industrial ltd",
    )
    db.add(vendor)
    db.flush()

    po = PurchaseOrder(ingestion_run_id=run.id, po_number="PO-1001", vendor_id=vendor.id)
    db.add(po)
    db.flush()

    po_line = PurchaseOrderLine(
        purchase_order_id=po.id,
        line_number=1,
        item="Bearing 6205",
        normalized_item="bearing 6205",
        quantity=Decimal("100"),
        unit_price=Decimal("450.00"),
        staging_record_id=staging.id,
    )
    db.add(po_line)
    db.flush()

    grn = Grn(ingestion_run_id=run.id, grn_ref=f"GRN-{run.id}-PO-1001", purchase_order_id=po.id)
    db.add(grn)
    db.flush()
    db.add(
        GrnLine(
            grn_id=grn.id,
            purchase_order_line_id=po_line.id,
            item="Bearing 6205",
            quantity=Decimal("98"),
            staging_record_id=staging.id,
        )
    )

    invoice = Invoice(
        ingestion_run_id=run.id, invoice_number="INV-77", vendor_id=vendor.id, purchase_order_id=po.id
    )
    db.add(invoice)
    db.flush()
    inv_line = InvoiceLine(
        invoice_id=invoice.id,
        purchase_order_line_id=po_line.id,
        item="Bearing 6205",
        quantity=Decimal("100"),
        unit_price=Decimal("455.00"),
        staging_record_id=staging.id,
    )
    db.add(inv_line)
    db.flush()

    recon = ReconciliationRun(
        ingestion_run_id=run.id,
        rule_version="m4-v0.1",
        tolerances={"price_tolerance_pct": 0.5},
        status="COMPLETED",
    )
    db.add(recon)
    db.flush()

    result = ReconciliationResult(
        reconciliation_run_id=recon.id,
        staging_record_id=staging.id,
        purchase_order_line_id=po_line.id,
        invoice_line_id=inv_line.id,
        system_status=ResultStatus.MISMATCH,
        current_status=ResultStatus.MISMATCH,
        findings=[{"rule_id": "R4", "passed": False}],
        explanation="Invoice unit price 455.00 exceeds PO unit price 450.00.",
        snapshot=RAW_ROW,
    )
    db.add(result)
    db.flush()
    return run, staging, result


def test_full_chain_is_traceable(db):
    _, staging, result = _build_chain(db)

    db.add(
        DecisionLogEntry(
            reconciliation_result_id=result.id,
            actor="ap.clerk",
            action=DecisionAction.APPROVE,
            from_status=ResultStatus.MISMATCH,
            to_status=ResultStatus.MATCHED,
            reason="Price increase agreed with vendor in writing.",
            rule_version="m4-v0.1",
        )
    )
    db.flush()

    # Walk backwards: decision → result → staged row → the original uploaded bytes.
    decision = db.execute(
        select(DecisionLogEntry).where(DecisionLogEntry.reconciliation_result_id == result.id)
    ).scalar_one()

    reloaded = db.get(ReconciliationResult, decision.reconciliation_result_id)
    origin = db.get(StagingRecord, reloaded.staging_record_id)
    ingestion = db.get(IngestionRun, origin.ingestion_run_id)
    source = db.get(UploadedFile, ingestion.uploaded_file_id)

    assert origin.id == staging.id
    assert origin.raw_data["po_number"] == "PO-1001"
    assert source.original_filename == "vendor-data.csv"
    assert source.content.startswith(b"po_number,vendor,item")


def test_system_verdict_survives_human_override(db):
    _, _, result = _build_chain(db)

    # A human overturns the machine. The system verdict must remain readable.
    db.add(
        DecisionLogEntry(
            reconciliation_result_id=result.id,
            actor="ap.clerk",
            action=DecisionAction.OVERRIDE,
            from_status=result.system_status,
            to_status=ResultStatus.MATCHED,
            reason="Approved variance.",
            rule_version="m4-v0.1",
        )
    )
    result.current_status = ResultStatus.MATCHED
    db.flush()

    reloaded = db.get(ReconciliationResult, result.id)
    assert reloaded.system_status == ResultStatus.MISMATCH  # untouched
    assert reloaded.current_status == ResultStatus.MATCHED  # derived
    assert len(reloaded.decisions) == 1


def test_numeric_columns_do_not_drift(db):
    """Quantities and money are Numeric, not Float. 0.1 + 0.2 must equal 0.3 here,
    or the engine would report variances that are artefacts of the storage type."""
    _, staging, _ = _build_chain(db)
    po = db.execute(select(PurchaseOrder)).scalars().first()

    line = PurchaseOrderLine(
        purchase_order_id=po.id,
        line_number=2,
        item="Seal Kit",
        normalized_item="seal kit",
        quantity=Decimal("0.1") + Decimal("0.2"),
        unit_price=Decimal("1234.5678"),
        staging_record_id=staging.id,
    )
    db.add(line)
    db.flush()
    db.expire(line)

    assert line.quantity == Decimal("0.3000")
    assert line.unit_price == Decimal("1234.5678")


def test_deleting_a_run_cascades_but_leaves_no_orphans(db):
    run, _, result = _build_chain(db)
    run_id, result_id = run.id, result.id

    db.delete(run)
    db.flush()
    # The cascade happens in Postgres, so the session's identity map must be
    # discarded before asking what actually survived.
    db.expire_all()

    def count(model, **where):
        stmt = select(func.count()).select_from(model)
        for col, val in where.items():
            stmt = stmt.where(getattr(model, col) == val)
        return db.execute(stmt).scalar_one()

    assert count(ReconciliationResult, id=result_id) == 0
    assert count(StagingRecord, ingestion_run_id=run_id) == 0
    assert count(PurchaseOrder, ingestion_run_id=run_id) == 0
    assert count(Vendor, ingestion_run_id=run_id) == 0
    assert count(ReconciliationRun, ingestion_run_id=run_id) == 0

    # decision_log hangs off the result, two cascade hops from the run.
    assert db.execute(
        select(func.count()).select_from(DecisionLogEntry).where(
            DecisionLogEntry.reconciliation_result_id == result_id
        )
    ).scalar_one() == 0
