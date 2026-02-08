"""FastAPI application factory for Flow Engine service."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router


# Global state
_start_time: float = 0.0


def get_uptime() -> float:
    """Get server uptime in seconds."""
    return time.time() - _start_time


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    global _start_time

    # Startup
    _start_time = time.time()

    # Add components import to register them
    from .. import components  # noqa: F401

    # Load composites
    from ..core import load_composites_from_directory
    composites_dir = Path(__file__).parent.parent / "composites"
    if composites_dir.exists():
        load_composites_from_directory(composites_dir)

    yield

    # Shutdown (nothing to clean up now)


def create_app(
    title: str = "Modular Flow Engine",
    version: str = "1.0.0",
) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=title,
        version=version,
        description="HTTP API for executing modular dataflow pipelines",
        lifespan=lifespan,
    )

    # CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(router)

    return app
