"""Main FastAPI application entrypoint for the downstream mock service."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.downstream_mock.routers.orders import router as orders_router
from src.downstream_mock.routers.refunds import router as refunds_router
from src.downstream_mock.store import store


def create_mock_app() -> FastAPI:
    """Create and configure the downstream mock FastAPI application."""
    app = FastAPI(
        title="Attest Downstream Mock Service",
        description="Orders and payments mock with deterministic chaos injection",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "downstream-mock"}

    @app.post("/reset", tags=["system"])
    async def reset() -> dict[str, str]:
        """Reset mock in-memory database to initial state."""
        store.reset()
        return {"status": "reset_completed"}

    app.include_router(orders_router)
    app.include_router(refunds_router)
    return app


app = create_mock_app()
