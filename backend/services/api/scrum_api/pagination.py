"""Opaque cursor pagination: ``?cursor=&limit=`` → ``{items, next_cursor}`` (plan §6.2)."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import Query
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api.errors import invalid


class Page:
    def __init__(self, cursor: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)):
        self.limit = limit
        self.offset = 0
        if cursor:
            try:
                self.offset = int(base64.urlsafe_b64decode(cursor.encode()).decode().removeprefix("o:"))
            except ValueError as exc:
                raise invalid("cursor", "Invalid cursor") from exc

    async def fetch(self, db: AsyncSession, stmt: Select[Any]) -> tuple[list[Any], str | None]:
        rows = list((await db.execute(stmt.offset(self.offset).limit(self.limit + 1))).scalars().all())
        nxt = None
        if len(rows) > self.limit:
            rows = rows[: self.limit]
            nxt = base64.urlsafe_b64encode(f"o:{self.offset + self.limit}".encode()).decode()
        return rows, nxt
