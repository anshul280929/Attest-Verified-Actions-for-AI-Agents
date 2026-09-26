"""Main FastAPI application entrypoint for Attest gateway."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError

from src.attest.api.router import router as actions_router
from src.attest.clients import create_downstream_client, create_verifier_client
from src.attest.config import settings
from src.attest.contracts import ContractRegistry, load_contracts

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("attest.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context for startup and shutdown procedures."""
    logger.info("Starting Attest Gateway Service...")

    # Fail-fast contract loading on startup
    try:
        contracts_dict = load_contracts("contracts")
        app.state.contract_registry = ContractRegistry(contracts_dict)
        logger.info(f"Loaded {len(contracts_dict)} contracts: {list(contracts_dict.keys())}")
    except Exception as exc:
        logger.critical(f"Failed to load contracts on startup: {exc}")
        raise

    # Initialize shared HTTP clients
    app.state.downstream_client = create_downstream_client()
    app.state.verifier_client = create_verifier_client()

    yield

    # Teardown HTTP clients
    await app.state.downstream_client.aclose()
    await app.state.verifier_client.aclose()
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
