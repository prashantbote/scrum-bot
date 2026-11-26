"""Integrations (plan §6.2): meeting provider (LiveKit), mail (SMTP), Jira Cloud (OAuth 3LO)."""

from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse
from uuid import UUID

import aiosmtplib
import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session, require_role
from scrum_api.errors import Problem, not_found
from scrum_core.audit import write_audit
from scrum_core.db import session_for
from scrum_core.models import Integration
from scrum_core.models.base import IntegrationKind, IntegrationStatus, Role
from scrum_core.security.crypto import seal
from scrum_core.security.tokens import InvalidToken, sign, verify_payload
from scrum_core.settings import get_settings

router = APIRouter(tags=["integrations"])

ATLASSIAN_AUTH = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN = "https://auth.atlassian.com/oauth/token"  # noqa: S105 (URL, not a secret)
ATLASSIAN_RESOURCES = "https://api.atlassian.com/oauth/token/accessible-resources"
JIRA_SCOPES = "read:jira-work write:jira-work read:jira-user offline_access"

DISPLAY = {
    IntegrationKind.teams: "Meetings",
    IntegrationKind.mail: "Email (SMTP)",
    IntegrationKind.jira: "Jira Cloud",
    IntegrationKind.ado: "Azure DevOps",
}


def _display(kind: IntegrationKind) -> str:
    s = get_settings()
    if kind == IntegrationKind.teams:
        return "Meetings (LiveKit)" if s.meeting_provider == "livekit" else "Meetings (demo provider)"
    if kind == IntegrationKind.jira and s.pm_provider == "fake":
        return "Jira (demo catalog)"
    return DISPLAY[kind]


def _out(i: Integration) -> S.IntegrationOut:
    return S.IntegrationOut(
        id=i.id,
        kind=i.kind,
        status=i.status,
        display_name=i.display_name,
        detail=i.detail,
        last_checked_at=i.last_checked_at,
    )


async def _ensure_rows(db: AsyncSession, org_id: UUID) -> list[Integration]:
    rows = {i.kind: i for i in (await db.execute(select(Integration))).scalars()}
    for kind in IntegrationKind:
        if kind not in rows:
            rows[kind] = Integration(org_id=org_id, kind=kind, display_name=_display(kind))
            db.add(rows[kind])
    await db.flush()
    order = [IntegrationKind.teams, IntegrationKind.jira, IntegrationKind.mail, IntegrationKind.ado]
    return [rows[k] for k in order]


# ------------------------------------------------------------------------------- health checks


async def _check(kind: IntegrationKind, integ: Integration) -> tuple[IntegrationStatus, str]:
    s = get_settings()
    if kind == IntegrationKind.teams:
        if s.meeting_provider == "fake":
            return IntegrationStatus.connected, "Scripted demo meetings (SCRUM_MEETING_PROVIDER=fake)"
        url = s.livekit_url.replace("ws://", "http://").replace("wss://", "https://")
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                await http.get(url)
            return (
                IntegrationStatus.connected,
                f"LiveKit · {urlparse(url).netloc} · bot joins as “{s.bot_display_name}”",
            )
        except httpx.HTTPError as exc:
            return IntegrationStatus.error, f"LiveKit unreachable at {url}: {exc.__class__.__name__}"
    if kind == IntegrationKind.mail:
        if s.mail_provider == "memory":
            return IntegrationStatus.connected, "In-memory outbox (tests)"
        try:
            smtp = aiosmtplib.SMTP(hostname=s.smtp_host, port=s.smtp_port, timeout=5, start_tls=s.smtp_starttls)
            await smtp.connect()
            await smtp.noop()
            await smtp.quit()
            return IntegrationStatus.connected, f"SMTP {s.smtp_host}:{s.smtp_port} · from {s.mail_from}"
        except (aiosmtplib.SMTPException, OSError) as exc:
            return IntegrationStatus.error, f"SMTP {s.smtp_host}:{s.smtp_port} unreachable ({exc.__class__.__name__})"
    if kind == IntegrationKind.jira:
        if s.pm_provider == "fake":
            return IntegrationStatus.connected, "Demo ticket catalog · PROJ, BE"
        if not integ.encrypted_token:
            return IntegrationStatus.disconnected, "Not connected"
        if integ.expires_at and integ.expires_at < datetime.now(UTC) + timedelta(days=7):
            return IntegrationStatus.expiring, f"{integ.config.get('site_url', 'Jira')} · token refresh due"
        return IntegrationStatus.connected, f"{integ.config.get('site_url', 'Jira Cloud')} · OAuth"
    return IntegrationStatus.disconnected, "Not available in this build (planned for v2)"


# ------------------------------------------------------------------------------- routes


@router.get("/integrations", response_model=list[S.IntegrationOut])
async def list_integrations(
    p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.IntegrationOut]:
    return [_out(i) for i in await _ensure_rows(db, p.org_id)]


