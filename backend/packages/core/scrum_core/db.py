"""Async engine and tenant-scoped sessions.

Every tenant query runs inside ``session_for(org_id)``, which sets ``app.org_id`` for the
transaction so PostgreSQL row-level security (plan §4.2) filters every table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from scrum_core.settings import get_settings


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def _factory(url: str | None = None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(url), expire_on_commit=False)


async def set_org_context(session: AsyncSession, org_id: UUID | str) -> None:
    # set_config(..., is_local => true) is the bind-parameter-safe form of SET LOCAL.
    await session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})


@asynccontextmanager
async def session_for(org_id: UUID | str) -> AsyncIterator[AsyncSession]:
    """One transaction, scoped to one tenant. Commits on success, rolls back on error."""
    async with _factory()() as session, session.begin():
        await set_org_context(session, org_id)
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """No tenant context: only non-RLS tables (organizations) and SECURITY DEFINER lookups are visible."""
    async with _factory()() as session, session.begin():
        yield session


@asynccontextmanager
async def owner_session() -> AsyncIterator[AsyncSession]:
    """Table-owner connection for seeding and maintenance scripts. Never used by request handlers."""
    async with _factory(get_settings().database_owner_url)() as session, session.begin():
        yield session


async def dispose_engines() -> None:
    for url in {get_settings().database_url, get_settings().database_owner_url}:
        if get_engine.cache_info().currsize:
            await get_engine(url).dispose()
    get_engine.cache_clear()
