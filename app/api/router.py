from fastapi import APIRouter

from app.api.routes import decisions, health, ingestion, reconciliation

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(ingestion.router, tags=["ingestion"])
api_router.include_router(reconciliation.router, tags=["reconciliation"])
api_router.include_router(decisions.router, tags=["decisions"])
