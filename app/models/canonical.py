import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey

# Money and quantities are Numeric, never Float. Reconciliation compares these
# values for equality within a tolerance; binary floating point would manufacture
# variances that do not exist in the source data.
QTY = Numeric(18, 4)
MONEY = Numeric(18, 4)

# Canonical records are scoped to their ingestion run. Re-uploading the same PO
# in a later run creates a separate record rather than colliding, which is what
# makes runs independently repeatable.
# These are factories, not shared instances: a ForeignKey object binds to exactly
# one parent column.
def RunFK() -> ForeignKey:
    return ForeignKey("ingestion_runs.id", ondelete="CASCADE")


def StagingFK() -> ForeignKey:
    return ForeignKey("staging_records.id", ondelete="SET NULL")


class Vendor(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "normalized_name"),)

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), RunFK(), index=True)
    vendor_code: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)


class PurchaseOrder(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "po_number"),)

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), RunFK(), index=True)
    po_number: Mapped[str] = mapped_column(String(128), index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    po_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(8))

    vendor: Mapped[Vendor | None] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    line_number: Mapped[int] = mapped_column(Integer)
    item: Mapped[str] = mapped_column(String(512))
    item_code: Mapped[str | None] = mapped_column(String(128))
    normalized_item: Mapped[str] = mapped_column(String(512), index=True)
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    staging_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), StagingFK())

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class Grn(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "grns"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "grn_ref"),)

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), RunFK(), index=True)
    # The CSV carries no GRN number, so this is synthesised per PO per run.
    # A real grn_number column drops in here later without a schema change.
    grn_ref: Mapped[str] = mapped_column(String(128), index=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    grn_date: Mapped[date | None] = mapped_column(Date)

    lines: Mapped[list["GrnLine"]] = relationship(
        back_populates="grn", cascade="all, delete-orphan"
    )


class GrnLine(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "grn_lines"

    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grns.id", ondelete="CASCADE"), index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), index=True
    )
    item: Mapped[str] = mapped_column(String(512))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    staging_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), StagingFK())

    grn: Mapped[Grn] = relationship(back_populates="lines")


class Invoice(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "invoice_number"),)

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), RunFK(), index=True)
    invoice_number: Mapped[str] = mapped_column(String(128), index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL")
    )
    invoice_date: Mapped[date | None] = mapped_column(Date)
    tax_total: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(8))

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceLine(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), index=True
    )
    item: Mapped[str] = mapped_column(String(512))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    tax: Mapped[Decimal | None] = mapped_column(MONEY)
    staging_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), StagingFK())

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
