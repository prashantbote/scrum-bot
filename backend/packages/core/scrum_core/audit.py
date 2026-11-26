"""write_audit(): every config change and every outbound message is recorded (plan §12)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from scrum_core.models import AuditLog

SYSTEM_ACTOR = "Scrum Bot"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


async def write_audit(
    session: AsyncSession,
    *,
    org_id: UUID,
    actor_name: str,
    action: str,
    entity_type: str,
    entity_id: UUID | str,
    diff: dict[str, Any] | None = None,
    actor_user_id: UUID | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            diff=_jsonable(diff or {}),
            ip=ip,
        )
    )
