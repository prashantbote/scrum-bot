"""Public signed-link endpoints (no user session): blocker actions and async check-ins (plan §10)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api import schemas as S
from scrum_api.errors import Problem
from scrum_api.routers.blockers import apply_status
from scrum_core import workflow_client
from scrum_core.audit import write_audit
from scrum_core.db import session_for, system_session
from scrum_core.models import (
    ActionTokenUse,
    AsyncCheckin,
    Attendance,
    Blocker,
    Organization,
    Question,
    QuestionTemplate,
    StandupSession,
    Team,
    TeamMember,
    User,
)
from scrum_core.models.base import AttendanceStatus, BlockerEventKind, BlockerStatus
from scrum_core.models.blocker import BlockerEvent
from scrum_core.security.tokens import ActionClaims, InvalidToken, blocker_token, checkin_token, verify
from scrum_core.settings import get_settings

router = APIRouter(tags=["public links"])

NOT_RECOGNISED = Problem(404, "Link not recognised", "This link is invalid. Check that you copied the full URL.")


def _claims(token: str) -> ActionClaims:
    try:
        return verify(token)
    except InvalidToken as exc:
        raise NOT_RECOGNISED from exc


async def _used(db: AsyncSession, token_id: str) -> set[str]:
    return set((await db.execute(select(ActionTokenUse.action).where(ActionTokenUse.token_id == token_id))).scalars())


async def _questions(db: AsyncSession, s: StandupSession) -> list[Question]:
    tpl_id = (
        s.template_id
        or (
            await db.execute(
                select(QuestionTemplate.id).where(
                    QuestionTemplate.team_id == s.team_id, QuestionTemplate.is_active.is_(True)
                )
            )
        ).scalar()
    )
    if tpl_id is None:
        return []
    return list(
        (await db.execute(select(Question).where(Question.template_id == tpl_id).order_by(Question.position))).scalars()
    )


@router.get("/actions/{token}", response_model=S.ActionPreview)
async def preview(token: str) -> S.ActionPreview:
    c = _claims(token)
    async with session_for(c.org_id) as db:
        if c.kind == "blocker":
            b = await db.get(Blocker, c.blocker_id)
            if b is None:
                raise NOT_RECOGNISED
            team = await db.get(Team, b.team_id)
            reporter = await db.get(User, b.reporter_user_id)
            used = await _used(db, c.token_id)
            done = b.status == BlockerStatus.resolved
            allowed: list[str] = (
                [] if done else (["resolve"] if b.status == BlockerStatus.acknowledged else ["acknowledge", "resolve"])
            )
            return S.ActionPreview(
                kind="blocker",
                expired=c.expired,
                already_done=done,
                allowed_actions=[a for a in allowed if a not in used],
                blocker=S.ActionBlocker(
                    description=b.description,
                    ticket_keys=b.ticket_keys or [],
                    reporter_name=reporter.display_name if reporter else "—",
                    team_name=team.name if team else "",
                    status=b.status,
                    days_open=b.days_open,
                ),
            )
        s = await db.get(StandupSession, c.session_id)
        member = await db.get(User, c.user_id)
        if s is None or member is None:
            raise NOT_RECOGNISED
        team = await db.get(Team, s.team_id)
        submitted = (
            await db.execute(
                select(AsyncCheckin.id).where(AsyncCheckin.session_id == s.id, AsyncCheckin.user_id == member.id)
            )
        ).first() is not None
        return S.ActionPreview(
            kind="checkin",
            expired=c.expired,
            already_done=submitted,
            allowed_actions=[],
            checkin=S.ActionCheckin(
                member_name=member.display_name,
                team_name=team.name if team else "",
                run_date=s.run_date,
                questions=[
                    S.ActionQuestion(id=q.id, text=q.text, required=q.required) for q in await _questions(db, s)
                ],
            ),
        )


@router.post("/actions/{token}", response_model=S.ActionResult)
async def perform(token: str, body: S.ActionIn) -> S.ActionResult:
    c = _claims(token)
    if c.kind != "blocker":
        raise NOT_RECOGNISED
    if c.expired:
        raise Problem(410, "Link expired", "This link has expired. Open the blocker in Scrum Bot instead.")
    async with session_for(c.org_id) as db:
        b = await db.get(Blocker, c.blocker_id)
        if b is None:
            raise NOT_RECOGNISED
        if b.status == BlockerStatus.resolved:
            return S.ActionResult(status="resolved")
        if body.action in await _used(db, c.token_id):
            return S.ActionResult(status=b.status.value)
        actor = (await db.execute(select(User).where(User.email == (c.recipient or "").lower()))).scalar_one_or_none()
        actor_name = actor.display_name if actor else (c.recipient or "Email recipient")
        target = BlockerStatus.resolved if body.action == "resolve" else BlockerStatus.acknowledged
        before = b.status
        now = datetime.now(UTC)
        kind = apply_status(b, target, now) or BlockerEventKind.acknowledged
        db.add(ActionTokenUse(org_id=c.org_id, token_id=c.token_id, action=body.action, actor_email=c.recipient or ""))
        db.add(
            BlockerEvent(
                org_id=c.org_id, blocker_id=b.id, at=now, kind=kind, actor_name=actor_name, note="From email link"
            )
        )
        await write_audit(
            db,
            org_id=c.org_id,
            actor_user_id=actor.id if actor else None,
            actor_name=actor_name,
            action=f"blocker.{target}",
            entity_type="blocker",
            entity_id=b.id,
            diff={"status": [before, target], "via": "email_link"},
        )
        try:
            await db.flush()
        except IntegrityError:  # double click raced us: single use per action
            raise Problem(409, "Already done", "This action was already taken from this link.") from None
        return S.ActionResult(status=target.value)


@router.post("/async-checkins/{token}", response_model=S.ActionResult)
async def submit_checkin(token: str, body: S.CheckinIn) -> S.ActionResult:
    c = _claims(token)
    if c.kind != "checkin":
        raise NOT_RECOGNISED
    if c.expired:
        raise Problem(410, "Check-in closed", "The async window for this standup has closed.")
    async with session_for(c.org_id) as db:
        s = await db.get(StandupSession, c.session_id)
        member = await db.get(User, c.user_id)
        if s is None or member is None:
            raise NOT_RECOGNISED
        if (
            await db.execute(
                select(AsyncCheckin.id).where(AsyncCheckin.session_id == s.id, AsyncCheckin.user_id == member.id)
            )
        ).first():
            raise Problem(409, "Already submitted", "You've already sent today's update.")
        questions = await _questions(db, s)
        answers = {k: v.strip() for k, v in body.answers.items() if isinstance(v, str)}
        missing = [q for q in questions if q.required and not answers.get(str(q.id))]
        if missing:
            raise Problem(
                422,
                "Validation failed",
                None,
                [{"field": str(q.id), "message": "This answer is required"} for q in missing],
            )
        known = {str(q.id) for q in questions}
        db.add(
            AsyncCheckin(
                org_id=c.org_id,
                session_id=s.id,
                user_id=member.id,
                answers={k: v[:2000] for k, v in answers.items() if k in known},
            )
        )
        att = (
            await db.execute(select(Attendance).where(Attendance.session_id == s.id, Attendance.user_id == member.id))
        ).scalar_one_or_none()
        if att is None:
            db.add(Attendance(org_id=c.org_id, session_id=s.id, user_id=member.id, status=AttendanceStatus.async_))
        elif att.status == AttendanceStatus.absent:
            att.status = AttendanceStatus.async_
        await write_audit(
            db,
            org_id=c.org_id,
            actor_user_id=member.id,
            actor_name=member.display_name,
            action="checkin.submitted",
            entity_type="standup_session",
            entity_id=s.id,
            diff={"source": "web_form", "answers": len(answers)},
        )
        workflow_id, member_id = s.workflow_id, member.id
    if workflow_id and get_settings().temporal_enabled:
        await workflow_client.signal_async_checkin(workflow_id, member_id)  # wakes the workflow; DB is the truth
    return S.ActionResult(status="submitted")


# ------------------------------------------------------------------------------- dev helpers


@router.get("/dev/demo-links", response_model=list[S.DemoLink], include_in_schema=False)
async def demo_links() -> list[S.DemoLink]:
    """Fresh signed links into the seeded story (dev auth mode only) — used by the frontend sign-in page."""
    if get_settings().auth_mode != "dev":
        raise Problem(404, "Not found")
    async with system_session() as sys:
        org_id = (await sys.execute(select(Organization.id).order_by(Organization.created_at))).scalars().first()
    if org_id is None:
        return []
    out: list[S.DemoLink] = []
    async with session_for(org_id) as db:

        async def first(status: BlockerStatus) -> tuple[Blocker, User] | None:
            row = (
                await db.execute(
                    select(Blocker, User)
                    .join(User, User.id == Blocker.blocked_on_user_id)
                    .where(Blocker.status == status)
                    .order_by(Blocker.days_open.desc(), Blocker.first_seen_at.desc())
                )
            ).first()
            return (row[0], row[1]) if row else None

        if hit := await first(BlockerStatus.open):
            b, u = hit
            out.append(
                S.DemoLink(
                    label=f"Blocker alert link ({u.display_name.split()[0]} → {b.description[:40]})",
                    href=f"/a/{blocker_token(org_id=org_id, blocker_id=b.id, recipient=u.email)}",
                )
            )
        if hit := await first(BlockerStatus.resolved):
            b, u = hit
            out.append(
                S.DemoLink(
                    label="Already-resolved link",
                    href=f"/a/{blocker_token(org_id=org_id, blocker_id=b.id, recipient=u.email)}",
                )
            )
        if hit := await first(BlockerStatus.acknowledged) or await first(BlockerStatus.open):
            b, u = hit
            tok = blocker_token(org_id=org_id, blocker_id=b.id, recipient=u.email, ttl_seconds=-60)
            out.append(S.DemoLink(label="Expired link", href=f"/a/{tok}"))
        row = (
            await db.execute(
                select(StandupSession, TeamMember.user_id, User.display_name)
                .join(TeamMember, TeamMember.team_id == StandupSession.team_id)
                .join(User, User.id == TeamMember.user_id)
                .where(
                    ~select(AsyncCheckin.id)
                    .where(AsyncCheckin.session_id == StandupSession.id, AsyncCheckin.user_id == TeamMember.user_id)
                    .exists()
                )
                .order_by(StandupSession.run_date.desc(), TeamMember.speaking_order.desc())
            )
        ).first()
        if row:
            s, uid, name = row
            tok = checkin_token(org_id=org_id, session_id=s.id, user_id=uid, expires_at=int(time.time()) + 86_400)
            out.append(S.DemoLink(label=f"Async check-in ({name.split()[0]})", href=f"/a/{tok}?type=checkin"))
    return out
