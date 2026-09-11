"""Upload → validate → stage. Deliberately free of FastAPI imports so the whole
pipeline can be lifted into the larger MRO platform unchanged."""

import hashlib
import io
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import IngestionRun, IngestionStatus, StagingRecord, UploadedFile
from app.modules.m4.column_map import MappingResult, resolve_columns
from app.modules.m4.fields import FIELDS
from app.modules.m4.validation import (
    ACCEPTED_SUFFIXES,
    CsvFormatError,
    ParsedRow,
    errors_to_json,
    read_tabular,
    validate_rows,
)


_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xls": "application/vnd.ms-excel",
}


def _content_type(filename: str) -> str:
    for suffix, mime in _CONTENT_TYPES.items():
        if filename.lower().endswith(suffix):
            return mime
    return "application/octet-stream"


class IngestionRejected(Exception):
    """The file was readable but cannot be used. Carries everything the user
    needs to fix it: what is missing, what we did recognise, and the template."""

    def __init__(self, message: str, hint: str | None = None, mapping: MappingResult | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.mapping = mapping


@dataclass
class IngestionOutcome:
    run: IngestionRun
    mapping: MappingResult
    rows: list[ParsedRow]


def expected_format() -> dict:
    return {
        "required": [
            {"field": f.name, "label": f.label, "type": f.kind, "description": f.description}
            for f in FIELDS if f.required
        ],
        "optional": [
            {"field": f.name, "label": f.label, "type": f.kind, "description": f.description}
            for f in FIELDS if not f.required
        ],
        "aliases": {f.name: list(f.aliases) for f in FIELDS},
        "note": (
            "One row per item, carrying the ordered, received and billed figures "
            "together. Column names need not match exactly — common variants are "
            "recognised automatically and anything unrecognised can be mapped by hand."
        ),
    }


def build_template_csv() -> str:
    header = [f.name for f in FIELDS]
    examples = {
        "po_number": "PO-1001", "vendor": "Acme Industrial Ltd", "item": "Ball Bearing 6205",
        "po_quantity": "100", "grn_quantity": "100", "invoice_quantity": "100",
        "po_unit_price": "450.00", "invoice_unit_price": "450.00",
        "invoice_number": "INV-2201", "tax": "8100.00", "po_date": "2026-01-12",
        "grn_date": "2026-01-20", "invoice_date": "2026-01-22",
        "vendor_code": "V-0012", "item_code": "BRG-6205", "currency": "INR",
    }
    second = dict(examples, po_number="PO-1002", item="Oil Seal 35x52x7",
                  po_quantity="50", grn_quantity="48", invoice_quantity="50",
                  po_unit_price="120.00", invoice_unit_price="126.00",
                  invoice_number="INV-2202", tax="1134.00", item_code="SEL-3552")

    buffer = io.StringIO()
    buffer.write(",".join(header) + "\n")
    for row in (examples, second):
        buffer.write(",".join(str(row.get(col, "")) for col in header) + "\n")
    return buffer.getvalue()


def ingest_csv(
    db: Session,
    *,
    content: bytes,
    filename: str,
    actor: str,
    max_bytes: int,
) -> IngestionOutcome:
    if len(content) > max_bytes:
        raise IngestionRejected(
            f"The file is {len(content) / 1_000_000:.1f} MB, above the "
            f"{max_bytes / 1_000_000:.1f} MB upload limit.",
            "Split the export into smaller files and upload them as separate runs.",
        )

    frame = read_tabular(content, filename)  # raises CsvFormatError
    mapping = resolve_columns(list(frame.columns))

    uploaded = UploadedFile(
        original_filename=filename,
        content=content,
        content_type=_content_type(filename),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=actor,
    )
    db.add(uploaded)
    db.flush()

    run = IngestionRun(
        uploaded_file_id=uploaded.id,
        source_filename=filename,
        status=IngestionStatus.UPLOADED,
        row_count=len(frame),
        column_mapping=mapping.to_json()["mapping"],
        unmapped_columns=mapping.unmapped_columns,
    )
    db.add(run)
    db.flush()

    if not mapping.is_usable:
        # Recorded rather than discarded: a rejected upload is still part of the
        # audit trail, and the user can fix the mapping without re-uploading.
        run.status = IngestionStatus.FAILED_VALIDATION
        run.validation_errors = [{
            "type": "missing_required_columns",
            "fields": mapping.missing_required,
        }]
        db.flush()
        raise IngestionRejected(
            "The file is missing required columns.",
            "Map them manually on the next screen, or re-upload using the template.",
            mapping,
        )

    rows = validate_rows(frame, mapping)
    _stage(db, run, rows)
    return IngestionOutcome(run=run, mapping=mapping, rows=rows)


def restage(db: Session, run: IngestionRun, overrides: dict[str, str]) -> IngestionOutcome:
    """Re-run validation after the user corrects the column mapping."""
    uploaded = db.get(UploadedFile, run.uploaded_file_id)
    frame = read_tabular(uploaded.content, run.source_filename)
    mapping = resolve_columns(list(frame.columns), overrides=overrides)

    run.column_mapping = mapping.to_json()["mapping"]
    run.unmapped_columns = mapping.unmapped_columns

    if not mapping.is_usable:
        run.status = IngestionStatus.FAILED_VALIDATION
        run.validation_errors = [{
            "type": "missing_required_columns",
            "fields": mapping.missing_required,
        }]
        db.flush()
        raise IngestionRejected(
            "Required columns are still unmapped.",
            "Every required field needs a source column before the data can be staged.",
            mapping,
        )

    db.query(StagingRecord).filter(StagingRecord.ingestion_run_id == run.id).delete()
    rows = validate_rows(frame, mapping)
    _stage(db, run, rows)
    return IngestionOutcome(run=run, mapping=mapping, rows=rows)


def _stage(db: Session, run: IngestionRun, rows: list[ParsedRow]) -> None:
    db.bulk_save_objects([
        StagingRecord(
            ingestion_run_id=run.id,
            row_number=row.row_number,
            raw_data=row.raw,
            mapped_data=row.mapped,
            is_valid=row.is_valid,
            errors=errors_to_json(row.errors) or None,
        )
        for row in rows
    ])

    run.row_count = len(rows)
    run.valid_row_count = sum(1 for r in rows if r.is_valid)
    run.error_row_count = sum(1 for r in rows if not r.is_valid)
    run.validation_errors = [
        e for row in rows if not row.is_valid for e in errors_to_json(row.errors)
    ][:500] or None
    run.status = IngestionStatus.STAGED
    db.flush()


__all__ = [
    "ACCEPTED_SUFFIXES",
    "CsvFormatError",
    "IngestionOutcome",
    "IngestionRejected",
    "build_template_csv",
    "expected_format",
    "ingest_csv",
    "restage",
]
