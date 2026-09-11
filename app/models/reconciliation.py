import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import ReconciliationRunStatus


class ReconciliationRun(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "reconciliation_runs"

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True
    )
    rule_version: Mapped[str] = mapped_column(String(32))
    # Frozen at execution time: a result must stay explainable even after the
    # configured defaults are changed.
    tolerances: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default=ReconciliationRunStatus.RUNNING)
    status_counts: Mapped[dict | None] = mapped_column(JSONB)
    # Money that would be overpaid if every exception in this run were paid as
    # billed. The number finance acts on, as opposed to a count of exceptions.
    total_exposure: Mapped[object | None] = mapped_column(Numeric(18, 2))
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["ReconciliationResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ReconciliationResult(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "reconciliation_results"

    reconciliation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    # The thread back to the exact uploaded CSV row. Never null in practice:
    # every result originates from one staged row.
    staging_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staging_records.id", ondelete="SET NULL"), index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="SET NULL")
    )
    grn_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grn_lines.id", ondelete="SET NULL")
    )
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice_lines.id", ondelete="SET NULL")
    )

    # Written once by the engine and never updated. Human outcomes are appended
    # to decision_log; current_status is derived from the newest decision. This
    # is what guarantees the original machine verdict stays recoverable.
    system_status: Mapped[str] = mapped_column(String(32), index=True)
    current_status: Mapped[str] = mapped_column(String(32), index=True)

    findings: Mapped[list] = mapped_column(JSONB)
    explanation: Mapped[str | None] = mapped_column(Text)
    # Denormalised for list rendering and search without joining six tables.
    snapshot: Mapped[dict] = mapped_column(JSONB)

    run: Mapped[ReconciliationRun] = relationship(back_populates="results")
    decisions: Mapped[list["DecisionLogEntry"]] = relationship(
        back_populates="result",
        cascade="all, delete-orphan",
        order_by="DecisionLogEntry.decided_at",
    )


class DecisionLogEntry(Base, UUIDPrimaryKey):
    __tablename__ = "decision_log"

    reconciliation_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliation_results.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(32))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    result: Mapped[ReconciliationResult] = relationship(back_populates="decisions")
