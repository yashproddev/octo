from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="OctoProc M4 — Vendor Reconciliation & Closure",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Only needed for local dev, where Vite serves on a different port.
    # In production the SPA and API share one Vercel origin, so this is empty.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
