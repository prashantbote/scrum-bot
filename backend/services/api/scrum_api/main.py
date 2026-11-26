"""FastAPI app factory (plan §6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scrum_api import errors
from scrum_api.middleware import IdempotencyMiddleware, RateLimitMiddleware
from scrum_api.routers import audit, blockers, integrations, metrics, org, public, sessions, teams
from scrum_core import telemetry
from scrum_core.db import dispose_engines
from scrum_core.settings import get_settings

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engines()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Scrum Bot API",
        version="1.0.0",
        description="Config, sessions, blockers, review queue and dashboard metrics for Scrum Bot. "
        "Errors are RFC 7807 `application/problem+json`.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    errors.install(app)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Mock-User"],
        max_age=600,
    )
    for r in (
        org.router,
        teams.router,
        integrations.router,
        sessions.router,
        blockers.router,
        public.router,
        metrics.router,
        audit.router,
    ):
        app.include_router(r, prefix=API_PREFIX)
    app.include_router(audit.health)
    telemetry.setup("scrum-api", app)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("scrum_api.main:app", host="0.0.0.0", port=8800, proxy_headers=True)  # noqa: S104
