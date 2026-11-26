"""Default-queue activities: context loading and session bookkeeping (plan §7.3)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from temporalio import activity

from scrum_adapters import registry
from scrum_core.audit import SYSTEM_ACTOR, write_audit
from scrum_core.db import session_for
from scrum_core.models import (
    Blocker,
    Organization,
    QuestionTemplate,
    Schedule,
    StandupSession,
    Team,
    TeamMember,
    User,
)
from scrum_core.models.base import BlockerStatus, SessionStatus
from scrum_core.schedule import skip_reason, today_in
from scrum_core.schemas.workflow import (
    MemberCtx,
    QuestionCtx,
    StaleBlocker,
    StandupContext,
    StandupInput,
    TicketRef,
)

log = logging.getLogger(__name__)
TECH_TERMS = [
    "API",
    "PR",
    "staging",
    "sandbox",
    "deploy",
    "migration",
    "Kafka",
    "Postgres",
    "webhook",
    "refund",
    "UPI",
    "Jira",
    "QA",
    "DevOps",
    "backend",
    "frontend",
]


@activity.defn(name="load_context")
async def load_context(inp: StandupInput) -> StandupContext:
    """Roster, active template, schedule/holidays, PM open items and STT vocabulary; upserts the session row."""
    async with session_for(inp.org_id) as db:
        org = await db.get(Organization, inp.org_id)
        team = await db.get(Team, inp.team_id)
        if org is None or team is None:
            raise ValueError(f"team {inp.team_id} not found in org {inp.org_id}")
        run_date = inp.run_date or today_in(team.timezone)
        sched = (await db.execute(select(Schedule).where(Schedule.team_id == team.id))).scalar_one_or_none()
        tpl = (
            await db.execute(
                select(QuestionTemplate).where(
                    QuestionTemplate.team_id == team.id, QuestionTemplate.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        lead = await db.get(User, team.lead_user_id)
        rows = (
            await db.execute(
                select(TeamMember, User)
                .join(User, User.id == TeamMember.user_id)
                .where(TeamMember.team_id == team.id, User.erased_at.is_(None))
                .order_by(TeamMember.speaking_order)
            )
        ).all()

        reason: str | None = None
        if not team.active:
            reason = "Team is inactive"
        elif sched and not inp.manual:
            reason = skip_reason(run_date, sched.skip_dates or [], sched.holiday_calendar)
        if not rows:
            reason = reason or "Team has no members"
        if tpl is None:
            reason = reason or "Team has no active question template"

        existing = (
            await db.execute(
                select(StandupSession).where(StandupSession.team_id == team.id, StandupSession.run_date == run_date)
            )
        ).scalar_one_or_none()
        if existing and existing.status in (SessionStatus.delivered, SessionStatus.running, SessionStatus.extracting):
            reason = reason or f"Standup already {existing.status.value} for {run_date}"
            session_id = existing.id
        else:
            stmt = (
                insert(StandupSession)
                .values(
                    org_id=inp.org_id,
                    team_id=team.id,
                    run_date=run_date,
                    template_id=tpl.id if tpl else None,
                    status=SessionStatus.scheduled,
                    workflow_id=activity.info().workflow_id,
                )
                .on_conflict_do_update(
                    index_elements=["team_id", "run_date"],
                    set_={
                        "status": SessionStatus.scheduled,
                        "workflow_id": activity.info().workflow_id,
                        "template_id": tpl.id if tpl else None,
                        "error": None,
                        "updated_at": datetime.now(UTC),
                    },
                )
                .returning(StandupSession.id)
            )
            session_id = (await db.execute(stmt)).scalar_one()

        # Acknowledged blockers not mentioned in the last 2 sessions → soft "is it resolved?" prompt.
        recent = (
            (
                await db.execute(
                    select(StandupSession.id)
                    .where(StandupSession.team_id == team.id, StandupSession.run_date < run_date)
                    .order_by(StandupSession.run_date.desc())
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        stale = (
            (
                await db.execute(
                    select(Blocker).where(
                        Blocker.team_id == team.id,
                        Blocker.status == BlockerStatus.acknowledged,
                        Blocker.last_seen_session_id.not_in(recent) if recent else Blocker.id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
            if len(recent) == 2
            else []
        )

        pm = await registry.pm_for_org(db, inp.org_id)
        accounts = [m.pm_account_id for m, _ in rows if m.pm_account_id]
        open_items: dict[str, list[Any]] = {}
        if pm and accounts:
            try:
                open_items = await pm.open_items_for(accounts)
            except Exception as exc:  # PM outage must not cancel the standup
                log.warning("PM preload failed: %s", exc)

        members = []
        vocab: list[str] = []
        for m, u in rows:
            tickets = [
                TicketRef(key=t.key, summary=t.summary, status=t.status)
                for t in open_items.get(m.pm_account_id or "", [])
            ][:5]
            members.append(
                MemberCtx(
                    user_id=u.id,
                    display_name=u.display_name,
                    first_name=u.display_name.split()[0],
                    email=u.email,
                    aliases=u.aliases or [],
                    department=u.department,
                    pm_account_id=m.pm_account_id,
                    open_tickets=tickets,
                    stale_blockers=[
                        StaleBlocker(id=b.id, description=b.description) for b in stale if b.reporter_user_id == u.id
                    ][:1],
                )
            )
            vocab += [u.display_name, *(u.aliases or []), *(t.key for t in tickets)]
        prefixes = sorted(
            {k.split("-")[0] for k in (team.pm_project_keys or [])}
            | {t.key.split("-")[0] for m in members for t in m.open_tickets}
        )
        questions = [
            QuestionCtx(
                id=q.id,
                position=q.position,
                text=q.text,
                type=q.type.value,
                required=q.required,
                followup_policy=q.followup_policy.value,
                max_followups=q.max_followups,
            )
            for q in (tpl.questions if tpl else [])
        ]
        return StandupContext(
            org_id=inp.org_id,
            team_id=team.id,
            team_name=team.name,
            timezone=team.timezone,
            run_date=run_date,
            session_id=session_id,
            skip_today=reason is not None,
            skip_reason=reason,
            lead_user_id=team.lead_user_id,
            lead_email=lead.email if lead else "",
            lead_name=lead.display_name if lead else "",
            members=members,
            template_id=tpl.id if tpl else None,
            questions=questions,
            consent_text=org.consent_text,
            async_window_minutes=sched.async_window_minutes if sched else 120,
            join_url=sched.join_url if sched else None,
            vocabulary=list(dict.fromkeys([*vocab, *prefixes, team.name, *TECH_TERMS])),
            escalation_days=org.escalation_days,
            pm_writeback_enabled=bool((org.settings or {}).get("pm_writeback_enabled")),
        )


@activity.defn(name="mark_session")
async def mark_session(args: dict[str, Any]) -> None:
    """Session status bookkeeping: {org_id, session_id, status, error?, reason?, already?}."""
    org_id, session_id = UUID(args["org_id"]), UUID(args["session_id"])
    status = SessionStatus(args["status"])
    async with session_for(org_id) as db:
        s = await db.get(StandupSession, session_id)
        if s is None:
            return
        if args.get("already"):  # skip because it already ran: leave the existing row untouched
            return
        s.status = status
        if status == SessionStatus.failed:
            s.error = str(args.get("error", ""))[:2000]
        if status == SessionStatus.skipped:
            s.error = args.get("reason")
        if status in (SessionStatus.skipped, SessionStatus.failed):
            await write_audit(
                db,
                org_id=org_id,
                actor_name=SYSTEM_ACTOR,
                action=f"standup.{status.value}",
                entity_type="standup_session",
                entity_id=session_id,
                diff={k: args[k] for k in ("reason", "error") if args.get(k)},
            )


@activity.defn(name="pending_async_users")
async def pending_async_users(args: dict[str, Any]) -> list[str]:
    """Absentees who still haven't submitted a check-in (the DB is the source of truth; signals only wake us)."""
    from scrum_core.models import AsyncCheckin

    org_id, session_id = UUID(args["org_id"]), UUID(args["session_id"])
    wanted = {str(x) for x in args["user_ids"]}
    async with session_for(org_id) as db:
        done = {
            str(x)
            for x in (
                await db.execute(select(AsyncCheckin.user_id).where(AsyncCheckin.session_id == session_id))
            ).scalars()
        }
    return sorted(wanted - done)


