"""Extraction evals (plan §9.4): blocker precision/recall, ticket recall and invented-item rate (target 0).

* Default (CI): the deterministic heuristic engine.
* ``pytest -m llm tests/evals``: the open-source LLM on the configured OpenAI-compatible server
  (Ollama by default; set SCRUM_LLM_BASE_URL / SCRUM_LLM_STRONG_MODEL). Prints a metrics table.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from scrum_adapters.llm import OpenAICompatLLM
from scrum_intelligence.extraction import Line, MemberTurn, extract_turn
from scrum_intelligence.grounding import ground

CASES = json.loads((Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    invented: int = 0
    tickets_expected: int = 0
    tickets_found: int = 0
    deps_ok: int = 0
    on_ok: int = 0
    on_total: int = 0

    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


def turn_for(case: dict) -> MemberTurn:
    lines = [Line(i + 1, uuid.uuid4(), who, text, pos) for i, (who, pos, text) in enumerate(case["lines"])]
    return MemberTurn(uuid.uuid4(), case["member"], lines)


async def evaluate(llm, model: str | None = None) -> tuple[Score, list[str]]:
    score, notes = Score(), []
    for case in CASES:
        turn = turn_for(case)
        raw, engine = await extract_turn(turn, llm, model=model)
        upd, report = ground(turn, raw)
        exp = case["expect"]
        score.invented += report.invented
        n_exp, n_got = len(exp["blockers"]), len(upd.blockers)
        score.tp += min(n_exp, n_got)
        score.fp += max(0, n_got - n_exp)
        score.fn += max(0, n_exp - n_got)
        for want, got in zip(exp["blockers"], upd.blockers, strict=False):
            score.on_total += 1
            on = (got.blocked_on_raw or "").lower()
            score.on_ok += (want["on"] is None and not on) or (want["on"] is not None and want["on"].lower() in on)
        found = {k for w in upd.completed for k in w.ticket_keys}
        score.tickets_expected += len(exp["completed_tickets"])
        score.tickets_found += len(set(exp["completed_tickets"]) & found)
        score.deps_ok += len(upd.dependencies) == exp["dependencies"]
        if n_exp != n_got or report.invented:
            notes.append(f"{case['name']} [{engine}]: blockers {n_got}/{n_exp}, dropped {report.dropped}")
    return score, notes


async def test_heuristic_engine_meets_baseline():
    score, notes = await evaluate(None)
    assert score.invented == 0, notes
    assert score.precision() == 1.0 and score.recall() == 1.0, notes
    assert score.tickets_found == score.tickets_expected
    assert score.on_ok == score.on_total
    assert score.deps_ok == len(CASES)


def _llm_reachable(base: str) -> bool:
    try:
        return httpx.get(base.rstrip("/").removesuffix("/v1") + "/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.llm
async def test_open_source_llm_extraction_quality():
    base = os.environ.get("SCRUM_EVAL_LLM_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("SCRUM_EVAL_LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")
    if not _llm_reachable(base):
        pytest.skip(f"no OpenAI-compatible LLM server at {base}")
    llm = OpenAICompatLLM(base, "ollama", model, timeout=180)
    score, notes = await evaluate(llm, model)
    print(
        f"\n{model}: blocker P={score.precision():.2f} R={score.recall():.2f} | blocked-on "
        f"{score.on_ok}/{score.on_total} | done tickets {score.tickets_found}/{score.tickets_expected} | "
        f"deps {score.deps_ok}/{len(CASES)} | invented (dropped by guard) {score.invented}"
    )
    for n in notes:
        print("  ", n)
    # The grounding guard removes ungrounded items before they reach anyone; what's left must be accurate.
    assert score.recall() >= 0.75 and score.precision() >= 0.75
    assert score.tickets_found >= score.tickets_expected - 1
