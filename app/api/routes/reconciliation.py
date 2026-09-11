import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models import (
    DecisionLogEntry,
    IngestionRun,
    ReconciliationResult,
    ReconciliationRun,
    StagingRecord,
)
from app.modules.m4.engine import reconcile
from app.modules.m4.normalize import normalize_run
from app.modules.m4.rules import Tolerances

router = APIRouter()


def _run_payload(run: ReconciliationRun) -> dict:
    return {
        "id": str(run.id),
        "ingestion_run_id": str(run.ingestion_run_id),
        "rule_version": run.rule_version,
        "tolerances": run.tolerances,
        "status": run.status,
        "status_counts": run.status_counts or {},
        "total_exposure": str(run.total_exposure) if run.total_exposure is not None else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# Short labels for the results table. Without these a row whose only failure is
# on a column the table does not show (tax, most often) reads as an unexplained
# mismatch — every visible number agrees, yet the status says otherwise.
_RULE_SHORT = {
    "R1": "PO ref",
    "R2": "GRN qty",
    "R3": "Invoice qty",
    "R4": "Price",
    "R5": "Tax",
    "R6": "Duplicate",
    "R7": "Data",
}


def _result_row(result: ReconciliationResult) -> dict:
    failed = [
        _RULE_SHORT.get(f.get("rule_id"), f.get("rule_id"))
        for f in (result.findings or [])
        if not f.get("passed") and not f.get("skipped")
    ]
    unchecked = [
        _RULE_SHORT.get(f.get("rule_id"), f.get("rule_id"))
        for f in (result.findings or [])
        if f.get("skipped")
    ]
    return {
        "id": str(result.id),
        "system_status": result.system_status,
        "current_status": result.current_status,
        "explanation": result.explanation,
        "failed_checks": failed,
        "unchecked": unchecked,
        "decision_count": len([d for d in result.decisions if not d.is_system]),
        **(result.snapshot or {}),
    }


@router.post("/ingestion/runs/{run_id}/normalize")
def normalize(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(404, detail={"message": "Ingestion run not found."})
    if run.status == "FAILED_VALIDATION":
        raise HTTPException(
            422,
            detail={
                "message": "This run failed validation and cannot be normalized.",
                "hint": "Correct the column mapping first.",
            },
        )

    summary = normalize_run(db, run)
    db.commit()
    return {"run_id": str(run.id), "status": run.status, "summary": summary.as_dict()}


@router.get("/config/tolerances")
def tolerances() -> dict:
    return {"defaults": Tolerances().as_dict(), "rule_version": settings.rule_version}


@router.post("/reconciliation/runs", status_code=201)
def create_run(payload: dict, db: Session = Depends(get_db)) -> dict:
    run_id = payload.get("ingestion_run_id")
    if not run_id:
        raise HTTPException(422, detail={"message": "'ingestion_run_id' is required."})

    run = db.get(IngestionRun, uuid.UUID(str(run_id)))
    if not run:
        raise HTTPException(404, detail={"message": "Ingestion run not found."})

    staged = db.execute(
        select(func.count()).select_from(StagingRecord).where(
            StagingRecord.ingestion_run_id == run.id
        )
    ).scalar_one()
    if staged == 0:
        raise HTTPException(
            422,
            detail={
                "message": "This run has no staged rows to reconcile.",
                "hint": "Upload a file and confirm the column mapping first.",
            },
        )

    if run.status != "NORMALIZED":
        normalize_run(db, run)

    recon = reconcile(db, run, tolerances=payload.get("tolerances"))
    db.commit()
    return {"run": _run_payload(recon)}


@router.get("/reconciliation/runs")
def list_runs(db: Session = Depends(get_db), limit: int = Query(50, le=200)) -> dict:
    runs = db.execute(
        select(ReconciliationRun).order_by(desc(ReconciliationRun.created_at)).limit(limit)
    ).scalars().all()
    return {"runs": [_run_payload(r) for r in runs]}


@router.get("/reconciliation/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = db.get(ReconciliationRun, run_id)
    if not run:
        raise HTTPException(404, detail={"message": "Reconciliation run not found."})
    return {"run": _run_payload(run)}


@router.get("/reconciliation/runs/{run_id}/results")
def list_results(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict:
    stmt = (
        select(ReconciliationResult)
        .where(ReconciliationResult.reconciliation_run_id == run_id)
        .options(selectinload(ReconciliationResult.decisions))
    )
    if status:
        stmt = stmt.where(ReconciliationResult.current_status == status)

    results = db.execute(stmt.limit(limit).offset(offset)).scalars().all()

    if q:
        needle = q.lower()
        results = [
            r for r in results
            if any(needle in str(v).lower() for v in (r.snapshot or {}).values())
        ]

    results.sort(key=lambda r: (r.snapshot or {}).get("row_number") or 0)
    return {"results": [_result_row(r) for r in results], "count": len(results)}


@router.get("/reconciliation/results/{result_id}")
def get_result(result_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    result = db.execute(
        select(ReconciliationResult)
        .where(ReconciliationResult.id == result_id)
        .options(
            selectinload(ReconciliationResult.decisions),
            selectinload(ReconciliationResult.run),
        )
    ).scalar_one_or_none()
    if not result:
        raise HTTPException(404, detail={"message": "Result not found."})

    staging = db.get(StagingRecord, result.staging_record_id) if result.staging_record_id else None

    return {
        "id": str(result.id),
        "system_status": result.system_status,
        "current_status": result.current_status,
        "explanation": result.explanation,
        "snapshot": result.snapshot,
        "findings": result.findings,
        "rule_version": result.run.rule_version if result.run else None,
        "tolerances": result.run.tolerances if result.run else None,
        "source_row": {
            "row_number": staging.row_number,
            "raw_data": staging.raw_data,
            "errors": staging.errors or [],
        } if staging else None,
        "decisions": [
            {
                "id": str(d.id),
                "actor": d.actor,
                "action": d.action,
                "from_status": d.from_status,
                "to_status": d.to_status,
                "reason": d.reason,
                "rule_version": d.rule_version,
                "is_system": d.is_system,
                "decided_at": d.decided_at.isoformat(),
            }
            for d in sorted(result.decisions, key=lambda x: x.decided_at)
        ],
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    latest = db.execute(
        select(ReconciliationRun).order_by(desc(ReconciliationRun.created_at)).limit(1)
    ).scalar_one_or_none()

    ingestion_runs = db.execute(
        select(IngestionRun).order_by(desc(IngestionRun.created_at)).limit(10)
    ).scalars().all()

    decisions = db.execute(
        select(func.count()).select_from(DecisionLogEntry).where(
            DecisionLogEntry.is_system.is_(False)
        )
    ).scalar_one()

    open_exposure = db.execute(
        select(func.coalesce(func.sum(ReconciliationRun.total_exposure), 0))
    ).scalar_one()

    return {
        "latest_run": _run_payload(latest) if latest else None,
        "open_exposure": str(open_exposure),
        "totals": {
            "ingestion_runs": db.execute(select(func.count()).select_from(IngestionRun)).scalar_one(),
            "reconciliation_runs": db.execute(
                select(func.count()).select_from(ReconciliationRun)
            ).scalar_one(),
            "results": db.execute(select(func.count()).select_from(ReconciliationResult)).scalar_one(),
            "human_decisions": decisions,
        },
        "recent_ingestion_runs": [
            {
                "id": str(r.id),
                "source_filename": r.source_filename,
                "status": r.status,
                "row_count": r.row_count,
                "error_row_count": r.error_row_count,
                "created_at": r.created_at.isoformat(),
            }
            for r in ingestion_runs
        ],
    }


@router.get("/reconciliation/runs/{run_id}/export.csv", response_class=PlainTextResponse)
def export_results(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    status: str | None = None,
) -> PlainTextResponse:
    """Results as a file, optionally filtered to one status.

    Exceptions get worked in a spreadsheet and chased over email; a queue that
    cannot leave the browser does not fit how this job is actually done.
    """
    stmt = (
        select(ReconciliationResult)
        .where(ReconciliationResult.reconciliation_run_id == run_id)
        .options(selectinload(ReconciliationResult.decisions))
    )
    if status:
        stmt = stmt.where(ReconciliationResult.current_status == status)

    results = db.execute(stmt).scalars().all()
    results.sort(key=lambda r: (r.snapshot or {}).get("row_number") or 0)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "row", "po_number", "vendor", "item", "invoice_number",
        "po_quantity", "grn_quantity", "invoice_quantity",
        "po_unit_price", "invoice_unit_price", "tax",
        "system_status", "current_status", "exposure",
        "failed_checks", "explanation",
    ])
    for r in results:
        s = r.snapshot or {}
        failed = [
            _RULE_SHORT.get(f.get("rule_id"), f.get("rule_id"))
            for f in (r.findings or [])
            if not f.get("passed") and not f.get("skipped")
        ]
        writer.writerow([
            s.get("row_number", ""), s.get("po_number", ""), s.get("vendor", ""),
            s.get("item", ""), s.get("invoice_number", ""),
            s.get("po_quantity", ""), s.get("grn_quantity", ""), s.get("invoice_quantity", ""),
            s.get("po_unit_price", ""), s.get("invoice_unit_price", ""), s.get("tax", ""),
            r.system_status, r.current_status, s.get("exposure", ""),
            "; ".join(failed), r.explanation or "",
        ])

    label = f"-{status.lower()}" if status else ""
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="m4-results{label}.csv"'},
    )