@activity.defn(name="retention_sweep")
async def retention_sweep() -> dict[str, int]:
    """Nightly (plan §12): drop transcripts and raw audio past each org's retention; summaries stay."""
    from datetime import timedelta

    from sqlalchemy import delete, update

    from scrum_adapters.blob import key_from_uri
    from scrum_core.db import system_session
    from scrum_core.models import TranscriptSegment

    totals = {"orgs": 0, "segments": 0, "recordings": 0}
    async with system_session() as sys_db:
        orgs = (
            await sys_db.execute(
                select(Organization.id, Organization.retention_days_transcript, Organization.retention_days_audio)
            )
        ).all()
    today = datetime.now(UTC).date()
    for org_id, keep_transcript, keep_audio in orgs:
        async with session_for(org_id) as db:
            old = select(StandupSession.id).where(StandupSession.run_date < today - timedelta(days=keep_transcript))
            seg = await db.execute(delete(TranscriptSegment).where(TranscriptSegment.session_id.in_(old)))
            rec = (
                (
                    await db.execute(
                        select(StandupSession).where(
                            StandupSession.recording_uri.is_not(None),
                            StandupSession.run_date < today - timedelta(days=keep_audio),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for s in rec:
                await registry.blob().delete(key_from_uri(s.recording_uri or ""))
            if rec:
                await db.execute(
                    update(StandupSession).where(StandupSession.id.in_([s.id for s in rec])).values(recording_uri=None)
                )
            n = seg.rowcount or 0  # type: ignore[attr-defined]
            if n or rec:
                await write_audit(
                    db,
                    org_id=org_id,
                    actor_name=SYSTEM_ACTOR,
                    action="retention.swept",
                    entity_type="organization",
                    entity_id=org_id,
                    diff={"transcript_segments": n, "recordings": len(rec)},
                )
        totals["orgs"] += 1
        totals["segments"] += n
        totals["recordings"] += len(rec)
    return totals


ACTIVITIES: list[Callable[..., Any]] = [load_context, mark_session, pending_async_users, retention_sweep]
