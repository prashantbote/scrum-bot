"""Authentication (plan §6.1) with any OIDC provider, plus a dev persona mode.

* ``oidc``: bearer JWT validated against the issuer's JWKS (Keycloak, Authentik, Zitadel or Entra ID).
  The issuer maps to ``organizations.idp_issuer``; ``sub`` maps to ``users.idp_subject``.
  First sign-in of an unknown issuer creates the tenant and makes that user ``org_admin``
  (the open-source equivalent of "first user after admin consent"); later users are JIT-provisioned
  as ``member`` (or the role in ``SCRUM_OIDC_ROLE_CLAIM``).
* ``dev``: trusts ``X-Mock-User: <idp_subject>`` — what the frontend's persona picker sends.
  Refused in production by settings validation.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api.errors import Problem
from scrum_core.db import _factory, set_org_context
from scrum_core.models import Organization, Team, TeamMember, User
from scrum_core.models.base import Role
from scrum_core.settings import get_settings


@dataclass
class Principal:
    user_id: UUID
    org_id: UUID
    role: Role
    display_name: str
    email: str
    lead_team_ids: list[UUID] = field(default_factory=list)
    member_team_ids: list[UUID] = field(default_factory=list)
    ip: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.org_admin


# ------------------------------------------------------------------------------- JWKS cache

_jwks: dict[str, tuple[float, jwt.PyJWKSet]] = {}


async def _jwks_for(issuer: str) -> jwt.PyJWKSet:
    s = get_settings()
    cached = _jwks.get(issuer)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    async with httpx.AsyncClient(timeout=10) as http:
        url = s.oidc_jwks_url
        if not url:
            conf = (await http.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration")).json()
            url = conf["jwks_uri"]
        keyset = jwt.PyJWKSet.from_dict((await http.get(url)).json())
    _jwks[issuer] = (time.time(), keyset)
    return keyset


async def verify_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Problem(401, "Unauthorized", "Malformed token.") from exc
    issuer = str(unverified.get("iss", ""))
    if s.oidc_issuer and issuer.rstrip("/") != s.oidc_issuer.rstrip("/"):
        raise Problem(401, "Unauthorized", "Token issuer is not trusted.")
    keyset = await _jwks_for(issuer)
    key = next((k for k in keyset.keys if k.key_id == header.get("kid")), None)
    if key is None:
        _jwks.pop(issuer, None)  # key rotation: refetch next time
        raise Problem(401, "Unauthorized", "Unknown signing key.")
    try:
        return jwt.decode(
            token,
            key.key,
            algorithms=[header.get("alg", "RS256")],
            audience=s.oidc_audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise Problem(401, "Unauthorized", f"Invalid token: {exc}") from exc


# ------------------------------------------------------------------------------- lookups


async def _find_user(session: AsyncSession, subject: str, issuer: str | None) -> tuple[UUID, UUID] | None:
    row = (
        await session.execute(text("SELECT org_id, user_id FROM auth_find_user(:s, :i)"), {"s": subject, "i": issuer})
    ).first()
    return (row[0], row[1]) if row else None


async def _provision(session: AsyncSession, claims: dict[str, Any]) -> tuple[UUID, UUID]:
    """Just-in-time provisioning for OIDC sign-ins."""
    issuer = str(claims["iss"])
    org = (await session.execute(select(Organization).where(Organization.idp_issuer == issuer))).scalar_one_or_none()
    first_user = org is None
    if org is None:
        org = Organization(
            name=str(claims.get("org_name") or claims.get("azp") or "New organization"), idp_issuer=issuer
        )
        session.add(org)
        await session.flush()
    await set_org_context(session, org.id)
    claim_role = claims.get(get_settings().oidc_role_claim)
    role = (
        Role.org_admin
        if first_user
        else (Role(str(claim_role)) if str(claim_role) in Role.__members__ else Role.member)
    )
    email = str(claims.get("email") or claims.get("preferred_username") or f"{claims['sub']}@unknown")
    user = User(
        org_id=org.id,
        idp_subject=str(claims["sub"]),
        email=email.lower(),
        display_name=str(claims.get("name") or email.split("@")[0]),
        role=role,
        aliases=[],
    )
    session.add(user)
    await session.flush()
    return org.id, user.id


async def _principal(session: AsyncSession, org_id: UUID, user_id: UUID, ip: str | None) -> Principal:
    await set_org_context(session, org_id)
    user = await session.get(User, user_id)
    if user is None or user.erased_at is not None:
        raise Problem(401, "Unauthorized", "Your account is not active.")
    lead = (await session.execute(select(Team.id).where(Team.lead_user_id == user_id))).scalars().all()
    member = (await session.execute(select(TeamMember.team_id).where(TeamMember.user_id == user_id))).scalars().all()
    return Principal(
        user_id=user.id,
        org_id=org_id,
        role=user.role,
        display_name=user.display_name,
        email=user.email,
        lead_team_ids=list(lead),
        member_team_ids=list(dict.fromkeys(member)),
        ip=ip,
    )


# ------------------------------------------------------------------------------- dependencies


async def db_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request. Tenant context is set by ``current_user``."""
    async with _factory()() as session:
        try:
            await session.begin()
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def current_user(request: Request, session: AsyncSession = Depends(db_session)) -> Principal:
    s = get_settings()
    ip = request.client.host if request.client else None
    if s.auth_mode == "dev":
        subject = request.headers.get("X-Mock-User") or request.headers.get("X-Dev-User")
        if not subject:
            raise Problem(401, "Unauthorized", "Sign in to continue.")
        found = await _find_user(session, subject, None)
        if not found:
            raise Problem(401, "Unauthorized", f"Unknown dev persona {subject!r}. Run `make seed`.")
        return await _principal(session, found[0], found[1], ip)

    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Problem(401, "Unauthorized", "Sign in to continue.")
    claims = await verify_jwt(auth.split(" ", 1)[1])
    found = await _find_user(session, str(claims["sub"]), str(claims["iss"]))
    if not found:
        found = await _provision(session, claims)
    return await _principal(session, found[0], found[1], ip)


def require_role(*roles: Role):  # type: ignore[no-untyped-def]
    async def _dep(p: Principal = Depends(current_user)) -> Principal:
        if p.role not in roles:
            raise Problem(403, "Forbidden", "Your role can't do this.")
        return p

    return _dep
