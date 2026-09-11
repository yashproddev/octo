"""Staging → canonical fan-out.

A single uploaded row describes one item across three documents. This module
explodes it into the separate PO / GRN / invoice records the schema models,
linking every one of them back to the staging row it came from.

Canonical records are scoped to the ingestion run, so re-uploading the same PO
in a later run produces a separate record instead of colliding with the first.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Grn,
    GrnLine,
    IngestionRun,
    IngestionStatus,
    Invoice,
    InvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    StagingRecord,
    Vendor,
)

_PUNCT = re.compile(r"[^\w\s]+")
_SPACE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE.sub(" ", _PUNCT.sub(" ", str(value).strip().lower())).strip()


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _date(value):
    from datetime import date

    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass
class NormalizationSummary:
    vendors: int = 0
    purchase_orders: int = 0
    purchase_order_lines: int = 0
    grns: int = 0
    grn_lines: int = 0
    invoices: int = 0
    invoice_lines: int = 0
    skipped_rows: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def normalize_run(db: Session, run: IngestionRun) -> NormalizationSummary:
    rows = (
        db.query(StagingRecord)
        .filter(StagingRecord.ingestion_run_id == run.id)
        .order_by(StagingRecord.row_number)
        .all()
    )

    summary = NormalizationSummary()
    vendors: dict[str, Vendor] = {}
    orders: dict[str, PurchaseOrder] = {}
    grns: dict[str, Grn] = {}
    invoices: dict[str, Invoice] = {}
    line_counters: dict[str, int] = {}

    for row in rows:
        data = row.mapped_data or {}
        po_number = (data.get("po_number") or "").strip()

        # A row without a PO reference, or with unusable numbers, cannot be
        # fanned out. It is deliberately left un-normalised; the engine still
        # reports it as INCOMPLETE from its staging record, so it stays visible.
        po_qty = _decimal(data.get("po_quantity"))
        po_price = _decimal(data.get("po_unit_price"))
        if not po_number or po_qty is None or po_price is None:
            summary.skipped_rows += 1
            continue

        vendor_name = (data.get("vendor") or "").strip()
        vendor_key = normalize_text(data.get("vendor_code")) or normalize_text(vendor_name)
        vendor = vendors.get(vendor_key)
        if vendor is None and vendor_key:
            vendor = Vendor(
                ingestion_run_id=run.id,
                vendor_code=(data.get("vendor_code") or None),
                name=vendor_name or vendor_key,
                normalized_name=normalize_text(vendor_name) or vendor_key,
            )
            db.add(vendor)
            db.flush()
            vendors[vendor_key] = vendor
            summary.vendors += 1

        order = orders.get(po_number)
        if order is None:
            order = PurchaseOrder(
                ingestion_run_id=run.id,
                po_number=po_number,
                vendor_id=vendor.id if vendor else None,
                po_date=_date(data.get("po_date")),
                currency=(data.get("currency") or None),
            )
            db.add(order)
            db.flush()
            orders[po_number] = order
            summary.purchase_orders += 1

        line_counters[po_number] = line_counters.get(po_number, 0) + 1
        item = (data.get("item") or "").strip()

        po_line = PurchaseOrderLine(
            purchase_order_id=order.id,
            line_number=line_counters[po_number],
            item=item,
            item_code=(data.get("item_code") or None),
            normalized_item=normalize_text(item),
            quantity=po_qty,
            unit_price=po_price,
            staging_record_id=row.id,
        )
        db.add(po_line)
        db.flush()
        summary.purchase_order_lines += 1

        # The CSV carries no GRN number, so one synthetic header per PO per run.
        grn_qty = _decimal(data.get("grn_quantity"))
        if grn_qty is not None:
            grn_ref = f"GRN-{po_number}"
            grn = grns.get(grn_ref)
            if grn is None:
                grn = Grn(
                    ingestion_run_id=run.id,
                    grn_ref=grn_ref,
                    purchase_order_id=order.id,
                    grn_date=_date(data.get("grn_date")),
                )
                db.add(grn)
                db.flush()
                grns[grn_ref] = grn
                summary.grns += 1

            db.add(GrnLine(
                grn_id=grn.id,
                purchase_order_line_id=po_line.id,
                item=item,
                quantity=grn_qty,
                staging_record_id=row.id,
            ))
            summary.grn_lines += 1

        inv_qty = _decimal(data.get("invoice_quantity"))
        inv_price = _decimal(data.get("invoice_unit_price"))
        if inv_qty is not None and inv_price is not None:
            # Without an invoice number the rows cannot be grouped, so each gets
            # its own synthetic header. Duplicate detection is skipped for these.
            invoice_number = (data.get("invoice_number") or "").strip()
            if not invoice_number:
                invoice_number = f"AUTO-{po_number}-{row.row_number}"

            invoice = invoices.get(invoice_number)
            if invoice is None:
                invoice = Invoice(
                    ingestion_run_id=run.id,
                    invoice_number=invoice_number,
                    vendor_id=vendor.id if vendor else None,
                    purchase_order_id=order.id,
                    invoice_date=_date(data.get("invoice_date")),
                    currency=(data.get("currency") or None),
                    tax_total=Decimal("0"),
                )
                db.add(invoice)
                db.flush()
                invoices[invoice_number] = invoice
                summary.invoices += 1

            tax = _decimal(data.get("tax"))
            if tax is not None:
                invoice.tax_total = (invoice.tax_total or Decimal("0")) + tax

            db.add(InvoiceLine(
                invoice_id=invoice.id,
                purchase_order_line_id=po_line.id,
                item=item,
                quantity=inv_qty,
                unit_price=inv_price,
                tax=tax,
                staging_record_id=row.id,
            ))
            summary.invoice_lines += 1

    from datetime import UTC, datetime

    run.status = IngestionStatus.NORMALIZED
    run.normalized_at = datetime.now(UTC)
    db.flush()
    return summary
