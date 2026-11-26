from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scrum_core.models.base import (
    AttendanceStatus,
    Base,
    NotificationStatus,
    NotificationType,
    SessionStatus,
    TenantMixin,
    UpdateSource,
    str_enum,
)


class StandupSession(TenantMixin, Base):
    __tablename__ = "standup_sessions"
    __table_args__ = (UniqueConstraint("team_id", "run_date"),)

    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"))
    run_date: Mapped[date] = mapped_column(Date)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("question_templates.id"))
    status: Mapped[SessionStatus] = mapped_column(
        str_enum(SessionStatus, "session_status"), default=SessionStatus.scheduled
    )
    workflow_id: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_uri: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class Attendance(TenantMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[AttendanceStatus] = mapped_column(str_enum(AttendanceStatus, "attendance_status"))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranscriptSegment(TenantMixin, Base):
    __tablename__ = "transcript_segments"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE")
    )
    speaker_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    speaker_label: Mapped[str] = mapped_column(String(200))
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="SET NULL")
    )
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    # Low when the expected speaker (agent called on them) disagrees with the provider's speaker hint.
    speaker_confidence: Mapped[float] = mapped_column(Float, default=1.0)


Index("ix_transcript_segments_session_start", TranscriptSegment.session_id, TranscriptSegment.start_ms)


class MemberUpdateRow(TenantMixin, Base):
    __tablename__ = "member_updates"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[UpdateSource] = mapped_column(str_enum(UpdateSource, "update_source"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)  # schemas.extraction.MemberUpdate
    extraction_model: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)


class AsyncCheckin(TenantMixin, Base):
    """Raw answers from the emailed check-in form; the source of truth for async updates."""

    __tablename__ = "async_checkins"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    answers: Mapped[dict[str, str]] = mapped_column(JSONB)  # question_id -> answer


class Report(TenantMixin, Base):
    __tablename__ = "reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE"), unique=True
    )
    html: Mapped[str] = mapped_column(Text)
    html_uri: Mapped[str | None] = mapped_column(Text)
    pdf_uri: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Notification(TenantMixin, Base):
    """Outbound message ledger. The unique key makes every send idempotent across retries (plan §10)."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("org_id", "idempotency_key"),)

    idempotency_key: Mapped[str] = mapped_column(String(400))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="SET NULL")
    )
    blocker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("blockers.id", ondelete="SET NULL")
    )
    recipient: Mapped[str] = mapped_column(String(320))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType, "notification_type"))
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus, "notification_status"), default=NotificationStatus.pending
    )
    subject: Mapped[str] = mapped_column(Text, default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
