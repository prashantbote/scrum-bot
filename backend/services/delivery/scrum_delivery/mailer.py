"""Idempotent sending through the notifications ledger (plan §10).

1. Insert a ``pending`` row under the unique key (own transaction).
2. On conflict: skip if already ``sent`` (or a recent ``pending`` that another attempt owns);
   a ``failed`` or stale ``pending`` row is retried — the deterministic Message-ID lets mail clients
   dedupe the rare double send in that crash window.
3. Send, then mark ``sent`` with the provider id (or ``failed`` with the error, and re-raise so
   Temporal retries the activity).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from scrum_adapters import registry
from scrum_adapters.mail import OutboundMail
from scrum_core.audit import SYSTEM_ACTOR, write_audit
from scrum_core.db import session_for
from scrum_core.models import Notification
from scrum_core.models.base import NotificationStatus, NotificationType

log = logging.getLogger(__name__)
STALE_PENDING = timedelta(minutes=5)


async def send_once(
    *,
    org_id: UUID,
    key: str,
    type_: NotificationType,
    recipient: str,
    build: Callable[[], Awaitable[OutboundMail]],
    session_id: UUID | None = None,
    blocker_id: UUID | None = None,
    audit_entity: str | None = None,
) -> bool:
    """Returns True if this call sent the message."""
    async with session_for(org_id) as db:
        inserted = (
            await db.execute(
                insert(Notification)
                .values(
                    org_id=org_id,
                    idempotency_key=key,
                    session_id=session_id,
                    blocker_id=blocker_id,
                    recipient=recipient,
                    type=type_,
                    status=NotificationStatus.pending,
                )
                .on_conflict_do_nothing(index_elements=["org_id", "idempotency_key"])
                .returning(Notification.id)
            )
        ).scalar()
        if inserted is None:
            row = (await db.execute(select(Notification).where(Notification.idempotency_key == key))).scalar_one()
            fresh = row.updated_at > datetime.now(UTC) - STALE_PENDING
            if row.status == NotificationStatus.sent or (row.status == NotificationStatus.pending and fresh):
                return False
            row.status = NotificationStatus.pending
    msg = await build()
    try:
        provider_id = await registry.mail().send(msg, idempotency_key=key)
    except Exception as exc:
        async with session_for(org_id) as db:
            row = (await db.execute(select(Notification).where(Notification.idempotency_key == key))).scalar_one()
            row.status, row.error = NotificationStatus.failed, str(exc)[:1000]
        raise
    async with session_for(org_id) as db:
        row = (await db.execute(select(Notification).where(Notification.idempotency_key == key))).scalar_one()
        row.status, row.provider_message_id, row.sent_at, row.subject = (
            NotificationStatus.sent,
            provider_id,
            datetime.now(UTC),
            msg.subject,
        )
        await write_audit(
            db,
            org_id=org_id,
            actor_name=SYSTEM_ACTOR,
            action="mail.sent",
            entity_type="notification",
            entity_id=audit_entity or str(session_id or blocker_id or row.id),
            diff={"type": type_.value, "to": recipient},
        )
    return True
