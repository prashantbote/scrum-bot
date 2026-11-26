"""Temporal activities on the ``delivery`` task queue (plan §10)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from scrum_adapters import registry
from scrum_adapters.blob import key_from_uri
from scrum_adapters.mail import Attachment, OutboundMail
from scrum_core.db import session_for
from scrum_core.models import (
    Attendance,
    Blocker,
    BlockerEvent,
    MemberUpdateRow,
    Organization,
    Question,
    Report,
    StandupSession,
    Team,
    TeamMember,
    TranscriptSegment,
    User,
)
from scrum_core.models.base import AttendanceStatus, BlockerEventKind, BlockerStatus, NotificationType, Role
from scrum_core.schemas.workflow import (
    AsyncRequest,
    BlockerAlertsInput,
    BlockerRefs,
    ResendDigestInput,
    SendResult,
    SessionRef,
)
from scrum_core.security.tokens import blocker_token, checkin_token
from scrum_core.settings import get_settings
from scrum_delivery.mailer import send_once
from scrum_delivery.render import html_to_pdf, long_date, render

# ------------------------------------------------------------------------------- report


async def _digest_context(db: AsyncSession, session: StandupSession) -> dict[str, Any]:
    team = await db.get(Team, session.team_id)
    assert team is not None
    users = {u.id: u for u in (await db.execute(select(User))).scalars()}
    att = (await db.execute(select(Attendance).where(Attendance.session_id == session.id))).scalars().all()
    rows = (
        (
            await db.execute(
                select(MemberUpdateRow)
                .where(MemberUpdateRow.session_id == session.id)
                .order_by(MemberUpdateRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    blocker_rows = {
        str(b.id): b for b in (await db.execute(select(Blocker).where(Blocker.team_id == team.id))).scalars()
    }
    order = {
        m.user_id: m.speaking_order
        for m in (await db.execute(select(TeamMember).where(TeamMember.team_id == team.id))).scalars()
    }
    rows = sorted(rows, key=lambda r: order.get(r.user_id, 99))

    def who(uid: Any) -> str:
        return users[uid].display_name if uid in users else "—"

    blockers, deps, updates = [], [], []
    for r in rows:
        p = r.payload
        for b in p.get("blockers", []):
            row = blocker_rows.get(b.get("_blocker_id", ""))
            on_id = b.get("blocked_on_member_id")
            blockers.append(
                {
                    "who": who(r.user_id),
                    "description": b["description"],
                    "blocked_on": who(UUID(on_id)) if on_id else b.get("blocked_on_raw"),
                    "ticket_keys": b.get("ticket_keys", []),
                    "repeat": bool(row and row.first_seen_session_id != session.id),
                    "days_open": row.days_open if row else 0,
                }
            )
        for d in p.get("dependencies", []):
            on_id = d.get("on_member_id")
            deps.append(
                {
                    "who": who(r.user_id),
                    "on": who(UUID(on_id)) if on_id else d.get("on_raw"),
                    "description": d["description"],
                }
            )
        updates.append(
            {
                "name": who(r.user_id),
                "source": r.source.value,
                "completed": p.get("completed", []),
                "planned": p.get("planned", []),
                "blockers": [
                    {"summary": b["description"], "ticket_keys": b.get("ticket_keys", [])}
                    for b in p.get("blockers", [])
                ],
                "challenges": p.get("challenges", []),
            }
        )
    attended = [a for a in att if a.status != AttendanceStatus.absent]
    return {
        "title": f"{team.name} standup",
        "kicker": "Daily standup report",
        "team_name": team.name,
        "date_long": long_date(session.run_date),
        "attended": len(attended),
        "total": len(att),
        "async_count": sum(1 for a in att if a.status == AttendanceStatus.async_),
        "absent": [who(a.user_id) for a in att if a.status == AttendanceStatus.absent],
        "blockers": blockers,
        "dependencies": deps,
        "updates": updates,
        "app_url": f"{get_settings().public_app_url}/standups/{session.id}/report",
    }


@activity.defn(name="render_report")
async def render_report(ref: SessionRef) -> str:
    async with session_for(ref.org_id) as db:
        session = await db.get(StandupSession, ref.session_id)
        assert session is not None
        ctx = await _digest_context(db, session)
    html = render("digest.html.j2", **ctx)
    blob = registry.blob()
    base = f"{ref.org_id}/reports/{ref.session_id}"
    html_uri = await blob.put(f"{base}.html", html.encode(), "text/html")
    pdf = await html_to_pdf(html)
    pdf_uri = await blob.put(f"{base}.pdf", pdf, "application/pdf") if pdf else None
    summary = {"attended": ctx["attended"], "total": ctx["total"], "blockers": len(ctx["blockers"])}
    async with session_for(ref.org_id) as db:
        await db.execute(
            insert(Report)
            .values(
                org_id=ref.org_id,
                session_id=ref.session_id,
                html=html,
                html_uri=html_uri,
                pdf_uri=pdf_uri,
                summary=summary,
            )
            .on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    "html": html,
                    "html_uri": html_uri,
                    "pdf_uri": pdf_uri,
                    "summary": summary,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
    return html_uri


async def _digest_recipients(db: AsyncSession, team: Team) -> list[User]:
    member_ids = (await db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))).scalars().all()
    users = (await db.execute(select(User).where(User.erased_at.is_(None)))).scalars().all()
    picked = [u for u in users if u.id == team.lead_user_id or u.id in member_ids or u.role == Role.viewer]
    return sorted(picked, key=lambda u: (u.id != team.lead_user_id, u.display_name))


async def _send_digest(org_id: UUID, session_id: UUID, nonce: str | None) -> SendResult:
    async with session_for(org_id) as db:
        session = await db.get(StandupSession, session_id)
        assert session is not None
        team = await db.get(Team, session.team_id)
        report = (await db.execute(select(Report).where(Report.session_id == session_id))).scalar_one()
        recipients = await _digest_recipients(db, team)  # type: ignore[arg-type]
        team_name, run_date = team.name, session.run_date  # type: ignore[union-attr]
        html, pdf_uri = report.html, report.pdf_uri
    pdf = await registry.blob().get(key_from_uri(pdf_uri)) if pdf_uri else None
    sent = skipped = 0
    for u in recipients:
        activity.heartbeat(u.email)

        async def build(u: User = u) -> OutboundMail:
            return OutboundMail(
                to=[u.email],
                subject=f"{team_name} standup · {long_date(run_date)}",
                html=html,
                text=f"{team_name} standup report for {run_date}. Open Scrum Bot for details.",
                attachments=[Attachment(f"standup-{run_date}.pdf", pdf, "application/pdf")] if pdf else [],
            )

        key = f"digest:{session_id}:{u.email}" + (f":resend-{nonce}" if nonce else "")
        ok = await send_once(
            org_id=org_id, key=key, type_=NotificationType.digest, recipient=u.email, session_id=session_id, build=build
        )
        sent, skipped = sent + ok, skipped + (not ok)
    return SendResult(sent=sent, skipped=skipped)


@activity.defn(name="send_digest")
async def send_digest(ref: SessionRef) -> SendResult:
    return await _send_digest(ref.org_id, ref.session_id, None)


@activity.defn(name="resend_digest")
async def resend_digest(inp: ResendDigestInput) -> SendResult:
    return await _send_digest(inp.org_id, inp.session_id, inp.nonce)


# ------------------------------------------------------------------------------- blocker alerts


async def _alert(org_id: UUID, blocker_id: UUID) -> bool:
    s = get_settings()
    async with session_for(org_id) as db:
        b = await db.get(Blocker, blocker_id)
        if (
            b is None
            or b.alert_held
            or b.blocked_on_user_id is None
            or b.status in (BlockerStatus.resolved, BlockerStatus.needs_review)
        ):
            return False
        team = await db.get(Team, b.team_id)
        to = await db.get(User, b.blocked_on_user_id)
        reporter = await db.get(User, b.reporter_user_id)
        lead = await db.get(User, team.lead_user_id) if team else None
        session = await db.get(StandupSession, b.first_seen_session_id) if b.first_seen_session_id else None
        quote = (
            (
                await db.execute(
                    select(TranscriptSegment.text)
                    .where(
                        TranscriptSegment.session_id == b.first_seen_session_id,
                        TranscriptSegment.speaker_user_id == b.reporter_user_id,
                    )
                    .order_by(TranscriptSegment.start_ms.desc())
                )
            )
            .scalars()
            .first()
            if b.first_seen_session_id
            else None
        )
        assert to is not None and reporter is not None and team is not None
        desc, tickets, team_name = b.description, list(b.ticket_keys or []), team.name
        cc = sorted({x.email for x in (reporter, lead) if x and x.email != to.email})
        run_date = session.run_date if session else datetime.now(UTC).date()
        to_email, to_name, reporter_name = to.email, to.display_name, reporter.display_name

    token = blocker_token(org_id=org_id, blocker_id=blocker_id, recipient=to_email)
    url = f"{s.public_app_url}/a/{token}"

    async def build() -> OutboundMail:
        html = render(
            "blocker_alert.html.j2",
            title="Blocker alert",
            kicker="Blocker alert",
            reporter=reporter_name,
            description=desc,
            team_name=team_name,
            date_long=long_date(run_date),
            ticket_keys=tickets,
            quote=quote,
            ack_url=url,
            resolve_url=url,
            ttl_days=s.action_token_ttl_days,
        )
        return OutboundMail(
            to=[to_email],
            cc=cc,
            subject=f"{reporter_name} is blocked on you: {desc[:60]}",
            html=html,
            text=f"{reporter_name} is blocked: {desc}\nAcknowledge or resolve: {url}",
        )

    sent = await send_once(
        org_id=org_id,
        key=f"blocker_alert:{blocker_id}:{to_email}",
        type_=NotificationType.blocker_alert,
        recipient=to_email,
        blocker_id=blocker_id,
        session_id=None,
        build=build,
        audit_entity=str(blocker_id),
    )
    if sent:
        async with session_for(org_id) as db:
            db.add(
                BlockerEvent(
                    org_id=org_id,
                    blocker_id=blocker_id,
                    at=datetime.now(UTC),
                    kind=BlockerEventKind.alert_sent,
                    actor_name="Scrum Bot",
                    note=f"Alert emailed to {to_name}" + (f" (cc {', '.join(cc)})" if cc else ""),
                )
            )
    return sent


@activity.defn(name="send_blocker_alerts")
async def send_blocker_alerts(refs: BlockerRefs) -> SendResult:
    sent = skipped = 0
    for bid in refs.new_blocker_ids:
        activity.heartbeat(str(bid))
        ok = await _alert(refs.org_id, bid)
        sent, skipped = sent + ok, skipped + (not ok)
    return SendResult(sent=sent, skipped=skipped)


@activity.defn(name="send_alerts_for")
async def send_alerts_for(inp: BlockerAlertsInput) -> SendResult:
    return await send_blocker_alerts(
        BlockerRefs(
            org_id=inp.org_id,
            session_id=inp.session_id or inp.team_id,
            team_id=inp.team_id,
            new_blocker_ids=inp.blocker_ids,
            matched_blocker_ids=[],
        )
    )


# ------------------------------------------------------------------------------- escalation


@activity.defn(name="escalate_stale_blockers")
async def escalate_stale_blockers(ref: SessionRef) -> SendResult:
    s = get_settings()
    async with session_for(ref.org_id) as db:
        org = await db.get(Organization, ref.org_id)
        team = await db.get(Team, ref.team_id)
        session = await db.get(StandupSession, ref.session_id)
        assert org is not None and team is not None and session is not None
        lead = await db.get(User, team.lead_user_id)
        stale = (
            (
                await db.execute(
                    select(Blocker).where(
                        Blocker.team_id == team.id,
                        Blocker.status == BlockerStatus.open,
                        Blocker.days_open >= org.escalation_days,
                    )
                )
            )
            .scalars()
            .all()
        )
        users = {u.id: u.display_name for u in (await db.execute(select(User))).scalars()}
        items = []
        tz = ZoneInfo(team.timezone)
        for b in stale:
            events = (
                (
                    await db.execute(
                        select(BlockerEvent).where(BlockerEvent.blocker_id == b.id).order_by(BlockerEvent.at)
                    )
                )
                .scalars()
                .all()
            )
            items.append(
                (
                    b.id,
                    b.description,
                    b.days_open,
                    list(b.ticket_keys or []),
                    users.get(b.reporter_user_id),
                    users.get(b.blocked_on_user_id) if b.blocked_on_user_id else b.blocked_on_raw,
                    [
                        {"at": e.at.astimezone(tz).strftime("%a %d %b %H:%M"), "kind": e.kind.value, "note": e.note}
                        for e in events
                    ],
                )
            )
        run_date = session.run_date
    if lead is None:
        return SendResult(sent=0, skipped=len(items))
    sent = skipped = 0
    for bid, desc, days, tickets, reporter, blocked_on, history in items:

        async def build(
            desc: str = desc,
            days: int = days,
            tickets: list[str] = tickets,
            reporter: Any = reporter,
            blocked_on: Any = blocked_on,
            events: list[Any] = history,
            bid: UUID = bid,
        ) -> OutboundMail:
            html = render(
                "escalation.html.j2",
                title="Escalation",
                kicker="Escalation",
                description=desc,
                days_open=days,
                ticket_keys=tickets,
                reporter=reporter,
                blocked_on=blocked_on,
                events=events,
                app_url=f"{s.public_app_url}/blockers/{bid}",
            )
            return OutboundMail(
                to=[lead.email],
                subject=f"Escalation: blocker open {days} days — {desc[:60]}",
                html=html,
                text=f"Blocker open for {days} days: {desc}",
            )

        ok = await send_once(
            org_id=ref.org_id,
            key=f"escalation:{bid}:{run_date}",
            type_=NotificationType.escalation,
            recipient=lead.email,
            blocker_id=bid,
            session_id=ref.session_id,
            build=build,
            audit_entity=str(bid),
        )
        if ok:
            async with session_for(ref.org_id) as db:
                row = await db.get(Blocker, bid)
                if row is not None:
                    row.escalated = True
                    db.add(
                        BlockerEvent(
                            org_id=ref.org_id,
                            blocker_id=bid,
                            at=datetime.now(UTC),
                            kind=BlockerEventKind.escalated,
                            actor_name="Scrum Bot",
                            session_id=ref.session_id,
                            note=f"Open for {days} days — escalated to {lead.display_name}",
                        )
                    )
        sent, skipped = sent + ok, skipped + (not ok)
    return SendResult(sent=sent, skipped=skipped)


# ------------------------------------------------------------------------------- async check-in


@activity.defn(name="send_async_checkin")
async def send_async_checkin(req: AsyncRequest) -> SendResult:
    """Emails each absentee a signed link to the web check-in form (open-source stand-in for Adaptive Cards)."""
    s = get_settings()
    closes = int(time.time()) + req.window_minutes * 60
    async with session_for(req.org_id) as db:
        session = await db.get(StandupSession, req.session_id)
        assert session is not None
        team = await db.get(Team, session.team_id)
        questions = (
            (
                await db.execute(
                    select(Question.text).where(Question.template_id == session.template_id).order_by(Question.position)
                )
            )
            .scalars()
            .all()
        )
        users = (await db.execute(select(User).where(User.id.in_(req.user_ids)))).scalars().all()
        tz = ZoneInfo(team.timezone) if team else UTC
        team_name = team.name if team else ""
    closes_at = (datetime.now(UTC) + timedelta(minutes=req.window_minutes)).astimezone(tz).strftime("%H:%M")
    sent = skipped = 0
    for u in users:
        token = checkin_token(org_id=req.org_id, session_id=req.session_id, user_id=u.id, expires_at=closes)
        url = f"{s.public_app_url}/a/{token}?type=checkin"

        async def build(u: User = u, url: str = url) -> OutboundMail:
            html = render(
                "checkin.html.j2",
                title="Async check-in",
                kicker="Async check-in",
                team_name=team_name,
                first_name=u.display_name.split()[0],
                questions=list(questions),
                url=url,
                closes_at=closes_at,
            )
            return OutboundMail(
                to=[u.email],
                subject=f"Quick check-in: {team_name} standup",
                html=html,
                text=f"Send your standup update: {url}",
            )

        ok = await send_once(
            org_id=req.org_id,
            key=f"async_checkin:{req.session_id}:{u.email}",
            type_=NotificationType.async_checkin,
            recipient=u.email,
            session_id=req.session_id,
            build=build,
        )
        sent, skipped = sent + ok, skipped + (not ok)
    return SendResult(sent=sent, skipped=skipped)


ACTIVITIES: list[Callable[..., Any]] = [
    render_report,
    send_digest,
    resend_digest,
    send_blocker_alerts,
    send_alerts_for,
    escalate_stale_blockers,
    send_async_checkin,
]
