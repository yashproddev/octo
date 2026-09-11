from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        version = db.execute(text("select version()")).scalar_one()
        database = {"connected": True, "server": version.split(",")[0]}
    except Exception as exc:
        database = {"connected": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "service": "octoproc-m4",
        "status": "ok" if database["connected"] else "degraded",
        "rule_version": settings.rule_version,
        "database": database,
    }
