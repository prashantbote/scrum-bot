"""People resolution (plan §9.2): roster/alias match → rapidfuzz + department hints → LLM tie-break.

Scores: >= 0.85 applied automatically; 0.60-0.85 → review_items(person_match) and the alert is held;
< 0.60 left unresolved (shown in the report only). Team mentions ("the backend team") resolve to
that team's lead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel
from rapidfuzz import fuzz

from scrum_adapters.llm import LLMClient, LLMUnavailable, structured

log = logging.getLogger(__name__)


@dataclass
class Person:
    id: UUID
    name: str
    aliases: list[str]
    department: str | None
    team_ids: set[UUID] = field(default_factory=set)

    @property
    def first(self) -> str:
        return self.name.split()[0].lower()


@dataclass
class TeamRef:
    id: UUID
    name: str
    lead_id: UUID


@dataclass
class Candidate:
    person: Person
    score: float
    why: str


@dataclass
class Resolution:
    raw: str
    best: Candidate | None
    candidates: list[Candidate]
    team: TeamRef | None = None

    @property
    def confidence(self) -> float:
        return self.best.score if self.best else 0.0


_HINT = re.compile(r"\b(?:from|in|on) (?:the )?(?P<hint>[a-z][\w-]*)(?: team)?\b", re.I)
_NOISE = re.compile(r"\b(the|team|from|in|on|guys|folks|people)\b", re.I)


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("’", "'").split())  # noqa: RUF001 (normalizes curly apostrophes)


def _strip_hint(raw: str) -> tuple[str, str | None]:
    m = _HINT.search(raw)
    hint = m.group("hint").lower() if m else None
    core = _HINT.sub("", raw) if m else raw
    return _norm(core).strip(" ,."), hint


def _match_team(raw: str, teams: list[TeamRef]) -> TeamRef | None:
    r = _norm(_NOISE.sub(" ", raw))
    if not r:
        return None
    best = max(teams, key=lambda t: fuzz.token_set_ratio(r, _norm(_NOISE.sub(" ", t.name))), default=None)
    if best and fuzz.token_set_ratio(r, _norm(_NOISE.sub(" ", best.name))) >= 85 and "team" in raw.lower():
        return best
    return None


def score_candidates(raw: str, roster: list[Person], *, reporter_team: UUID | None = None) -> list[Candidate]:
    core, hint = _strip_hint(raw)
    raw_n = _norm(raw)
    first_counts: dict[str, int] = {}
    for p in roster:
        first_counts[p.first] = first_counts.get(p.first, 0) + 1
    out: list[Candidate] = []
    for p in roster:
        names = [_norm(p.name)]
        aliases = [_norm(a) for a in p.aliases]
        if raw_n in names or core in names:
            out.append(Candidate(p, 1.0, "exact name"))
            continue
        if raw_n in aliases:
            out.append(Candidate(p, 0.97, "alias"))
            continue
        fuzzy = max(fuzz.token_set_ratio(core, n) for n in names + aliases) / 100 * 0.8
        why = "fuzzy"
        if core and core.split()[0] == p.first:
            unique = first_counts.get(p.first, 0) == 1
            fuzzy, why = max(fuzzy, 0.9 if unique else 0.8), "unique first name" if unique else "first name"
        if fuzzy < 0.5:
            continue
        if hint and p.department and hint in p.department.lower():
            fuzzy += 0.12
            why += f" + {p.department}"
        if reporter_team and reporter_team in p.team_ids:
            fuzzy += 0.05
            why += " + same team"
        out.append(Candidate(p, min(fuzzy, 0.96), why))
    out.sort(key=lambda c: c.score, reverse=True)
    # Ambiguity: several plausible people with close scores and no disambiguating hint.
    strong = [c for c in out if c.score >= 0.75]
    if len(strong) >= 2 and strong[0].score - strong[1].score < 0.15 and strong[0].score < 0.97:
        for c in out:
            c.score = round(c.score * 0.88, 3)
    return out[:3]


class _Pick(BaseModel):
    choice: int  # 1-based index into the candidate list, 0 = none of them
    confident: bool


async def llm_tiebreak(
    llm: LLMClient, raw: str, sentence: str, cands: list[Candidate], *, model: str | None = None
) -> int | None:
    listing = "\n".join(
        f"{i + 1}. {c.person.name} ({c.person.department or 'no department'})" for i, c in enumerate(cands)
    )
    messages = [
        {
            "role": "system",
            "content": 'Pick which person a standup speaker meant. Reply JSON {"choice": n, '
            '"confident": bool}; choice 0 if none fit.',
        },
        {"role": "user", "content": f'Sentence: "{sentence}"\nMentioned: "{raw}"\nCandidates:\n{listing}'},
    ]
    try:
        pick = await structured(llm, messages, _Pick, model=model, max_retries=1, max_tokens=60)
    except (LLMUnavailable, ValueError) as exc:
        log.info("LLM tie-break unavailable: %s", exc)
        return None
    return pick.choice - 1 if 1 <= pick.choice <= len(cands) and pick.confident else None


async def resolve(
    raw: str | None,
    sentence: str,
    roster: list[Person],
    teams: list[TeamRef],
    *,
    reporter_id: UUID,
    reporter_team: UUID | None,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> Resolution | None:
    if not raw or not raw.strip():
        return None
    if team := _match_team(raw, teams):
        lead = next((p for p in roster if p.id == team.lead_id), None)
        cands = [Candidate(lead, 0.86, f"lead of {team.name}")] if lead else []
        return Resolution(raw=raw, best=cands[0] if cands else None, candidates=cands, team=team)
    others = [p for p in roster if p.id != reporter_id]
    cands = score_candidates(raw, others, reporter_team=reporter_team)
    if llm is not None and len(cands) >= 2 and 0.6 <= cands[0].score < 0.85:
        idx = await llm_tiebreak(llm, raw, sentence, cands, model=model)
        if idx is not None:
            cands[idx].score = round(min(0.84, cands[idx].score + 0.08), 3)
            cands[idx].why += " + LLM"
            cands.sort(key=lambda c: c.score, reverse=True)
    return Resolution(raw=raw, best=cands[0] if cands else None, candidates=cands)
