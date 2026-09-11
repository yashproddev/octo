import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import DecisionLogEntry, ReconciliationResult
from app.modules.m4.decisions import DecisionRejected, record_decision

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
