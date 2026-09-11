import uuid

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import IngestionRun, StagingRecord, UploadedFile
from app.modules.m4.validation import read_tabular
from app.modules.m4.ingestion import (
    ACCEPTED_SUFFIXES,
    CsvFormatError,
    IngestionRejected,
    build_template_csv,
    expected_format,
    ingest_csv,
    restage,
)

router = APIRouter()


def actor(x_actor: str = Header(default="demo.user")) -> str:
    return x_actor


def _run_payload(run: IngestionRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "source_filename": run.source_filename,
        "row_count": run.row_count,
        "valid_row_count": run.valid_row_count,
        "error_row_count": run.error_row_count,
        "column_mapping": run.column_mapping,
        "unmapped_columns": run.unmapped_columns or [],
        "validation_errors": run.validation_errors or [],
        "normalized_at": run.normalized_at.isoformat() if run.normalized_at else None,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/schema")
def schema() -> dict:
    return expected_format()


@router.get("/template.csv", response_class=PlainTextResponse)
def template() -> PlainTextResponse:
    return PlainTextResponse(
        build_template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="m4-template.csv"'},
    )


@router.post("/ingestion/uploads", status_code=201)
def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    who: str = Depends(actor),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(ACCEPTED_SUFFIXES):
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"\"{file.filename or 'That file'}\" is not a spreadsheet we can read.",
                "hint": "Upload a .csv, .xlsx, .xlsm or .xls file.",
                "expected_format": expected_format(),
            },
        )

    content = file.file.read()

    try:
        outcome = ingest_csv(
            db,
            content=content,
            filename=file.filename,
            actor=who,
            max_bytes=settings.max_upload_bytes,
        )
    except CsvFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": exc.message,
                "hint": exc.hint,
                "expected_format": expected_format(),
            },
        ) from exc
    except IngestionRejected as exc:
        db.commit()  # keep the failed run for the audit trail
        detail = {
            "message": exc.message,
            "hint": exc.hint,
            "expected_format": expected_format(),
        }
        if exc.mapping:
            detail |= exc.mapping.to_json()
        raise HTTPException(status_code=422, detail=detail) from exc

    db.commit()
    return {
        "run": _run_payload(outcome.run),
        **outcome.mapping.to_json(),
        "preview": [
            {"row_number": r.row_number, "mapped": r.mapped, "errors": [e.__dict__ for e in r.errors]}
            for r in outcome.rows[:10]
        ],
    }


@router.get("/ingestion/runs")
def list_runs(db: Session = Depends(get_db), limit: int = Query(50, le=200)) -> dict:
    runs = db.execute(
        select(IngestionRun).order_by(IngestionRun.created_at.desc()).limit(limit)
    ).scalars().all()
    return {"runs": [_run_payload(r) for r in runs]}


@router.get("/ingestion/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(404, detail={"message": "Ingestion run not found."})
    source = db.get(UploadedFile, run.uploaded_file_id)
    # Re-read through the same reader that ingested it. Decoding the bytes as
    # text would work for CSV and produce nonsense for a binary workbook.
    columns: list[str] = []
    if source:
        try:
            columns = [str(c).strip() for c in read_tabular(source.content, run.source_filename).columns]
        except CsvFormatError:
            columns = []

    return {
        "run": _run_payload(run),
        "source_columns": columns,
        "expected_format": expected_format(),
    }


@router.get("/ingestion/runs/{run_id}/rows")
def get_rows(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    invalid_only: bool = False,
    limit: int = Query(100, le=1000),
    offset: int = 0,
) -> dict:
    stmt = select(StagingRecord).where(StagingRecord.ingestion_run_id == run_id)
    if invalid_only:
        stmt = stmt.where(StagingRecord.is_valid.is_(False))
    rows = db.execute(
        stmt.order_by(StagingRecord.row_number).limit(limit).offset(offset)
    ).scalars().all()
    return {
        "rows": [
            {
                "row_number": r.row_number,
                "raw_data": r.raw_data,
                "mapped_data": r.mapped_data,
                "is_valid": r.is_valid,
                "errors": r.errors or [],
            }
            for r in rows
        ]
    }


@router.put("/ingestion/runs/{run_id}/mapping")
def update_mapping(
    run_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(404, detail={"message": "Ingestion run not found."})

    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise HTTPException(422, detail={"message": "'overrides' must be an object of field -> column."})

    try:
        outcome = restage(db, run, overrides)
    except CsvFormatError as exc:
        raise HTTPException(422, detail={"message": exc.message, "hint": exc.hint}) from exc
    except IngestionRejected as exc:
        db.commit()
        detail = {"message": exc.message, "hint": exc.hint}
        if exc.mapping:
            detail |= exc.mapping.to_json()
        raise HTTPException(422, detail=detail) from exc

    db.commit()
    return {"run": _run_payload(outcome.run), **outcome.mapping.to_json()}
