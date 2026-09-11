import csv
import io
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import DecisionLogEntry, ReconciliationResult
from app.modules.m4.decisions import DecisionRejected, record_bulk, record_decision

router = APIRouter()


def actor(x_actor: str = Header(default="demo.user")) -> str:
    return x_actor


@router.post("/decisions", status_code=201)
def create_decision(
    payload: dict,
    db: Session = Depends(get_db),
    who: str = Depends(actor),
) -> dict:
    result_id = payload.get("result_id")
    if not result_id:
        raise HTTPException(422, detail={"message": "'result_id' is required."})

    result = db.execute(
        select(ReconciliationResult)
        .where(ReconciliationResult.id == uuid.UUID(str(result_id)))
        .options(selectinload(ReconciliationResult.run))
    ).scalar_one_or_none()
    if not result:
        raise HTTPException(404, detail={"message": "Result not found."})

    try:
        entry = record_decision(
            db,
            result=result,
            action=str(payload.get("action", "")),
            actor=who,
            reason=payload.get("reason"),
        )
    except DecisionRejected as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from exc

    db.commit()
    return {
        "decision": {
            "id": str(entry.id),
            "actor": entry.actor,
            "action": entry.action,
            "from_status": entry.from_status,
            "to_status": entry.to_status,
            "reason": entry.reason,
            "decided_at": entry.decided_at.isoformat(),
        },
        "result": {
            "id": str(result.id),
            "system_status": result.system_status,
            "current_status": result.current_status,
        },
    }


@router.post("/decisions/bulk", status_code=201)
def create_bulk(
    payload: dict,
    db: Session = Depends(get_db),
    who: str = Depends(actor),
) -> dict:
    ids = payload.get("result_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(422, detail={"message": "'result_ids' must be a non-empty list."})
    if len(ids) > 500:
        raise HTTPException(
            422,
            detail={
                "message": f"{len(ids)} lines is above the 500-line batch limit.",
                "hint": "Filter to a narrower set and apply the action again.",
            },
        )

    try:
        uuids = [uuid.UUID(str(i)) for i in ids]
    except ValueError as exc:
        raise HTTPException(422, detail={"message": "One of the result ids is not valid."}) from exc

    results = db.execute(
        select(ReconciliationResult)
        .where(ReconciliationResult.id.in_(uuids))
        .options(selectinload(ReconciliationResult.run))
    ).scalars().all()

    missing = len(uuids) - len(results)
    if not results:
        raise HTTPException(404, detail={"message": "None of those results were found."})

    try:
        entries = record_bulk(
            db,
            results=results,
            action=str(payload.get("action", "")),
            actor=who,
            reason=payload.get("reason"),
        )
    except DecisionRejected as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from exc

    db.commit()
    return {
        "applied": len(entries),
        "not_found": missing,
        "action": entries[0].action if entries else None,
    }


@router.get("/decisions")
def list_decisions(
    db: Session = Depends(get_db),
    include_system: bool = True,
    actor_filter: str | None = Query(default=None, alias="actor"),
    action: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict:
    stmt = select(DecisionLogEntry).order_by(desc(DecisionLogEntry.decided_at))
    if not include_system:
        stmt = stmt.where(DecisionLogEntry.is_system.is_(False))
    if actor_filter:
        stmt = stmt.where(DecisionLogEntry.actor == actor_filter)
    if action:
        stmt = stmt.where(DecisionLogEntry.action == action)

    entries = db.execute(
        stmt.limit(limit).offset(offset).options(selectinload(DecisionLogEntry.result))
    ).scalars().all()

    return {
        "decisions": [
            {
                "id": str(e.id),
                "result_id": str(e.reconciliation_result_id),
                "actor": e.actor,
                "action": e.action,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "reason": e.reason,
                "rule_version": e.rule_version,
                "is_system": e.is_system,
                "decided_at": e.decided_at.isoformat(),
                "system_status": e.result.system_status if e.result else None,
                "snapshot": (e.result.snapshot if e.result else None),
            }
            for e in entries
        ]
    }


@router.get("/decisions/export.csv", response_class=PlainTextResponse)
def export_decisions(db: Session = Depends(get_db)) -> PlainTextResponse:
    """The audit trail as a file. Finance and audit live in spreadsheets, and a
    log that cannot leave the screen is not much use at close."""
    entries = db.execute(
        select(DecisionLogEntry)
        .order_by(desc(DecisionLogEntry.decided_at))
        .options(selectinload(DecisionLogEntry.result))
    ).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "decided_at", "actor", "action", "is_system", "po_number", "item",
        "invoice_number", "system_verdict", "from_status", "to_status",
        "exposure", "reason", "rule_version", "result_id",
    ])
    for e in entries:
        snap = (e.result.snapshot if e.result else None) or {}
        writer.writerow([
            e.decided_at.isoformat(), e.actor, e.action, e.is_system,
            snap.get("po_number", ""), snap.get("item", ""), snap.get("invoice_number", ""),
            e.result.system_status if e.result else "", e.from_status, e.to_status,
            snap.get("exposure", ""), e.reason or "", e.rule_version, str(e.reconciliation_result_id),
        ])

    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="m4-decision-log.csv"'},
    )
