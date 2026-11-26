"""Teams, members, versioned question templates and schedules (Temporal Schedules + recurring meeting)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_adapters import registry
from scrum_adapters.calendar import MeetingRef, ScheduleConfig, TeamConfig
from scrum_api import projections as P
from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session, require_role
from scrum_api.errors import Problem, invalid, not_found
from scrum_api.rbac import require_configure, team_or_404, visible_team_ids
from scrum_core import workflow_client
from scrum_core.audit import write_audit
from scrum_core.models import Question, QuestionTemplate, Schedule, StandupSession, Team, TeamMember, User
from scrum_core.models.base import MeetingProviderKind, Role, SessionStatus
from scrum_core.schedule import ScheduleError, shift_cron_earlier, today_in, validate_cron, validate_timezone
from scrum_core.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["teams"])
LEADS = (Role.org_admin, Role.scrum_lead)


async def _audit(
    db: AsyncSession, p: Principal, action: str, entity_type: str, entity_id: object, diff: dict[str, Any]
) -> None:
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        diff=diff,
    )


# ------------------------------------------------------------------------------- teams


@router.get("/teams", response_model=S.Paginated[S.TeamOut])
async def list_teams(
    p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.Paginated[S.TeamOut]:
    ids = await visible_team_ids(p, db)
    teams = (await db.execute(select(Team).where(Team.id.in_(ids)).order_by(Team.name))).scalars().all()
    return S.Paginated[S.TeamOut](items=await P.teams_out(db, teams), next_cursor=None)


@router.post("/teams", response_model=S.TeamOut, status_code=201)
async def create_team(
    body: S.TeamCreate, p: Principal = Depends(require_role(*LEADS)), db: AsyncSession = Depends(db_session)
) -> S.TeamOut:
    name = body.name.strip()
    if (await db.execute(select(Team.id).where(func.lower(Team.name) == name.lower()))).first():
        raise invalid("name", "A team with this name already exists")
    try:
        validate_timezone(body.timezone)
    except ScheduleError as exc:
        raise invalid("timezone", str(exc)) from exc
    lead_id = body.lead_user_id or p.user_id
    if p.role == Role.scrum_lead and lead_id != p.user_id:
        raise invalid("lead_user_id", "Scrum leads can only create teams they lead")
    if await db.get(User, lead_id) is None:
        raise invalid("lead_user_id", "Unknown user")
    s = get_settings()
    team = Team(
        org_id=p.org_id,
        name=name,
        lead_user_id=lead_id,
        timezone=body.timezone,
        meeting_provider=MeetingProviderKind.livekit if s.meeting_provider == "livekit" else MeetingProviderKind.fake,
        active=True,
    )
    db.add(team)
    await db.flush()
    await _audit(db, p, "team.created", "team", team.id, {"name": name, "timezone": body.timezone})
    return (await P.teams_out(db, [team]))[0]


@router.get("/teams/{team_id}", response_model=S.TeamOut)
async def get_team(
    team_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.TeamOut:
    return (await P.teams_out(db, [await team_or_404(p, db, team_id)]))[0]


@router.patch("/teams/{team_id}", response_model=S.TeamOut)
async def patch_team(
    team_id: UUID,
    body: S.TeamPatch,
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> S.TeamOut:
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    diff: dict[str, list[object]] = {}
    data = body.model_dump(exclude_unset=True)
    if data.get("timezone"):
        try:
            validate_timezone(data["timezone"])
        except ScheduleError as exc:
            raise invalid("timezone", str(exc)) from exc
    if data.get("name"):
        data["name"] = data["name"].strip()
        clash = await db.execute(
            select(Team.id).where(func.lower(Team.name) == data["name"].lower(), Team.id != team.id)
        )
        if clash.first():
            raise invalid("name", "A team with this name already exists")
    for k, v in data.items():
        if v is not None and getattr(team, k) != v:
            diff[k] = [getattr(team, k), v]
            setattr(team, k, v)
    if diff:
        await _audit(db, p, "team.updated", "team", team.id, diff)
        if "active" in diff and get_settings().temporal_enabled:
            await _sync_pause(team.id, not team.active)
    return (await P.teams_out(db, [team]))[0]


@router.delete("/teams/{team_id}", status_code=204, response_class=Response)
async def delete_team(
    team_id: UUID, p: Principal = Depends(require_role(Role.org_admin)), db: AsyncSession = Depends(db_session)
) -> Response:
    team = await team_or_404(p, db, team_id)
    has_history = (
        await db.execute(select(StandupSession.id).where(StandupSession.team_id == team.id).limit(1))
    ).first()
    if has_history:
        # Keep history for reports and audit; deactivate instead of deleting.
        team.active = False
        await _audit(db, p, "team.deactivated", "team", team.id, {"reason": "has standup history"})
    else:
        await db.delete(team)
        await _audit(db, p, "team.deleted", "team", team_id, {"name": team.name})
    if get_settings().temporal_enabled:
        try:
            await workflow_client.delete_schedule(team_id)
        except Exception:  # Temporal down: the schedule's run will find the team inactive and skip.
            log.warning("could not delete Temporal schedule for %s", team_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------------- members


@router.get("/teams/{team_id}/members", response_model=list[S.TeamMemberOut])
async def get_members(
    team_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.TeamMemberOut]:
    await team_or_404(p, db, team_id)
    return await P.members_out(db, team_id)


@router.put("/teams/{team_id}/members", response_model=list[S.TeamMemberOut])
async def put_members(
    team_id: UUID,
    body: list[S.TeamMemberIn],
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> list[S.TeamMemberOut]:
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    ids = [m.user_id for m in body]
    if len(set(ids)) != len(ids):
        raise invalid("members", "A person can only be listed once")
    known = set((await db.execute(select(User.id).where(User.id.in_(ids), User.erased_at.is_(None)))).scalars())
    if missing := [str(i) for i in ids if i not in known]:
        raise invalid("members", f"Unknown users: {', '.join(missing)}")
    before = (await db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))).scalars().all()
    await db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    for i, m in enumerate(body):
        db.add(
            TeamMember(
                org_id=p.org_id,
                team_id=team.id,
                user_id=m.user_id,
                speaking_order=i + 1,
                pm_account_id=(m.pm_account_id or None),
            )
        )
    await db.flush()
    await _audit(
        db,
        p,
        "team.members_updated",
        "team",
        team.id,
        {
            "members": [len(before), len(body)],
            "added": [str(x) for x in set(ids) - set(before)],
            "removed": [str(x) for x in set(before) - set(ids)],
        },
    )
    return await P.members_out(db, team.id)


# ------------------------------------------------------------------------------- templates


@router.get("/teams/{team_id}/templates", response_model=list[S.TemplateOut])
async def list_templates(
    team_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.TemplateOut]:
    await team_or_404(p, db, team_id)
    rows = (
        (
            await db.execute(
                select(QuestionTemplate)
                .where(QuestionTemplate.team_id == team_id)
                .order_by(QuestionTemplate.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return await P.templates_out(db, rows)


@router.post("/teams/{team_id}/templates", response_model=S.TemplateOut, status_code=201)
async def create_template(
    team_id: UUID,
    body: S.TemplateIn,
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> S.TemplateOut:
    """Templates are immutable: saving always creates and activates a new version (plan §4.1)."""
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    current = (
        await db.execute(select(func.max(QuestionTemplate.version)).where(QuestionTemplate.team_id == team.id))
    ).scalar() or 0
    await db.execute(update(QuestionTemplate).where(QuestionTemplate.team_id == team.id).values(is_active=False))
    tpl = QuestionTemplate(org_id=p.org_id, team_id=team.id, version=current + 1, is_active=True, created_by=p.user_id)
    tpl.questions = [
        Question(
            org_id=p.org_id,
            position=i + 1,
            text=q.text.strip(),
            type=q.type,
            required=q.required,
            followup_policy=q.followup_policy,
            max_followups=q.max_followups if q.followup_policy != "none" else 0,
        )
        for i, q in enumerate(body.questions)
    ]
    db.add(tpl)
    await db.flush()
    await _audit(
        db,
        p,
        "template.created",
        "question_template",
        tpl.id,
        {"version": tpl.version, "questions": len(tpl.questions)},
    )
    await db.refresh(tpl, ["questions", "created_at"])
    return (await P.templates_out(db, [tpl]))[0]


@router.post("/templates/{template_id}/activate", response_model=S.TemplateOut)
async def activate_template(
    template_id: UUID, p: Principal = Depends(require_role(*LEADS)), db: AsyncSession = Depends(db_session)
) -> S.TemplateOut:
    tpl = await db.get(QuestionTemplate, template_id)
    if tpl is None or tpl.team_id not in await visible_team_ids(p, db):
        raise not_found("Template")
    require_configure(p, tpl.team_id)
    await db.execute(
        update(QuestionTemplate)
        .where(QuestionTemplate.team_id == tpl.team_id)
        .values(is_active=QuestionTemplate.id == tpl.id)
    )
    await db.refresh(tpl)
    await _audit(db, p, "template.activated", "question_template", tpl.id, {"version": tpl.version})
    return (await P.templates_out(db, [tpl]))[0]


# ------------------------------------------------------------------------------- schedule


async def _sync_pause(team_id: UUID, paused: bool) -> None:
    try:
        await workflow_client.set_paused(team_id, paused)
    except Exception as exc:
        log.warning("could not (un)pause schedule %s: %s", team_id, exc)


async def _team_config(db: AsyncSession, team: Team) -> TeamConfig:
    emails = (
        (
            await db.execute(
                select(User.email).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team.id)
            )
        )
        .scalars()
        .all()
    )
    lead = await db.get(User, team.lead_user_id)
    return TeamConfig(
        team_id=str(team.id),
        team_name=team.name,
        attendee_emails=[*emails, *([lead.email] if lead else [])],
        organizer_email=lead.email if lead else "standup-bot@scrumbot.local",
    )


@router.get("/teams/{team_id}/schedule", response_model=S.ScheduleOut)
async def get_schedule(
    team_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.ScheduleOut:
    await team_or_404(p, db, team_id)
    sched = (await db.execute(select(Schedule).where(Schedule.team_id == team_id))).scalar_one_or_none()
    if sched is None:
        raise Problem(404, "No schedule yet")
    return P.schedule_out(sched)


@router.put("/teams/{team_id}/schedule", response_model=S.ScheduleOut)
async def put_schedule(
    team_id: UUID,
    body: S.ScheduleIn,
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> S.ScheduleOut:
    """Saves the schedule, creates/updates the recurring meeting and upserts the Temporal Schedule.

    Order matters for the compensating step (plan §7.1): DB row first (inside the request transaction),
    then the external calls; if Temporal fails we raise, the transaction rolls back and the meeting
    invite is harmless to resend on the next save.
    """
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    try:
        cron = validate_cron(body.cron)
        shift_cron_earlier(cron, body.lead_minutes)
    except ScheduleError as exc:
        raise invalid("cron", str(exc)) from exc
    try:
        validate_timezone(body.timezone)
    except ScheduleError as exc:
        raise invalid("timezone", str(exc)) from exc

    sched = (await db.execute(select(Schedule).where(Schedule.team_id == team.id))).scalar_one_or_none()
    created = sched is None
    before = {} if created else {"cron": sched.cron, "timezone": sched.timezone}  # type: ignore[union-attr]
    if sched is None:
        sched = Schedule(org_id=p.org_id, team_id=team.id, cron=cron, timezone=body.timezone)
        db.add(sched)
    sched.cron, sched.timezone = cron, body.timezone
    sched.holiday_calendar = body.holiday_calendar or None
    sched.skip_dates = sorted(set(body.skip_dates))
    sched.async_window_minutes, sched.lead_minutes, sched.paused = (
        body.async_window_minutes,
        body.lead_minutes,
        body.paused,
    )

    cal = registry.calendar()
    team_cfg = await _team_config(db, team)
    sched_cfg = ScheduleConfig(cron=cron, timezone=body.timezone)
    try:
        if not sched.recurring_meeting_id:
            ref = await cal.create_recurring_meeting(team_cfg, sched_cfg)
            sched.recurring_meeting_id, sched.join_url = ref.id, ref.join_url
        elif before.get("cron") != cron or before.get("timezone") != body.timezone:
            await cal.update_recurring_meeting(
                MeetingRef(sched.recurring_meeting_id, sched.join_url or ""), team_cfg, sched_cfg
            )
    except Exception as exc:  # mail relay down etc. — the room URL is still valid; invite can be resent.
        log.warning("calendar invite failed for team %s: %s", team.id, exc)
        if not sched.join_url:
            room = f"standup-{team.id}"
            sched.recurring_meeting_id = room
            sched.join_url = get_settings().meeting_join_url_template.format(room=room)

    if get_settings().temporal_enabled:
        try:
            sched.temporal_schedule_id = await workflow_client.upsert_schedule(
                org_id=p.org_id,
                team_id=team.id,
                cron=cron,
                tz=body.timezone,
                lead_minutes=body.lead_minutes,
                paused=body.paused or not team.active,
            )
        except Exception as exc:
            raise Problem(503, "Scheduler unavailable", f"Could not save the schedule in Temporal: {exc}") from exc
    await db.flush()
    await _audit(
        db,
        p,
        "schedule.created" if created else "schedule.updated",
        "schedule",
        team.id,
        {
            "cron": [before.get("cron"), cron],
            "timezone": [before.get("timezone"), body.timezone],
            **({"recurring_meeting": "created"} if created else {}),
        },
    )
    return P.schedule_out(sched)


@router.post("/teams/{team_id}/schedule/trigger-now", response_model=S.TriggerOut, status_code=202)
async def trigger_now(
    team_id: UUID, p: Principal = Depends(require_role(*LEADS)), db: AsyncSession = Depends(db_session)
) -> S.TriggerOut:
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    if not get_settings().temporal_enabled:
        raise Problem(503, "Scheduler unavailable", "Temporal is disabled (SCRUM_TEMPORAL_ENABLED=false).")
    today = today_in(team.timezone)
    ran = (
        await db.execute(
            select(StandupSession.status).where(StandupSession.team_id == team.id, StandupSession.run_date == today)
        )
    ).scalar()
    if ran in (SessionStatus.running, SessionStatus.extracting, SessionStatus.delivered):
        raise Problem(409, "Already ran today", f"Today's standup is {ran.value}. It runs once per team per day.")
    try:
        wid = await workflow_client.trigger_now(org_id=p.org_id, team_id=team.id, tz=team.timezone)
    except Exception as exc:
        if "already started" in str(exc).lower():
            raise Problem(409, "Already starting", "A run for this team was just started.") from exc
        raise Problem(503, "Scheduler unavailable", str(exc)) from exc
    await _audit(db, p, "schedule.triggered", "schedule", team.id, {"workflow_id": wid})
    return S.TriggerOut(workflow_id=wid)


@router.post("/teams/{team_id}/schedule/pause", response_model=S.ScheduleOut)
async def pause_schedule(
    team_id: UUID, body: S.PauseIn, p: Principal = Depends(require_role(*LEADS)), db: AsyncSession = Depends(db_session)
) -> S.ScheduleOut:
    team = await team_or_404(p, db, team_id)
    require_configure(p, team.id)
    sched = (await db.execute(select(Schedule).where(Schedule.team_id == team.id))).scalar_one_or_none()
    if sched is None:
        raise Problem(404, "No schedule yet")
    sched.paused = body.paused
    if get_settings().temporal_enabled:
        await _sync_pause(team.id, body.paused)
    await _audit(db, p, "schedule.paused" if body.paused else "schedule.resumed", "schedule", team.id, {})
    return P.schedule_out(sched)
