from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scrum_core.models.base import (
    Base,
    FollowupPolicy,
    MeetingProviderKind,
    QuestionType,
    TenantMixin,
    str_enum,
)


class Team(TenantMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str] = mapped_column(String(200))
    lead_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    meeting_provider: Mapped[MeetingProviderKind] = mapped_column(
        str_enum(MeetingProviderKind, "meeting_provider"), default=MeetingProviderKind.livekit
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    pm_board_id: Mapped[str | None] = mapped_column(String(100))
    pm_project_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class TeamMember(TenantMixin, Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    pm_account_id: Mapped[str | None] = mapped_column(String(200))
    speaking_order: Mapped[int] = mapped_column(Integer, default=0)


class QuestionTemplate(TenantMixin, Base):
    """Versioned and immutable once a session used it; edits create a new version (plan §4.1)."""

    __tablename__ = "question_templates"
    __table_args__ = (UniqueConstraint("team_id", "version"),)

    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    questions: Mapped[list[Question]] = relationship(
        order_by="Question.position", cascade="all, delete-orphan", lazy="selectin"
    )


class Question(TenantMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("template_id", "position"),)

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_templates.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[QuestionType] = mapped_column(str_enum(QuestionType, "question_type"), default=QuestionType.text)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    followup_policy: Mapped[FollowupPolicy] = mapped_column(
        str_enum(FollowupPolicy, "followup_policy"), default=FollowupPolicy.if_vague
    )
    max_followups: Mapped[int] = mapped_column(Integer, default=2)


class Schedule(TenantMixin, Base):
    __tablename__ = "schedules"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), unique=True
    )
    cron: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))
    holiday_calendar: Mapped[str | None] = mapped_column(String(16))  # ISO country code for `holidays`
    skip_dates: Mapped[list[date]] = mapped_column(ARRAY(Date), default=list)
    async_window_minutes: Mapped[int] = mapped_column(Integer, default=120)
    lead_minutes: Mapped[int] = mapped_column(Integer, default=5)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    temporal_schedule_id: Mapped[str | None] = mapped_column(String(200))
    recurring_meeting_id: Mapped[str | None] = mapped_column(String(200))
    join_url: Mapped[str | None] = mapped_column(Text)
