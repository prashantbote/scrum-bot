"""Row → DTO projections (batch-loaded to avoid N+1 queries)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api import schemas as S
from scrum_core.models import (
    Attendance,
    Blocker,
    BlockerEvent,
    BlockerEvidence,
    MemberUpdateRow,
    QuestionTemplate,
    ReviewItem,
    Schedule,
    StandupSession,
    Team,
    TeamMember,
    TranscriptSegment,
    User,
)
from scrum_core.models.base import AttendanceStatus
from scrum_core.schedule import next_runs


async def user_names(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {r[0]: r[1] for r in rows}


async def team_names(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {r[0]: r[1] for r in await db.execute(select(Team.id, Team.name).where(Team.id.in_(wanted)))}


# ------------------------------------------------------------------------------- teams


async def teams_out(db: AsyncSession, teams: Sequence[Team]) -> list[S.TeamOut]:
    ids = [t.id for t in teams]
    if not ids:
        return []
    leads = await user_names(db, [t.lead_user_id for t in teams])
    counts = dict(
        (
            await db.execute(
                select(TeamMember.team_id, func.count()).where(TeamMember.team_id.in_(ids)).group_by(TeamMember.team_id)
            )
        ).all()
    )
    versions = dict(
        (
            await db.execute(
                select(QuestionTemplate.team_id, QuestionTemplate.version).where(
                    QuestionTemplate.team_id.in_(ids), QuestionTemplate.is_active.is_(True)
                )
            )
        ).all()
    )
    scheds = {s.team_id: s for s in (await db.execute(select(Schedule).where(Schedule.team_id.in_(ids)))).scalars()}
    out = []
    for t in teams:
        sched = scheds.get(t.id)
        nxt = None
        if sched and not sched.paused and t.active:
            runs = next_runs(
                sched.cron, sched.timezone, 1, skip_dates=sched.skip_dates, holiday_calendar=sched.holiday_calendar
            )
            nxt = runs[0] if runs else None
        out.append(
            S.TeamOut(
                id=t.id,
                name=t.name,
                lead_user_id=t.lead_user_id,
                lead_name=leads.get(t.lead_user_id, "—"),
                timezone=t.timezone,
                member_count=int(counts.get(t.id, 0)),
                meeting_provider=t.meeting_provider,
                active=t.active,
                next_run_at=nxt,
                active_template_version=versions.get(t.id),
            )
        )
    return out


async def members_out(db: AsyncSession, team_id: UUID) -> list[S.TeamMemberOut]:
    rows = await db.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.speaking_order, User.display_name)
    )
    return [
        S.TeamMemberOut(
            user_id=u.id,
            display_name=u.display_name,
            email=u.email,
            department=u.department,
            speaking_order=m.speaking_order,
            pm_account_id=m.pm_account_id,
            aliases=u.aliases or [],
        )
        for m, u in rows
    ]


async def templates_out(db: AsyncSession, templates: Sequence[QuestionTemplate]) -> list[S.TemplateOut]:
    names = await user_names(db, [t.created_by for t in templates])
    return [
        S.TemplateOut(
            id=t.id,
            team_id=t.team_id,
            version=t.version,
            is_active=t.is_active,
            created_by_name=names.get(t.created_by, "Scrum Bot") if t.created_by else "Scrum Bot",
            created_at=t.created_at,
            questions=[
                S.QuestionOut(
                    id=q.id,
                    position=q.position,
                    text=q.text,
                    type=q.type,
                    required=q.required,
                    followup_policy=q.followup_policy,
                    max_followups=q.max_followups,
                )
                for q in t.questions
            ],
        )
        for t in templates
    ]


def schedule_out(s: Schedule) -> S.ScheduleOut:
    return S.ScheduleOut(
        team_id=s.team_id,
        cron=s.cron,
        timezone=s.timezone,
        holiday_calendar=s.holiday_calendar,
        skip_dates=sorted(s.skip_dates or []),
        async_window_minutes=s.async_window_minutes,
        lead_minutes=s.lead_minutes,
        paused=s.paused,
        join_url=s.join_url,
    )


# ------------------------------------------------------------------------------- sessions


async def sessions_out(db: AsyncSession, sessions: Sequence[StandupSession]) -> list[S.SessionOut]:
    ids = [s.id for s in sessions]
    if not ids:
        return []
    names = await team_names(db, [s.team_id for s in sessions])
    att: dict[UUID, tuple[int, int]] = {}
    for sid, status, n in await db.execute(
        select(Attendance.session_id, Attendance.status, func.count())
        .where(Attendance.session_id.in_(ids))
        .group_by(Attendance.session_id, Attendance.status)
    ):
        ok, total = att.get(sid, (0, 0))
        att[sid] = (ok + (n if status != AttendanceStatus.absent else 0), total + n)
    blockers: dict[UUID, int] = {}
    for sid, payload in await db.execute(
        select(MemberUpdateRow.session_id, MemberUpdateRow.payload).where(MemberUpdateRow.session_id.in_(ids))
    ):
        blockers[sid] = blockers.get(sid, 0) + len(payload.get("blockers", []))
    versions = dict(
        (
            await db.execute(
                select(QuestionTemplate.id, QuestionTemplate.version).where(
                    QuestionTemplate.id.in_({s.template_id for s in sessions if s.template_id})
                )
            )
        ).all()
    )
    out = []
    for s in sessions:
        ok, total = att.get(s.id, (0, 0))
        duration = int((s.ended_at - s.started_at).total_seconds()) if s.started_at and s.ended_at else None
        out.append(
            S.SessionOut(
                id=s.id,
                team_id=s.team_id,
                team_name=names.get(s.team_id, ""),
                run_date=s.run_date,
                status=s.status,
                attendance_pct=(ok / total) if total else 0.0,
                blocker_count=blockers.get(s.id, 0),
                duration_seconds=duration,
                template_version=versions.get(s.template_id, 0) if s.template_id else 0,
                started_at=s.started_at,
                ended_at=s.ended_at,
            )
        )
    return out


def summary_of(s: S.SessionOut) -> S.SessionSummary:
    return S.SessionSummary(**s.model_dump(include=set(S.SessionSummary.model_fields)))


# ------------------------------------------------------------------------------- blockers


async def blockers_out(db: AsyncSession, rows: Sequence[Blocker]) -> list[S.BlockerOut]:
    people = await user_names(db, [b.reporter_user_id for b in rows] + [b.blocked_on_user_id for b in rows])
    teams = await team_names(db, [b.team_id for b in rows])
    return [
        S.BlockerOut(
            id=b.id,
            team_id=b.team_id,
            team_name=teams.get(b.team_id, ""),
            description=b.description,
            reporter_user_id=b.reporter_user_id,
            reporter_name=people.get(b.reporter_user_id, "—"),
            blocked_on_user_id=b.blocked_on_user_id,
            blocked_on_name=people.get(b.blocked_on_user_id) if b.blocked_on_user_id else None,
            blocked_on_raw=b.blocked_on_raw,
            ticket_keys=b.ticket_keys or [],
            severity=b.severity,
            status=b.status,
            days_open=b.days_open,
            escalated=b.escalated,
            first_seen_at=b.first_seen_at,
            resolved_at=b.resolved_at,
        )
        for b in rows
    ]


async def blocker_detail(db: AsyncSession, b: Blocker) -> S.BlockerDetailOut:
    base = (await blockers_out(db, [b]))[0]
    events = (
        (
            await db.execute(
                select(BlockerEvent)
                .where(BlockerEvent.blocker_id == b.id)
                .order_by(BlockerEvent.at, BlockerEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    ev_rows = (
        (
            await db.execute(
                select(TranscriptSegment)
                .join(BlockerEvidence, BlockerEvidence.segment_id == TranscriptSegment.id)
                .where(BlockerEvidence.blocker_id == b.id)
                .order_by(TranscriptSegment.created_at, TranscriptSegment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    return S.BlockerDetailOut(
        **base.model_dump(),
        events=[
            S.BlockerEventOut(at=e.at, kind=e.kind, actor_name=e.actor_name, note=e.note, session_id=e.session_id)
            for e in events
        ],
        evidence=[
            S.BlockerEvidenceOut(
                segment_id=t.id,
                session_id=t.session_id,
                speaker_label=t.speaker_label,
                text=t.text,
                start_ms=t.start_ms,
            )
            for t in ev_rows
        ],
    )


# ------------------------------------------------------------------------------- review


async def review_out(db: AsyncSession, rows: Sequence[ReviewItem]) -> list[S.ReviewItemOut]:
    teams = await team_names(db, [r.team_id for r in rows])
    return [
        S.ReviewItemOut(
            id=r.id,
            kind=r.kind,
            status=r.status,
            team_name=teams.get(r.team_id, "") if r.team_id else "",
            raw_phrase=r.payload.get("raw_phrase", ""),
            evidence_quote=r.payload.get("evidence_quote", ""),
            evidence_speaker=r.payload.get("evidence_speaker", ""),
            session_id=r.session_id,
            candidates=[S.ReviewCandidate(**c) for c in r.payload.get("candidates", [])],
            created_at=r.created_at,
        )
        for r in rows
    ]
