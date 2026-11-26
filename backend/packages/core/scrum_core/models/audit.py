from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scrum_core.models.base import Base, org_fk, pk


class AuditLog(Base):
    """Append-only: the application role is granted SELECT and INSERT only."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(200))
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


Index("ix_audit_log_org_at", AuditLog.org_id, AuditLog.at.desc())
