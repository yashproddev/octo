import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import settings

logger = logging.getLogger("octoproc.m4")


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

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Every deliberate failure in this app returns {message, hint}. Without
        # this, an unforeseen one returns a bare "Internal Server Error" string
        # that the UI cannot render and the user cannot act on.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "message": "Something went wrong while processing this request.",
                    "hint": "The error has been logged. Re-check the uploaded file, or try again.",
                    "error_type": type(exc).__name__,
                }
            },
        )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
