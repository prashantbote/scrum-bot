"""Audit log (org admins) and health probes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api import schemas as S
from scrum_api.auth import Principal, db_session, require_role
from scrum_api.pagination import Page
from scrum_core.db import system_session
from scrum_core.models import AuditLog
from scrum_core.models.base import Role
from scrum_core.settings import get_settings

router = APIRouter(tags=["audit"])
health = APIRouter(tags=["health"])


@router.get("/audit-log", response_model=S.Paginated[S.AuditEntryOut])
async def audit_log(
    entity: str | None = None,
    actor: str | None = Query(default=None, max_length=100),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    page: Page = Depends(),
    p: Principal = Depends(require_role(Role.org_admin)),
    db: AsyncSession = Depends(db_session),
) -> S.Paginated[S.AuditEntryOut]:
    stmt = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id)
    if entity:
        stmt = stmt.where(AuditLog.entity_type == entity)
    if actor:
        stmt = stmt.where(AuditLog.actor_name.ilike(f"%{actor}%"))
    utc = ZoneInfo("UTC")
    if from_:
        stmt = stmt.where(AuditLog.at >= datetime.combine(from_, time.min, utc))
    if to:
        stmt = stmt.where(AuditLog.at < datetime.combine(to + timedelta(days=1), time.min, utc))
    rows, nxt = await page.fetch(db, stmt)
    return S.Paginated[S.AuditEntryOut](
        items=[
            S.AuditEntryOut(
                id=a.id,
                at=a.at,
                actor_name=a.actor_name,
                action=a.action,
                entity_type=a.entity_type,
                entity_id=a.entity_id,
                diff=a.diff or {},
            )
            for a in rows
        ],
        next_cursor=nxt,
    )


@health.get("/healthz", response_model=S.Health)
async def healthz() -> S.Health:
    return S.Health(status="ok")


@health.get("/readyz", response_model=S.Health)
async def readyz(response: Response) -> S.Health:
    checks: dict[str, str] = {}
    try:
        async with system_session() as s:
            await s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - exercised manually
        checks["database"] = f"error: {exc.__class__.__name__}"
    if get_settings().temporal_enabled:
        try:
            from scrum_core.workflow_client import get_client

            await (await get_client()).service_client.check_health()
            checks["temporal"] = "ok"
        except Exception as exc:
            checks["temporal"] = f"error: {exc.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return S.Health(status="ok" if ok else "degraded", checks=checks)
