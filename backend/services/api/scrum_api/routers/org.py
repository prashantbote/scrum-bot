"""/me, onboarding, org settings, users (+ DPDP/GDPR erase and export)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session, require_role
from scrum_api.errors import Problem, forbidden, invalid, not_found
from scrum_api.pagination import Page
from scrum_core.audit import write_audit
from scrum_core.models import Blocker, MemberUpdateRow, Organization, Team, TeamMember, TranscriptSegment, User
from scrum_core.models.base import Role

router = APIRouter(tags=["identity & org"])
REDACTED = "[redacted on erasure request]"


def _rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def _me(p: Principal, db: AsyncSession) -> S.Me:
    org = await db.get(Organization, p.org_id)
    assert org is not None
    return S.Me(
        id=p.user_id,
        org_id=p.org_id,
        org_name=org.name,
        display_name=p.display_name,
        email=p.email,
        role=p.role,
        lead_team_ids=p.lead_team_ids,
        member_team_ids=p.member_team_ids,
        onboarded=org.onboarded_at is not None,
    )


@router.get("/me", response_model=S.Me)
async def me(p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)) -> S.Me:
    return await _me(p, db)


@router.post("/orgs/onboard", response_model=S.Me)
async def onboard(
    body: S.OnboardIn, p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> S.Me:
    org = await db.get(Organization, p.org_id)
    assert org is not None
    org.name = body.name.strip()
    org.onboarded_at = org.onboarded_at or datetime.now(UTC)
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="org.onboarded",
        entity_type="organization",
        entity_id=org.id,
        diff={"name": org.name},
    )
    return await _me(p, db)


def _settings(org: Organization) -> S.OrgSettings:
    return S.OrgSettings(
        name=org.name,
        consent_text=org.consent_text,
        retention_days_audio=org.retention_days_audio,
        retention_days_transcript=org.retention_days_transcript,
        escalation_days=org.escalation_days,
    )


@router.get("/org", response_model=S.OrgSettings)
@router.get("/org/settings", response_model=S.OrgSettings)
async def get_settings_(p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)) -> S.OrgSettings:
    org = await db.get(Organization, p.org_id)
    assert org is not None
    return _settings(org)


@router.patch("/org", response_model=S.OrgSettings)
@router.patch("/org/settings", response_model=S.OrgSettings)
async def patch_settings(
    body: S.OrgSettingsPatch,
    p: Principal = Depends(require_role(Role.org_admin)),
    db: AsyncSession = Depends(db_session),
) -> S.OrgSettings:
    org = await db.get(Organization, p.org_id)
    assert org is not None
    diff = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None and getattr(org, k) != v:
            diff[k] = [getattr(org, k), v]
            setattr(org, k, v)
    if diff:
        await write_audit(
            db,
            org_id=p.org_id,
            actor_user_id=p.user_id,
            actor_name=p.display_name,
            ip=p.ip,
            action="org.settings_updated",
            entity_type="organization",
            entity_id=org.id,
            diff=diff,
        )
    return _settings(org)


# ------------------------------------------------------------------------------- users


def _user(u: User) -> S.UserOut:
    return S.UserOut(
        id=u.id,
        display_name=u.display_name,
        email=u.email,
        role=u.role,
        department=u.department,
        aliases=u.aliases or [],
    )


@router.get("/users", response_model=S.Paginated[S.UserOut])
async def list_users(
    search: str | None = Query(default=None, max_length=100),
    page: Page = Depends(),
    p: Principal = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> S.Paginated[S.UserOut]:
    stmt = select(User).where(User.erased_at.is_(None)).order_by(User.display_name)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.email.ilike(like)))
    rows, nxt = await page.fetch(db, stmt)
    return S.Paginated[S.UserOut](items=[_user(u) for u in rows], next_cursor=nxt)


@router.post("/users/sync", response_model=S.SyncResult)
async def sync_users(
    p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> S.SyncResult:
    """Directory sync. Users are JIT-provisioned at first OIDC sign-in; a SCIM/Keycloak admin sync can
    plug in here. Today this refreshes nothing remotely and reports the current roster size."""
    count = len((await db.execute(select(User.id).where(User.erased_at.is_(None)))).all())
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="users.synced",
        entity_type="organization",
        entity_id=p.org_id,
        diff={"source": "oidc_jit", "added": 0, "updated": count},
    )
    return S.SyncResult(added=0, updated=count)


@router.patch("/users/{user_id}", response_model=S.UserOut)
async def patch_user(
    user_id: UUID,
    body: S.UserPatch,
    p: Principal = Depends(require_role(Role.org_admin, Role.scrum_lead)),
    db: AsyncSession = Depends(db_session),
) -> S.UserOut:
    u = await db.get(User, user_id)
    if u is None or u.erased_at is not None:
        raise not_found("User")
    diff: dict[str, object] = {}
    if body.role is not None and body.role != u.role:
        if p.role != Role.org_admin:
            raise forbidden("Only org admins can change roles.")
        if u.id == p.user_id:
            raise Problem(422, "Validation failed", "You can't change your own role.")
        diff["role"] = [u.role, body.role]
        u.role = body.role
    if body.aliases is not None and body.aliases != (u.aliases or []):
        diff["aliases"] = [u.aliases, body.aliases]
        u.aliases = body.aliases
    if diff:
        await write_audit(
            db,
            org_id=p.org_id,
            actor_user_id=p.user_id,
            actor_name=p.display_name,
            ip=p.ip,
            action="user.updated",
            entity_type="user",
            entity_id=u.id,
            diff=diff,
        )
    return _user(u)


@router.post("/users/{user_id}/erase", status_code=204, response_class=Response)
async def erase_user(
    user_id: UUID, p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> Response:
    """Right to erasure (plan §12): redact transcript text and speaker link, delete updates, keep an audit entry."""
    u = await db.get(User, user_id)
    if u is None or u.erased_at is not None:
        raise not_found("User")
    if u.id == p.user_id:
        raise invalid("user_id", "You can't erase your own account.")
    seg = await db.execute(
        update(TranscriptSegment)
        .where(TranscriptSegment.speaker_user_id == u.id)
        .values(text=REDACTED, speaker_user_id=None, speaker_label="Former member")
    )
    upd = await db.execute(delete(MemberUpdateRow).where(MemberUpdateRow.user_id == u.id))
    await db.execute(
        update(Blocker).where(Blocker.reporter_user_id == u.id).values(description=REDACTED, embedding=None)
    )
    await db.execute(delete(TeamMember).where(TeamMember.user_id == u.id))
    u.display_name, u.email, u.aliases, u.department = "Former member", f"erased-{u.id}@invalid", [], None
    u.idp_subject = f"erased:{u.id}"
    u.erased_at = datetime.now(UTC)
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="user.erased",
        entity_type="user",
        entity_id=user_id,
        diff={"transcripts": f"redacted {_rowcount(seg)}", "updates": f"deleted {_rowcount(upd)}"},
    )
    return Response(status_code=204)


@router.get("/users/{user_id}/export", response_model=S.UserExport)
async def export_user(
    user_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.UserExport:
    """Subject access request: everything Scrum Bot holds about one person (admin or the person)."""
    if p.role != Role.org_admin and p.user_id != user_id:
        raise forbidden("Only org admins or the person themselves can export this data.")
    u = await db.get(User, user_id)
    if u is None:
        raise not_found("User")
    teams = (
        (
            await db.execute(
                select(Team.name).join(TeamMember, TeamMember.team_id == Team.id).where(TeamMember.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    segs = (
        (
            await db.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.speaker_user_id == user_id)
                .order_by(TranscriptSegment.created_at)
            )
        )
        .scalars()
        .all()
    )
    updates = (await db.execute(select(MemberUpdateRow).where(MemberUpdateRow.user_id == user_id))).scalars().all()
    blockers = (await db.execute(select(Blocker).where(Blocker.reporter_user_id == user_id))).scalars().all()
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="user.exported",
        entity_type="user",
        entity_id=user_id,
        diff={},
    )
    return S.UserExport(
        user=_user(u),
        teams=list(teams),
        transcript_segments=[{"session_id": str(s.session_id), "start_ms": s.start_ms, "text": s.text} for s in segs],
        updates=[{"session_id": str(x.session_id), "source": x.source, **x.payload} for x in updates],
        blockers_reported=[
            {
                "id": str(b.id),
                "description": b.description,
                "status": b.status,
                "first_seen_at": b.first_seen_at.isoformat(),
            }
            for b in blockers
        ],
        exported_at=datetime.now(UTC),
    )
