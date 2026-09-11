"""Human review. Decisions are appended, never applied destructively.

`system_status` on a result is written once by the engine. Everything a person
does afterwards becomes a new decision_log row, and `current_status` is derived
from the latest one. The machine's original verdict therefore stays recoverable
no matter how many times a human overturns it.
"""

from sqlalchemy.orm import Session

from app.models import DecisionAction, DecisionLogEntry, ReconciliationResult, ResultStatus
from app.modules.m4.rules import RULE_VERSION


class DecisionRejected(Exception):
    pass


# What each human action means for the result's current status.
_TRANSITIONS = {
    DecisionAction.APPROVE: ResultStatus.AUTO_CLOSED,
    DecisionAction.REJECT: ResultStatus.MISMATCH,
    DecisionAction.RESOLVE: ResultStatus.AUTO_CLOSED,
    DecisionAction.OVERRIDE: ResultStatus.AUTO_CLOSED,
}

_REASON_REQUIRED = {DecisionAction.OVERRIDE, DecisionAction.REJECT}


def record_bulk(
    db: Session,
    *,
    results: list[ReconciliationResult],
    action: str,
    actor: str,
    reason: str | None = None,
) -> list[DecisionLogEntry]:
    """Apply one action across many results.

    Clearing a queue of two hundred exceptions one screen at a time is not a
    workflow anybody completes. Each line still gets its own decision row with
    its own before/after status, so the audit trail is identical to deciding
    them individually — only the clicking is batched, not the record.
    """
    return [
        record_decision(db, result=r, action=action, actor=actor, reason=reason)
        for r in results
    ]


def record_decision(
    db: Session,
    *,
    result: ReconciliationResult,
    action: str,
    actor: str,
    reason: str | None = None,
) -> DecisionLogEntry:
    try:
        parsed = DecisionAction(action)
    except ValueError as exc:
        allowed = ", ".join(a for a in _TRANSITIONS)
        raise DecisionRejected(f"'{action}' is not a valid action. Use one of: {allowed}.") from exc

    if parsed is DecisionAction.AUTO_CLOSE:
        raise DecisionRejected("AUTO_CLOSE is reserved for the engine and cannot be applied by a person.")

    if parsed in _REASON_REQUIRED and not (reason or "").strip():
        raise DecisionRejected(f"A reason is required when the action is {parsed.value}.")

    from_status = result.current_status
    to_status = _TRANSITIONS[parsed]

    entry = DecisionLogEntry(
        reconciliation_result_id=result.id,
        actor=actor,
        action=parsed,
        from_status=from_status,
        to_status=to_status,
        reason=(reason or "").strip() or None,
        rule_version=result.run.rule_version if result.run else RULE_VERSION,
        is_system=False,
    )
    db.add(entry)

    # Only the derived column moves. system_status is never touched.
    result.current_status = to_status
    db.flush()
    return entry
