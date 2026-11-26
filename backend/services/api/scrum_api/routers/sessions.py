"""Standup sessions, transcript, attendance, updates and reports."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_adapters import registry
from scrum_adapters.blob import key_from_uri
from scrum_api import projections as P
from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session, require_role
from scrum_api.errors import Problem, forbidden
from scrum_api.pagination import Page
from scrum_api.rbac import require_configure, session_or_404, team_or_404
from scrum_core import workflow_client
from scrum_core.audit import write_audit
from scrum_core.models import (
    Attendance,
    MemberUpdateRow,
    Notification,
    Question,
    Report,
    StandupSession,
    TranscriptSegment,
    User,
)
from scrum_core.models.base import NotificationStatus, NotificationType, Role
from scrum_core.schemas.workflow import RESEND_DIGEST_WORKFLOW, ResendDigestInput
from scrum_core.security.tokens import InvalidToken, sign, verify_payload
from scrum_core.settings import get_settings

router = APIRouter(tags=["sessions"])


@router.get("/teams/{team_id}/sessions", response_model=S.Paginated[S.SessionSummary])
async def list_sessions(
    team_id: UUID, page: Page = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.Paginated[S.SessionSummary]:
    await team_or_404(p, db, team_id)
    rows, nxt = await page.fetch(
        db, select(StandupSession).where(StandupSession.team_id == team_id).order_by(StandupSession.run_date.desc())
    )
    return S.Paginated[S.SessionSummary](
        items=[P.summary_of(s) for s in await P.sessions_out(db, rows)], next_cursor=nxt
    )


@router.get("/sessions/{session_id}", response_model=S.SessionOut)
async def get_session(
    session_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.SessionOut:
    return (await P.sessions_out(db, [await session_or_404(p, db, session_id)]))[0]


@router.get("/sessions/{session_id}/attendance", response_model=list[S.AttendanceOut])
async def attendance(
    session_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.AttendanceOut]:
    s = await session_or_404(p, db, session_id)
    rows = await db.execute(
        select(Attendance, User)
        .join(User, User.id == Attendance.user_id)
        .where(Attendance.session_id == s.id)
        .order_by(User.display_name)
    )
    return [
        S.AttendanceOut(user_id=u.id, display_name=u.display_name, status=a.status, joined_at=a.joined_at)
        for a, u in rows
    ]


@router.get("/sessions/{session_id}/transcript", response_model=list[S.TranscriptSegmentOut])
async def transcript(
    session_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.TranscriptSegmentOut]:
    s = await session_or_404(p, db, session_id)
    if p.role == Role.viewer:
        raise forbidden("Viewers see team-level reports only, not transcripts.")
    if p.role == Role.scrum_lead and s.team_id not in p.lead_team_ids and s.team_id not in p.member_team_ids:
        raise forbidden()
    stmt = (
        select(TranscriptSegment, Question.text)
        .outerjoin(Question, Question.id == TranscriptSegment.question_id)
        .where(TranscriptSegment.session_id == s.id)
        .order_by(TranscriptSegment.start_ms)
    )
    # Members (and leads looking at a team they only belong to) see only their own segments (plan §6.1).
    if p.role == Role.member or (p.role == Role.scrum_lead and s.team_id not in p.lead_team_ids):
        stmt = stmt.where(TranscriptSegment.speaker_user_id == p.user_id)
    return [
        S.TranscriptSegmentOut(
            id=t.id,
            speaker_user_id=t.speaker_user_id,
            speaker_label=t.speaker_label,
            question_id=t.question_id,
            question_text=q,
            start_ms=t.start_ms,
            end_ms=t.end_ms,
            text=t.text,
            confidence=t.confidence,
        )
        for t, q in (await db.execute(stmt))
    ]


@router.get("/sessions/{session_id}/updates", response_model=list[S.MemberUpdateOut])
async def updates(
    session_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.MemberUpdateOut]:
    s = await session_or_404(p, db, session_id)
    att = dict(
        (await db.execute(select(Attendance.user_id, Attendance.status).where(Attendance.session_id == s.id))).all()
    )
    rows = await db.execute(
        select(MemberUpdateRow, User)
        .join(User, User.id == MemberUpdateRow.user_id)
        .where(MemberUpdateRow.session_id == s.id)
        .order_by(MemberUpdateRow.created_at)
    )
    out = []
    for row, u in rows:
        d = row.payload
        out.append(
            S.MemberUpdateOut(
                member_id=u.id,
                display_name=u.display_name,
                attendance=att.get(u.id, "present"),
                source=row.source,
                completed=d.get("completed", []),
                planned=d.get("planned", []),
                blockers=d.get("blockers", []),
                dependencies=d.get("dependencies", []),
                challenges=d.get("challenges", []),
            )
        )
    return out


def file_url(uri: str, filename: str, content_type: str) -> str:
    token = sign({"k": "file", "uri": uri, "name": filename, "ct": content_type, "exp": int(time.time()) + 3600})
    return f"{get_settings().public_api_url}/files/{token}"


@router.get("/sessions/{session_id}/report", response_model=S.ReportOut)
async def report(
    session_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.ReportOut:
    s = await session_or_404(p, db, session_id)
    rep = (await db.execute(select(Report).where(Report.session_id == s.id))).scalar_one_or_none()
    notes = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.session_id == s.id,
                    Notification.type == NotificationType.digest,
                    Notification.status == NotificationStatus.sent,
                )
            )
        )
        .scalars()
        .all()
    )
    return S.ReportOut(
        session_id=s.id,
        html=rep.html if rep else "",
        pdf_url=file_url(rep.pdf_uri, f"standup-{s.run_date}.pdf", "application/pdf") if rep and rep.pdf_uri else None,
        recipients=sorted({n.recipient for n in notes}),
        sent_at=min((n.sent_at for n in notes if n.sent_at), default=None),
    )


@router.post("/sessions/{session_id}/resend-digest", response_model=S.QueuedOut, status_code=202)
async def resend_digest(
    session_id: UUID,
    p: Principal = Depends(require_role(Role.org_admin, Role.scrum_lead)),
    db: AsyncSession = Depends(db_session),
) -> S.QueuedOut:
    s = await session_or_404(p, db, session_id)
    require_configure(p, s.team_id)
    if (await db.execute(select(Report.id).where(Report.session_id == s.id))).first() is None:
        raise Problem(409, "No report yet", "This standup has no report to send yet.")
    recipients = {
        n
        for n in (
            await db.execute(
                select(Notification.recipient).where(
                    Notification.session_id == s.id, Notification.type == NotificationType.digest
                )
            )
        ).scalars()
    }
    nonce = f"{int(time.time())}"
    if get_settings().temporal_enabled:
        await workflow_client.start_job(
            RESEND_DIGEST_WORKFLOW,
            ResendDigestInput(org_id=p.org_id, session_id=s.id, nonce=nonce),
            id=f"resend-digest-{s.id}-{nonce}",
        )
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action="mail.resent",
        entity_type="notification",
        entity_id=s.id,
        diff={"type": "digest", "recipients": max(1, len(recipients))},
    )
    return S.QueuedOut(queued=max(1, len(recipients)))


@router.get("/files/{token}", include_in_schema=False)
async def get_file(token: str) -> Response:
    """Short-lived signed link to a report PDF (works for local disk and S3 backends alike)."""
    try:
        f = verify_payload(token, kind="file")
    except InvalidToken as exc:
        raise Problem(404, "Link not recognised", str(exc)) from exc
    data = await registry.blob().get(key_from_uri(f["uri"]))
    if data is None:
        raise Problem(404, "File not found")
    return Response(data, media_type=f["ct"], headers={"Content-Disposition": f'inline; filename="{f["name"]}"'})
