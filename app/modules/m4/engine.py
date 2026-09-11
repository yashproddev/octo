"""The deterministic reconciliation engine.

Each staged row produces exactly one result, which keeps a result traceable to
the CSV line it came from. Status is decided by first-match-wins precedence so
the outcome is reproducible: the same data plus the same tolerances always gives
the same verdict, which is the property that makes a human sign-off meaningful.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    DecisionAction,
    DecisionLogEntry,
    GrnLine,
    IngestionRun,
    InvoiceLine,
    PurchaseOrderLine,
    ReconciliationResult,
    ReconciliationRun,
    ReconciliationRunStatus,
    ResultStatus,
    StagingRecord,
)
from app.modules.m4.normalize import normalize_text
from app.modules.m4.rules import (
    RULE_VERSION,
    Finding,
    RuleOutcome,
    Tolerances,
    check_tax,
    compare_price,
    compare_quantity,
)


@dataclass
class _Row:
    staging: StagingRecord
    po_line: PurchaseOrderLine | None
    grn_line: GrnLine | None
    invoice_line: InvoiceLine | None
    invoice_number: str | None
    vendor: str | None


def _load_rows(db: Session, run: IngestionRun) -> list[_Row]:
    staged = (
        db.query(StagingRecord)
        .filter(StagingRecord.ingestion_run_id == run.id)
        .order_by(StagingRecord.row_number)
        .all()
    )

    po_lines = {
        line.staging_record_id: line
        for line in db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.staging_record_id.in_([s.id for s in staged] or [None]))
        .all()
    }
    grn_lines = {
        line.staging_record_id: line
        for line in db.query(GrnLine)
        .filter(GrnLine.staging_record_id.in_([s.id for s in staged] or [None]))
        .all()
    }
    invoice_lines = {
        line.staging_record_id: line
        for line in db.query(InvoiceLine)
        .filter(InvoiceLine.staging_record_id.in_([s.id for s in staged] or [None]))
        .all()
    }

    rows = []
    for record in staged:
        data = record.mapped_data or {}
        rows.append(_Row(
            staging=record,
            po_line=po_lines.get(record.id),
            grn_line=grn_lines.get(record.id),
            invoice_line=invoice_lines.get(record.id),
            invoice_number=(data.get("invoice_number") or "").strip() or None,
            vendor=(data.get("vendor") or "").strip() or None,
        ))
    return rows


def _duplicate_keys(rows: list[_Row]) -> dict:
    """Mark the second and later appearances of an identical invoice line.

    The key is (vendor, invoice_number, item). The same invoice number across
    *different* items is a legitimate multi-line invoice and must not be flagged,
    or every multi-line invoice in the file would raise a false exception.
    """
    seen: dict[tuple, int] = {}
    duplicates: dict = {}

    for row in rows:
        if not row.invoice_number or not row.invoice_line:
            continue
        key = (
            normalize_text(row.vendor),
            normalize_text(row.invoice_number),
            normalize_text(row.invoice_line.item),
        )
        if key in seen:
            duplicates[row.staging.id] = {
                "first_row": seen[key],
                "invoice_number": row.invoice_number,
                "item": row.invoice_line.item,
            }
        else:
            seen[key] = row.staging.row_number
    return duplicates


def _evaluate(row: _Row, tol: Tolerances, duplicate: dict | None) -> tuple[str, RuleOutcome]:
    outcome = RuleOutcome()
    data = row.staging.mapped_data or {}

    # R1 — PO reference
    po_number = (data.get("po_number") or "").strip()
    if po_number:
        outcome.add(Finding(
            "R1", "PO reference", passed=True, severity="info",
            actual=po_number, explanation=f"Line is linked to purchase order {po_number}.",
        ))
    else:
        outcome.add(Finding(
            "R1", "PO reference", passed=False, severity="hard",
            explanation="No purchase order reference on this line, so it cannot be matched to an order.",
        ))

    # R7 — completeness, evaluated from the staged row's own validation errors
    staging_errors = row.staging.errors or []
    if staging_errors:
        outcome.add(Finding(
            "R7", "Record completeness", passed=False, severity="hard",
            explanation="; ".join(e.get("message", "") for e in staging_errors[:3]),
        ))
    else:
        outcome.add(Finding(
            "R7", "Record completeness", passed=True, severity="info",
            explanation="All required values are present and numeric.",
        ))

    po_qty = row.po_line.quantity if row.po_line else None
    grn_qty = row.grn_line.quantity if row.grn_line else None
    inv_qty = row.invoice_line.quantity if row.invoice_line else None
    po_price = row.po_line.unit_price if row.po_line else None
    inv_price = row.invoice_line.unit_price if row.invoice_line else None
    tax = row.invoice_line.tax if row.invoice_line else None

    outcome.add(compare_quantity("R2", "PO vs GRN quantity", "PO quantity", po_qty,
                                 "GRN quantity", grn_qty, tol))
    outcome.add(compare_quantity("R3", "GRN vs invoice quantity", "GRN quantity", grn_qty,
                                 "Invoice quantity", inv_qty, tol))
    outcome.add(compare_price(po_price, inv_price, tol))
    outcome.add(check_tax(inv_qty, inv_price, tax, tol))

    # R6 — duplicate invoice line
    if duplicate:
        outcome.add(Finding(
            "R6", "Duplicate invoice line", passed=False, severity="hard",
            explanation=(
                f"Invoice {duplicate['invoice_number']} already billed "
                f"\"{duplicate['item']}\" on row {duplicate['first_row']}. "
                "This row repeats the same invoice, item and vendor."
            ),
        ))
    elif row.invoice_number:
        outcome.add(Finding(
            "R6", "Duplicate invoice line", passed=True, severity="info",
            explanation=f"Invoice {row.invoice_number} bills this item once.",
        ))
    else:
        outcome.add(Finding(
            "R6", "Duplicate invoice line", passed=True, skipped=True,
            skip_reason="No invoice number supplied.",
            explanation="Duplicate detection needs an invoice number to compare against.",
        ))

    # Status precedence — first match wins.
    incomplete = any(
        f.rule_id in {"R1", "R7"} and not f.passed and not f.skipped for f in outcome.findings
    )
    if incomplete:
        return ResultStatus.INCOMPLETE, outcome
    if duplicate:
        return ResultStatus.DUPLICATE, outcome
    if outcome.hard_failures:
        return ResultStatus.MISMATCH, outcome
    if outcome.review_flags or outcome.skipped:
        return ResultStatus.REVIEW, outcome
    return ResultStatus.MATCHED, outcome


def _explain(status: str, outcome: RuleOutcome) -> str:
    if status == ResultStatus.MATCHED:
        return "Order, receipt and invoice agree on every checked value."
    relevant = [f for f in outcome.findings if not f.passed and not f.skipped]
    if not relevant:
        relevant = outcome.skipped
    return " ".join(f.explanation for f in relevant if f.explanation) or "No explanation available."


def _snapshot(row: _Row) -> dict:
    data = row.staging.mapped_data or {}
    return {
        "row_number": row.staging.row_number,
        "po_number": data.get("po_number"),
        "vendor": data.get("vendor"),
        "item": data.get("item"),
        "invoice_number": data.get("invoice_number"),
        "po_quantity": str(row.po_line.quantity) if row.po_line else data.get("po_quantity"),
        "grn_quantity": str(row.grn_line.quantity) if row.grn_line else data.get("grn_quantity"),
        "invoice_quantity": str(row.invoice_line.quantity) if row.invoice_line else data.get("invoice_quantity"),
        "po_unit_price": str(row.po_line.unit_price) if row.po_line else data.get("po_unit_price"),
        "invoice_unit_price": str(row.invoice_line.unit_price) if row.invoice_line else data.get("invoice_unit_price"),
        "tax": str(row.invoice_line.tax) if row.invoice_line and row.invoice_line.tax is not None else data.get("tax"),
        "currency": data.get("currency"),
    }


def reconcile(
    db: Session, run: IngestionRun, tolerances: dict | None = None, actor: str = "system"
) -> ReconciliationRun:
    tol = Tolerances.from_dict(tolerances)

    recon = ReconciliationRun(
        ingestion_run_id=run.id,
        rule_version=RULE_VERSION,
        tolerances=tol.as_dict(),
        status=ReconciliationRunStatus.RUNNING,
    )
    db.add(recon)
    db.flush()

    rows = _load_rows(db, run)
    duplicates = _duplicate_keys(rows)
    counts: dict[str, int] = {}

    for row in rows:
        status, outcome = _evaluate(row, tol, duplicates.get(row.staging.id))
        current = status

        result = ReconciliationResult(
            reconciliation_run_id=recon.id,
            staging_record_id=row.staging.id,
            purchase_order_line_id=row.po_line.id if row.po_line else None,
            grn_line_id=row.grn_line.id if row.grn_line else None,
            invoice_line_id=row.invoice_line.id if row.invoice_line else None,
            system_status=status,
            current_status=current,
            findings=[f.as_dict() for f in outcome.findings],
            explanation=_explain(status, outcome),
            snapshot=_snapshot(row),
        )
        db.add(result)
        db.flush()

        # Only a clean match auto-closes. The system verdict stays MATCHED; the
        # closure is recorded as a decision so the audit trail shows who closed it.
        if status == ResultStatus.MATCHED and tol.auto_close_matched:
            result.current_status = ResultStatus.AUTO_CLOSED
            db.add(DecisionLogEntry(
                reconciliation_result_id=result.id,
                actor="system",
                action=DecisionAction.AUTO_CLOSE,
                from_status=ResultStatus.MATCHED,
                to_status=ResultStatus.AUTO_CLOSED,
                reason="All checks passed within tolerance; closed automatically.",
                rule_version=RULE_VERSION,
                is_system=True,
            ))
            current = ResultStatus.AUTO_CLOSED

        counts[current] = counts.get(current, 0) + 1

    recon.status = ReconciliationRunStatus.COMPLETED
    recon.status_counts = counts
    recon.completed_at = datetime.now(UTC)
    db.flush()
    return recon
