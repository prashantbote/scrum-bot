"""Turn decisions for the conversation controller (plan §8.2).

``LlmJudge`` uses the fast open-source model (e.g. llama3.2:3b on Ollama) with a hard timeout and
falls back to ``HeuristicJudge`` so a slow model never stalls the call.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from scrum_adapters.llm import LLMClient, LLMUnavailable, structured
from scrum_core.schemas.extraction import ticket_keys_in
from scrum_core.schemas.workflow import MemberCtx, QuestionCtx

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).parent / "prompts" / "controller_v1.md").read_text(encoding="utf-8")

VAGUE = re.compile(
    r"\b(stuff|things|same as yesterday|the usual|bits and pieces|some work|this and that|"
    r"not much|nothing much|various|misc)\b",
    re.I,
)
AFFIRMATIVE = re.compile(
    r"^\s*(yes|yeah|yep|yup|correct|right|that's right|that is right|exactly|sounds good|"
    r"looks good|perfect|sure|affirmative|all good|resolved|it is|done)\b",
    re.I,
)
NEGATIVE_BLOCKERS = re.compile(r"^\s*(no|nope|none|nothing|not really|all good)\b", re.I)


@dataclass
class Decision:
    action: Literal["next", "follow_up"]
    utterance: str | None = None


class TurnJudge(Protocol):
    async def judge(self, q: QuestionCtx, answer: str, followups_used: int, member: MemberCtx) -> Decision: ...


_TRAILING = re.compile(r"(?:\s+(?:and|or|but|so|for|to|the|a|an|of|on|with|from|in|,))+$", re.I)


def _short(text: str, words: int = 8) -> str:
    first = re.split(r"[.;]| but | and then |, and ", text.strip(), maxsplit=1)[0]
    first = re.sub(
        r"^(i|i've|i have|i'll|i will|today i'll|today i will|yesterday i)\s+", "", first.strip(), flags=re.I
    )
    return _TRAILING.sub("", " ".join(first.split()[:words]).rstrip(",")).strip()


def summarize(member: MemberCtx, answers: list[tuple[QuestionCtx, str]]) -> str:
    """One-line read-back for the CONFIRM step."""
    bits: list[str] = []
    for q, a in answers:
        if not a.strip():
            continue
        if q.position >= 3 or "block" in q.text.lower():
            bits.append("no blockers" if NEGATIVE_BLOCKERS.match(a) else f"blocker: {_short(a, 10)}")
        elif q.position == 1:
            bits.append(f"done: {_short(a)}")
        elif q.position == 2:
            bits.append(f"today: {_short(a)}")
        else:
            bits.append(_short(a))
    return "; ".join(bits) or "nothing to report"


def is_affirmative(text: str) -> bool:
    return bool(AFFIRMATIVE.match(text))


class HeuristicJudge:
    async def judge(self, q: QuestionCtx, answer: str, followups_used: int, member: MemberCtx) -> Decision:
        if q.followup_policy == "none" or followups_used >= q.max_followups:
            return Decision("next")
        words = len(answer.split())
        is_blocker_q = "block" in q.text.lower() or q.position >= 3
        if is_blocker_q and NEGATIVE_BLOCKERS.match(answer):
            return Decision("next")
        if q.followup_policy == "always" and followups_used == 0:
            return Decision("follow_up", "Anything else worth adding on that?")
        vague = words < 4 or bool(VAGUE.search(answer))
        if q.type == "ticket_list" and not ticket_keys_in(answer) and member.open_tickets and words < 8:
            vague = True
        if not vague:
            return Decision("next")
        if is_blocker_q:
            return Decision("follow_up", "Who or what are you waiting on, exactly?")
        if q.type == "ticket_list":
            return Decision("follow_up", "Which ticket or task was that, specifically?")
        return Decision("follow_up", "Could you be a bit more specific?")


class _LlmDecision(BaseModel):
    action: Literal["next", "follow_up"]
    utterance: str | None = None
    judged_complete: bool = True


class LlmJudge:
    def __init__(self, llm: LLMClient, model: str | None, timeout_s: float = 2.5) -> None:
        self._llm, self._model, self._timeout = llm, model, timeout_s
        self._fallback = HeuristicJudge()

    async def judge(self, q: QuestionCtx, answer: str, followups_used: int, member: MemberCtx) -> Decision:
        if q.followup_policy == "none" or followups_used >= q.max_followups:
            return Decision("next")
        tickets = ", ".join(f"{t.key} ({t.summary})" for t in member.open_tickets[:5]) or "none"
        messages = [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": f"Question ({q.type}, follow-up policy {q.followup_policy}): {q.text}\n"
                f"{member.first_name}'s open tickets: {tickets}\n"
                f'Follow-ups already asked: {followups_used}\nAnswer: "{answer}"',
            },
        ]
        try:
            d = await asyncio.wait_for(
                structured(self._llm, messages, _LlmDecision, model=self._model, max_retries=0, max_tokens=80),
                self._timeout,
            )
        except (TimeoutError, LLMUnavailable, ValueError) as exc:
            log.info("judge fallback to heuristics: %s", exc.__class__.__name__)
            return await self._fallback.judge(q, answer, followups_used, member)
        if d.action == "follow_up" and d.utterance and d.utterance.strip().endswith("?"):
            return Decision("follow_up", " ".join(d.utterance.split()[:22]))
        return Decision("next")
