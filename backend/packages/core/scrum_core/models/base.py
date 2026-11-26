from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


def org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)


def str_enum(enum: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint (easier to evolve than native PG enums)."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        create_constraint=True,
        validate_strings=True,
    )


class TenantMixin:
    """id, org_id, created_at, updated_at on every tenant table (plan §4)."""

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


# ------------------------------------------------------------------------------------------
# Enums shared by models and API schemas
# ------------------------------------------------------------------------------------------


class Role(StrEnum):
    org_admin = "org_admin"
    scrum_lead = "scrum_lead"
    member = "member"
    viewer = "viewer"


class MeetingProviderKind(StrEnum):
    livekit = "livekit"
    fake = "fake"
    recall_teams = "recall_teams"
    graph_bridge = "graph_bridge"
    recall_zoom = "recall_zoom"
    recall_meet = "recall_meet"


class IntegrationKind(StrEnum):
    teams = "teams"  # the meeting-provider slot (LiveKit in the open-source build)
    jira = "jira"
    mail = "mail"
    ado = "ado"


class IntegrationStatus(StrEnum):
    connected = "connected"
    error = "error"
    expiring = "expiring"
    disconnected = "disconnected"


class QuestionType(StrEnum):
    text = "text"
    yes_no = "yes_no"
    ticket_list = "ticket_list"


class FollowupPolicy(StrEnum):
    none = "none"
    if_vague = "if_vague"
    always = "always"


class SessionStatus(StrEnum):
    scheduled = "scheduled"
    running = "running"
    extracting = "extracting"
    delivered = "delivered"
    skipped = "skipped"
    failed = "failed"


class AttendanceStatus(StrEnum):
    present = "present"
    absent = "absent"
    async_ = "async"


class UpdateSource(StrEnum):
    voice = "voice"
    async_ = "async"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class BlockerStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    needs_review = "needs_review"


class BlockerEventKind(StrEnum):
    raised = "raised"
    mentioned = "mentioned"
    alert_sent = "alert_sent"
    acknowledged = "acknowledged"
    escalated = "escalated"
    resolved = "resolved"
    reopened = "reopened"


class ReviewKind(StrEnum):
    person_match = "person_match"
    blocker_match = "blocker_match"
    pm_writeback = "pm_writeback"


class ReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class NotificationType(StrEnum):
    digest = "digest"
    blocker_alert = "blocker_alert"
    escalation = "escalation"
    async_checkin = "async_checkin"


class NotificationStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


__all__ = [
    "AttendanceStatus",
    "Base",
    "BlockerEventKind",
    "BlockerStatus",
    "FollowupPolicy",
    "IntegrationKind",
    "IntegrationStatus",
    "MeetingProviderKind",
    "NotificationStatus",
    "NotificationType",
    "QuestionType",
    "ReviewKind",
    "ReviewStatus",
    "Role",
    "SessionStatus",
    "Severity",
    "TenantMixin",
    "UpdateSource",
]
