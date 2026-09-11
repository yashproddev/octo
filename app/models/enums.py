from enum import StrEnum


class IngestionStatus(StrEnum):
    UPLOADED = "UPLOADED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    STAGED = "STAGED"
    NORMALIZED = "NORMALIZED"


class ReconciliationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResultStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    DUPLICATE = "DUPLICATE"
    INCOMPLETE = "INCOMPLETE"
    REVIEW = "REVIEW"
    AUTO_CLOSED = "AUTO_CLOSED"


class DecisionAction(StrEnum):
    AUTO_CLOSE = "AUTO_CLOSE"  # written by the engine, never by a person
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RESOLVE = "RESOLVE"
    OVERRIDE = "OVERRIDE"
