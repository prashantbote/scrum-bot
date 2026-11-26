"""Structured extraction schemas (plan §9.1). The LLM must fill these; every item is grounded in segment ids."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b")


def ticket_keys_in(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for k in TICKET_RE.findall(text.upper() if text else ""):
        seen.setdefault(k, None)
    return list(seen)


class _Item(BaseModel):
    @field_validator("ticket_keys", mode="before", check_fields=False)
    @classmethod
    def _norm_tickets(cls, v: object) -> list[str]:
        if not v:
            return []
        items: list[object] = [v] if isinstance(v, str) else list(v) if isinstance(v, list | tuple) else [v]
        out: list[str] = []
        for raw in items:
            key = str(raw).strip().upper()
            if TICKET_RE.fullmatch(key) and key not in out:
                out.append(key)
        return out


class WorkItem(_Item):
    summary: str
    ticket_keys: list[str] = []
    status: Literal["done", "in_progress", "planned"]
    evidence_segment_ids: list[UUID] = []


class Blocker(_Item):
    description: str
    blocked_on_raw: str | None = None
    blocked_on_member_id: UUID | None = None
    ticket_keys: list[str] = []
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: float = Field(default=0.8, ge=0, le=1)
    evidence_segment_ids: list[UUID] = []


class Dependency(_Item):
    description: str
    on_raw: str
    on_member_id: UUID | None = None
    on_team_id: UUID | None = None
    ticket_keys: list[str] = []
    evidence_segment_ids: list[UUID] = []


class MemberUpdate(BaseModel):
    member_id: UUID
    completed: list[WorkItem] = []
    planned: list[WorkItem] = []
    blockers: list[Blocker] = []
    dependencies: list[Dependency] = []
    challenges: list[str] = []
    answers: dict[str, str] = {}  # question_id -> normalized answer


# ---------------------------------------------------------------------------------------------
# What the LLM is asked to produce for ONE member. Segment references are short integer handles
# ("S3") rather than UUIDs: small local models copy short handles far more reliably.
# ---------------------------------------------------------------------------------------------


class LlmWorkItem(BaseModel):
    summary: str = Field(description="Short imperative summary, max 12 words")
    ticket_keys: list[str] = Field(default=[], description="Ticket keys like PROJ-142 mentioned for this item")
    status: Literal["done", "in_progress", "planned"]
    evidence: list[int] = Field(description="Segment numbers (from [S#]) that state this item")


class LlmBlocker(BaseModel):
    description: str = Field(description="What is blocked and why, max 15 words")
    blocked_on: str | None = Field(default=None, description="Person or team they are waiting on, as spoken")
    ticket_keys: list[str] = []
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: float = Field(default=0.8, ge=0, le=1)
    evidence: list[int]


class LlmDependency(BaseModel):
    description: str
    on: str = Field(description="Person or team depended on, as spoken")
    ticket_keys: list[str] = []
    evidence: list[int]


class LlmMemberExtraction(BaseModel):
    completed: list[LlmWorkItem] = []
    planned: list[LlmWorkItem] = []
    blockers: list[LlmBlocker] = []
    dependencies: list[LlmDependency] = []
    challenges: list[str] = []
