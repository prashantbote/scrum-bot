"""Blocker matching (plan §9.3): same blocker mentioned again → no new alert.

Decision for a newly extracted blocker against the team's open/acknowledged blockers:
  * shared ticket key and (same reporter or cosine ≥ 0.80)  → same blocker
  * cosine ≥ 0.90 (no shared ticket)                         → same blocker
  * 0.80 ≤ cosine < 0.90 (no shared ticket)                  → review_items(blocker_match)
  * otherwise                                                → new blocker
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from scrum_adapters.llm import cosine


@dataclass
class Existing:
    id: UUID
    reporter_id: UUID
    ticket_keys: list[str]
    embedding: list[float] | None
    description: str


@dataclass
class MatchDecision:
    kind: Literal["same", "review", "new"]
    blocker_id: UUID | None = None
    score: float = 0.0
    reason: str = ""


def embed_text(description: str, ticket_keys: list[str]) -> str:
    return f"{description} {' '.join(ticket_keys)}".strip()


def decide(
    *,
    reporter_id: UUID,
    ticket_keys: list[str],
    embedding: list[float],
    existing: list[Existing],
    same_with_ticket: float = 0.80,
    same_without_ticket: float = 0.90,
) -> MatchDecision:
    best_review: MatchDecision | None = None
    ranked = sorted(
        ((e, cosine(embedding, e.embedding) if e.embedding is not None else 0.0) for e in existing),
        key=lambda x: x[1],
        reverse=True,
    )
    for e, cos in ranked:
        shared = sorted(set(ticket_keys) & set(e.ticket_keys))
        if shared and (e.reporter_id == reporter_id or cos >= same_with_ticket):
            return MatchDecision(
                "same",
                e.id,
                max(cos, 0.9 if e.reporter_id == reporter_id else cos),
                f"{', '.join(shared)}, {max(cos, 0.0):.2f}",
            )
        if cos >= same_without_ticket:
            return MatchDecision("same", e.id, cos, f"similar description, {cos:.2f}")
        if cos >= same_with_ticket and best_review is None:
            best_review = MatchDecision("review", e.id, cos, f"possibly the same, {cos:.2f}")
    return best_review or MatchDecision("new")