@router.post("/integrations/{kind}/connect", response_model=S.ConnectOut)
async def connect(
    kind: IntegrationKind,
    request: Request,
    p: Principal = Depends(require_role(Role.org_admin)),
    db: AsyncSession = Depends(db_session),
) -> S.ConnectOut:
    s = get_settings()
    rows = {i.kind: i for i in await _ensure_rows(db, p.org_id)}
    integ = rows[kind]
    if kind == IntegrationKind.ado:
        raise Problem(422, "Not available", "The Azure DevOps adapter is planned for v2.")
    if kind == IntegrationKind.jira and s.pm_provider == "jira":
        if not s.jira_client_id:
            raise Problem(422, "Jira not configured", "Set SCRUM_JIRA_CLIENT_ID and SCRUM_JIRA_CLIENT_SECRET.")
        state = sign(
            {
                "k": "oauth",
                "org": str(p.org_id),
                "user": str(p.user_id),
                "n": secrets.token_hex(6),
                "exp": int(time.time()) + 900,
            }
        )
        redirect = str(request.url_for("jira_callback"))
        url = (
            ATLASSIAN_AUTH
            + "?"
            + urlencode(
                {
                    "audience": "api.atlassian.com",
                    "client_id": s.jira_client_id,
                    "scope": JIRA_SCOPES,
                    "redirect_uri": redirect,
                    "state": state,
                    "response_type": "code",
                    "prompt": "consent",
                }
            )
        )
        return S.ConnectOut(authorize_url=url, integration=_out(integ))
    status, detail = await _check(kind, integ)
    integ.status, integ.detail, integ.last_checked_at = status, detail, datetime.now(UTC)
    integ.display_name = _display(kind)
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="integration.connected" if status != IntegrationStatus.error else "integration.failed",
        entity_type="integration",
        entity_id=integ.id,
        diff={"kind": kind, "detail": detail},
    )
    if status == IntegrationStatus.error:
        raise Problem(502, "Connection failed", detail)
    return S.ConnectOut(authorize_url=None, integration=_out(integ))


@router.get("/integrations/jira/callback", name="jira_callback", include_in_schema=True)
async def jira_callback(request: Request, code: str = Query(...), state: str = Query(...)) -> Response:
    """OAuth redirect target (browser, no bearer token): the signed ``state`` carries org and user."""
    s = get_settings()
    try:
        st = verify_payload(state, kind="oauth")
    except InvalidToken as exc:
        raise Problem(400, "Invalid OAuth state", str(exc)) from exc
    org_id = UUID(st["org"])
    async with httpx.AsyncClient(timeout=20) as http:
        tok = await http.post(
            ATLASSIAN_TOKEN,
            json={
                "grant_type": "authorization_code",
                "client_id": s.jira_client_id,
                "client_secret": s.jira_client_secret.get_secret_value() if s.jira_client_secret else "",
                "code": code,
                "redirect_uri": str(request.url_for("jira_callback")),
            },
        )
        if tok.status_code >= 400:
            raise Problem(502, "Jira token exchange failed", tok.text[:300])
        tokens = tok.json()
        res = await http.get(ATLASSIAN_RESOURCES, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        res.raise_for_status()
        site = res.json()[0]
    sealed = seal(
        json.dumps({"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token")}),
        aad=f"integration:{org_id}:jira",
    )
    async with session_for(org_id) as db:
        integ = (await db.execute(select(Integration).where(Integration.kind == IntegrationKind.jira))).scalar_one()
        integ.encrypted_token, integ.wrapped_dek, integ.key_id = sealed.ciphertext, sealed.wrapped_dek, sealed.key_id
        integ.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        integ.config = {"api_base_url": f"https://api.atlassian.com/ex/jira/{site['id']}", "site_url": site["url"]}
        integ.status, integ.detail = IntegrationStatus.connected, f"{site['url']} · OAuth"
        integ.last_checked_at = datetime.now(UTC)
        await write_audit(
            db,
            org_id=org_id,
            actor_user_id=UUID(st["user"]),
            actor_name="OAuth callback",
            action="integration.connected",
            entity_type="integration",
            entity_id=integ.id,
            diff={"kind": "jira", "site": site["url"]},
        )
    return RedirectResponse(f"{s.public_app_url}/integrations?connected=jira", status_code=302)


@router.post("/integrations/{integration_id}/test", response_model=S.IntegrationOut)
async def test_integration(
    integration_id: UUID, p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> S.IntegrationOut:
    integ = await db.get(Integration, integration_id)
    if integ is None:
        raise not_found("Integration")
    if integ.status != IntegrationStatus.disconnected:
        integ.status, integ.detail = await _check(integ.kind, integ)
    integ.last_checked_at = datetime.now(UTC)
    return _out(integ)


@router.delete("/integrations/{integration_id}", status_code=204, response_class=Response)
async def delete_integration(
    integration_id: UUID, p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> Response:
    integ = await db.get(Integration, integration_id)
    if integ is None:
        raise not_found("Integration")
    integ.status, integ.detail, integ.last_checked_at = IntegrationStatus.disconnected, "Not connected", None
    integ.encrypted_token = integ.wrapped_dek = None
    integ.key_id, integ.expires_at = None, None
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="integration.disconnected",
        entity_type="integration",
        entity_id=integ.id,
        diff={"kind": integ.kind},
    )
    return Response(status_code=204)
