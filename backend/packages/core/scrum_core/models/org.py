from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scrum_core.models.base import (
    Base,
    IntegrationKind,
    IntegrationStatus,
    Role,
    TenantMixin,
    created_at,
    pk,
    str_enum,
    updated_at,
)


class Organization(Base):
    """Tenant root. Not RLS-protected; access is always via a user's membership."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    # OIDC issuer (Keycloak realm URL, or Entra tenant issuer) that authenticates this org's users.
    idp_issuer: Mapped[str | None] = mapped_column(String(500), unique=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_text: Mapped[str] = mapped_column(Text, default="This standup is being recorded for notes.")
    retention_days_audio: Mapped[int] = mapped_column(Integer, default=0)
    retention_days_transcript: Mapped[int] = mapped_column(Integer, default=90)
    escalation_days: Mapped[int] = mapped_column(Integer, default=3)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class User(TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "idp_subject"),
        UniqueConstraint("org_id", "email"),
    )

    # OIDC "sub" (Keycloak) or "oid" (Entra). In dev auth mode this is the persona key, e.g. "u-neha".
    idp_subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    department: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), default=Role.member)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Integration(TenantMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("org_id", "kind"),)

    kind: Mapped[IntegrationKind] = mapped_column(str_enum(IntegrationKind, "integration_kind"))
    status: Mapped[IntegrationStatus] = mapped_column(
        str_enum(IntegrationStatus, "integration_status"), default=IntegrationStatus.disconnected
    )
    display_name: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="Not connected")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Envelope encryption (plan §5): token sealed with a per-record DEK, DEK wrapped by the KEK.
    encrypted_token: Mapped[bytes | None] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_users_aliases", User.aliases, postgresql_using="gin")
