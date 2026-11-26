from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scrum_core.models.base import (
    Base,
    BlockerEventKind,
    BlockerStatus,
    ReviewKind,
    ReviewStatus,
    Severity,
    TenantMixin,
    str_enum,
)

EMBED_DIM = 768  # nomic-embed-text (Ollama). Changing it needs a migration.


class Blocker(TenantMixin, Base):
    __tablename__ = "blockers"

    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"))
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    blocked_on_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    blocked_on_raw: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    ticket_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"), default=Severity.medium)
    status: Mapped[BlockerStatus] = mapped_column(str_enum(BlockerStatus, "blocker_status"), default=BlockerStatus.open)
    first_seen_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="SET NULL")
    )
    last_seen_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days_open: Mapped[int] = mapped_column(Integer, default=0)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Alerts are held while the blocked-on person needs review (plan §9.2).
    alert_held: Mapped[bool] = mapped_column(Boolean, default=False)


Index("ix_blockers_ticket_keys", Blocker.ticket_keys, postgresql_using="gin")
Index(
    "ix_blockers_embedding_hnsw",
    Blocker.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
Index("ix_blockers_team_status", Blocker.team_id, Blocker.status)


class BlockerEvent(TenantMixin, Base):
    __tablename__ = "blocker_events"

    blocker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blockers.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[BlockerEventKind] = mapped_column(str_enum(BlockerEventKind, "blocker_event_kind"))
    actor_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="SET NULL")
    )


class BlockerEvidence(TenantMixin, Base):
    __tablename__ = "blocker_evidence"
    __table_args__ = (UniqueConstraint("blocker_id", "segment_id"),)

    blocker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blockers.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="CASCADE")
    )


class Dependency(TenantMixin, Base):
    __tablename__ = "dependencies"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="CASCADE")
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    to_team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"))
    on_raw: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    ticket_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class ReviewItem(TenantMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("org_id", "dedupe_key"),)

    kind: Mapped[ReviewKind] = mapped_column(str_enum(ReviewKind, "review_kind"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standup_sessions.id", ondelete="SET NULL")
    )
    # {raw_phrase, evidence_quote, evidence_speaker, candidates: [{id,label,sublabel,confidence}], context: {...}}
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[ReviewStatus] = mapped_column(str_enum(ReviewStatus, "review_status"), default=ReviewStatus.pending)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(400))


class ActionTokenUse(TenantMixin, Base):
    """Signed action links are single-use per action (plan §10)."""

    __tablename__ = "action_token_uses"
    __table_args__ = (UniqueConstraint("token_id", "action"),)

    token_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    actor_email: Mapped[str] = mapped_column(String(320))
