"""Structured extraction (plan §9.1): open-source LLM first, deterministic heuristics as fallback.

Input is one member's turn: the bot's questions and the member's answers with segment handles
([S1], [S2] …). The LLM returns ``LlmMemberExtraction``; the grounding guard then maps handles to
segment UUIDs and drops anything not grounded in the member's own words.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from scrum_adapters.llm import LLMClient, LLMUnavailable, structured
from scrum_core.schemas.extraction import (
    LlmBlocker,
    LlmDependency,
    LlmMemberExtraction,
    LlmWorkItem,
    ticket_keys_in,
)

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).parent / "prompts" / "extract_v1.md").read_text(encoding="utf-8")
PROMPT_VERSION = "extract_v1"


@dataclass
class Line:
    handle: int  # [S#]
    segment_id: UUID | None  # None for async check-in answers
    speaker: str  # "bot" | "member"
    text: str
    question_position: int | None  # 1-based position of the template question this line belongs to
    question_text: str | None = None


@dataclass
class MemberTurn:
    member_id: UUID
    member_name: str
    lines: list[Line] = field(default_factory=list)
    source: str = "voice"

    def member_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.speaker == "member" and ln.text.strip()]

    def render(self) -> str:
        out = []
        for ln in self.lines:
            who = "Scrum Bot" if ln.speaker == "bot" else self.member_name
            q = f" (Q{ln.question_position}: {ln.question_text})" if ln.question_text and ln.speaker == "bot" else ""
            out.append(f"[S{ln.handle}] {who}{q}: {ln.text}")
        return "\n".join(out)


# ------------------------------------------------------------------------------- LLM


async def llm_extract(llm: LLMClient, turn: MemberTurn, *, model: str | None = None) -> LlmMemberExtraction:
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"Member: {turn.member_name}\nTranscript:\n{turn.render()}"},
    ]
    return await structured(llm, messages, LlmMemberExtraction, model=model, max_retries=2)


# ------------------------------------------------------------------------------- heuristics

NEGATIVE = re.compile(
    r"^\s*(no|nope|none|nothing|not really|all good|no blockers?|nothing blocking|no issues?)\b[\s,.!]*"
    r"(today|at the moment|right now|so far|for now|from my side)?[\s.!]*$",
    re.I,
)
BLOCKER_CUE = re.compile(
    r"\b(block(ed|ing|er)?|stuck|waiting|wait on|need(s|ed)?|can't|cannot|can not|unable|"
    r"failing|fails|broken|still no|pending)\b",
    re.I,
)
DEPENDS = re.compile(
    r"\bdepend(s|ing)? on (?P<who>[A-Z][\w-]*(?: (?:from|in|on) the [\w-]+| from [\w-]+| [A-Z][\w-]*)?)"
    r"(?: for (?P<what>[^.]+))?",
    re.I,
)
WHO_PATTERNS = [
    re.compile(r"\b(?:from|on|by|for) (?P<who>the [\w-]+ team)\b", re.I),
    re.compile(r"\bfrom (?P<who>(?:the )?[A-Z][\w-]*(?: from [\w-]+| team| [A-Z][\w-]*)?)"),
    re.compile(r"\b(?:waiting|wait) (?:on|for) (?P<who>(?:the )?[A-Z][\w-]*(?: team| from [\w-]+)?)"),
    re.compile(r"\b(?P<who>[A-Z][a-z]+) (?:said|promised|is looking|will look)"),
    re.compile(r"\b(?:blocked|stuck) (?:on|by) (?P<who>(?:the )?[A-Z][\w-]*(?: team)?)"),
    re.compile(r"\bon the (?P<who>[A-Za-z]+ team)\b"),
]
STOP_WHO = {
    "I",
    "PROJ",
    "The",
    "A",
    "It",
    "This",
    "That",
    "Staging",
    "Yesterday",
    "Today",
    "API",
    "PR",
    "UI",
    "DB",
    "CI",
    "SDK",
    "Jira",
}
SPLIT = re.compile(r"(?:;|\.\s+|,? and then |,? and also |, and |,? but )", re.I)
LEAD = re.compile(r"^(i|i've|i have|i'll|i will|i'm|i am|we|we'll|today i'll|today i will|yesterday i)\s+", re.I)
FILLER = re.compile(r"^(so|well|um+|uh+|okay|ok|yeah|yes|also|then|and)\b[,\s]*", re.I)
NOT_DONE = re.compile(r"\b(isn't|is not|not yet|not done|pending|in progress|half|partly|still)\b", re.I)


def _clauses(text: str) -> list[str]:
    parts = [FILLER.sub("", p.strip(" .,!")) for p in SPLIT.split(text) if p and p.strip(" .,!")]
    return [p for p in parts if len(p.split()) >= 2]


def _summary(clause: str) -> str:
    s = LEAD.sub("", clause.strip()).strip(" .")
    s = re.sub(r"^(finished|completed|wrapped up|worked on|will|going to|plan to|be)\s+", "", s, flags=re.I)
    s = re.sub(r"^(the|a)\s+", "", s, flags=re.I)
    s = " ".join(s.split()[:12])
    return s[:1].upper() + s[1:] if s else clause


def _who(text: str) -> str | None:
    for pat in WHO_PATTERNS:
        if m := pat.search(text):
            who = m.group("who").strip()
            head = who.removeprefix("the ").split()[0]
            if head not in STOP_WHO and not re.fullmatch(r"[A-Z]+-\d+", who):
                return who
    return None


def _severity(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(stuck|can't|cannot|blocked|failing|broken|down)\b", t):
        return "high"
    if re.search(r"\b(waiting|need|pending|still)\b", t):
        return "medium"
    return "low"


def heuristic_extract(turn: MemberTurn) -> LlmMemberExtraction:
    out = LlmMemberExtraction()
    # Ticket context: keys the bot or member mentioned anywhere in this turn.
    turn_tickets = ticket_keys_in(" ".join(ln.text for ln in turn.lines))
    for ln in turn.member_lines():
        pos = ln.question_position
        tickets = ticket_keys_in(ln.text)
        if pos == 1:
            for c in _clauses(ln.text):
                status = "in_progress" if NOT_DONE.search(c) else "done"
                if status == "in_progress" and not ticket_keys_in(c) and len(c.split()) < 4:
                    continue
                out.completed.append(
                    LlmWorkItem(
                        summary=_summary(c),
                        status=status,
                        evidence=[ln.handle],
                        ticket_keys=ticket_keys_in(c) or tickets[:1] or turn_tickets[:1],
                    )
                )
        elif pos == 2:
            for c in _clauses(ln.text):
                out.planned.append(
                    LlmWorkItem(
                        summary=_summary(c),
                        status="planned",
                        evidence=[ln.handle],
                        ticket_keys=ticket_keys_in(c) or tickets[:1] or turn_tickets[:1],
                    )
                )
        elif pos is not None and pos >= 3:
            if NEGATIVE.match(ln.text):
                continue
            if m := DEPENDS.search(ln.text):
                what = (m.group("what") or "").strip(" .")
                out.dependencies.append(
                    LlmDependency(
                        description=_summary(what) if what else ln.text.strip()[:120],
                        on=m.group("who").strip(),
                        evidence=[ln.handle],
                        ticket_keys=tickets or turn_tickets[:1],
                    )
                )
                continue
            if BLOCKER_CUE.search(ln.text):
                desc = _summary(ln.text.split(",")[0] if len(ln.text) > 90 else ln.text)
                out.blockers.append(
                    LlmBlocker(
                        description=desc,
                        blocked_on=_who(ln.text),
                        evidence=[ln.handle],
                        ticket_keys=tickets or turn_tickets[:1],
                        severity=_severity(ln.text),
                        confidence=0.7,
                    )
                )
            elif len(ln.text.split()) >= 4:
                out.challenges.append(ln.text.strip())
    return out


async def extract_turn(
    turn: MemberTurn, llm: LLMClient | None, *, model: str | None = None
) -> tuple[LlmMemberExtraction, str]:
    """Returns (extraction, model name). Falls back to heuristics if the model server is unavailable."""
    if llm is not None and turn.member_lines():
        try:
            return await llm_extract(llm, turn, model=model), f"{llm.name}/{PROMPT_VERSION}"
        except LLMUnavailable as exc:
            log.warning("LLM unavailable, using heuristic extraction: %s", exc)
        except ValueError as exc:
            log.warning("LLM output invalid after retries, using heuristic extraction: %s", exc)
    return heuristic_extract(turn), "heuristic-v1"
