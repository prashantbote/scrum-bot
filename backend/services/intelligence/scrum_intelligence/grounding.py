"""Grounding guard (plan §9.1): drop anything not evidenced by the member's own segments."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from scrum_core.schemas.extraction import (
    TICKET_RE,
    Blocker,
    Dependency,
    LlmMemberExtraction,
    MemberUpdate,
    WorkItem,
    ticket_keys_in,
)
from scrum_intelligence.extraction import NEGATIVE, MemberTurn, _who

log = logging.getLogger(__name__)


@dataclass
class GroundingReport:
    dropped: list[str] = field(default_factory=list)

    @property
    def invented(self) -> int:
        return len(self.dropped)


def ground(turn: MemberTurn, x: LlmMemberExtraction) -> tuple[MemberUpdate, GroundingReport]:
    member_handles = {ln.handle: ln for ln in turn.member_lines()}
    spoken = " ".join(ln.text for ln in turn.lines).upper()
    report = GroundingReport()

    def evidence(handles: list[int], what: str) -> list[UUID] | None:
        valid = [h for h in handles if h in member_handles]
        if not valid:
            report.dropped.append(what)
            return None
        return [member_handles[h].segment_id for h in valid if member_handles[h].segment_id]  # type: ignore[misc]

    def tickets(keys: list[str], text: str = "", handles: list[int] | None = None) -> list[str]:
        """LLM keys + keys in the item's own text + the key of a single-ticket evidence line.
        A key must actually have been said (or asked about) in this turn."""
        found = [*keys, *ticket_keys_in(text)]
        for h in handles or []:
            if h in member_handles and len(line_keys := ticket_keys_in(member_handles[h].text)) == 1:
                found += line_keys
        return [k for k in dict.fromkeys(k.upper() for k in found) if TICKET_RE.fullmatch(k) and k in spoken]

    def evidence_text(handles: list[int]) -> str:
        return " ".join(member_handles[h].text for h in handles if h in member_handles)

    upd = MemberUpdate(member_id=turn.member_id)
    for item in x.completed:
        if (ev := evidence(item.evidence, f"completed: {item.summary}")) is not None:
            upd.completed.append(
                WorkItem(
                    summary=item.summary,
                    ticket_keys=tickets(item.ticket_keys, item.summary, item.evidence),
                    status=item.status if item.status != "planned" else "done",
                    evidence_segment_ids=ev,
                )
            )
    for item in x.planned:
        if (ev := evidence(item.evidence, f"planned: {item.summary}")) is not None:
            upd.planned.append(
                WorkItem(
                    summary=item.summary,
                    ticket_keys=tickets(item.ticket_keys, item.summary, item.evidence),
                    status="planned",
                    evidence_segment_ids=ev,
                )
            )
    for b in x.blockers:
        if NEGATIVE.match(b.description) or NEGATIVE.match(evidence_text(b.evidence) or "x"):
            report.dropped.append(f"blocker (says none): {b.description}")
            continue
        if (ev := evidence(b.evidence, f"blocker: {b.description}")) is not None:
            # Small models often leave "blocked_on" empty; recover it from the member's own words.
            on = b.blocked_on or _who(evidence_text(b.evidence)) or None
            upd.blockers.append(
                Blocker(
                    description=b.description,
                    blocked_on_raw=on,
                    ticket_keys=tickets(b.ticket_keys, b.description, b.evidence),
                    severity=b.severity,
                    confidence=b.confidence,
                    evidence_segment_ids=ev,
                )
            )
    for d in x.dependencies:
        if (ev := evidence(d.evidence, f"dependency: {d.description}")) is not None:
            upd.dependencies.append(
                Dependency(
                    description=d.description,
                    on_raw=d.on,
                    ticket_keys=tickets(d.ticket_keys, d.description, d.evidence),
                    evidence_segment_ids=ev,
                )
            )
    upd.challenges = [c for c in x.challenges if c.strip()][:5]
    if report.dropped:
        log.info("grounding guard dropped %d item(s) for %s: %s", report.invented, turn.member_name, report.dropped)
    return upd, report
