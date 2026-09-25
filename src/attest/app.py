"""Main FastAPI application entrypoint for Attest gateway."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError

from src.attest.api.router import router as actions_router
from src.attest.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("attest.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context for startup and shutdown procedures."""
    logger.info("Starting Attest Gateway Service...")
    yield
    logger.info("Shutting down Attest Gateway Service...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Attest Gateway",
        description="Reliability layer for AI agents taking side-effecting actions",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def db_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Ledger guard intercepted DB failure: {exc}")
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "error": "ledger_unavailable",
                    "message": "Cannot record action; execution blocked",
                }
            },
        )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "attest-gateway"}

    app.include_router(actions_router)
    return app


app = create_app()
