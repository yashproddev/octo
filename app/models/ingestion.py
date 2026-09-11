import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import IngestionStatus


class UploadedFile(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "uploaded_files"

    original_filename: Mapped[str] = mapped_column(String(512))
    # Serverless functions have no persistent disk, so the raw file lives here.
    # It is what makes an audited result traceable back to the exact bytes uploaded.
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(255))

    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(back_populates="uploaded_file")


class IngestionRun(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "ingestion_runs"

    uploaded_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default=IngestionStatus.UPLOADED, index=True)
    source_filename: Mapped[str] = mapped_column(String(512))

    row_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_row_count: Mapped[int] = mapped_column(Integer, default=0)

    # {canonical_field: {"source_column": str, "match": "exact|alias|manual|unmapped"}}
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    unmapped_columns: Mapped[list | None] = mapped_column(JSONB)
    validation_errors: Mapped[list | None] = mapped_column(JSONB)

    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="ingestion_runs")
    staging_records: Mapped[list["StagingRecord"]] = relationship(
        back_populates="ingestion_run", cascade="all, delete-orphan"
    )


class StagingRecord(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "staging_records"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "row_number"),)

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)

    raw_data: Mapped[dict] = mapped_column(JSONB)
    mapped_data: Mapped[dict | None] = mapped_column(JSONB)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    errors: Mapped[list | None] = mapped_column(JSONB)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="staging_records")
