"""Resolution scoring, blocker matching, heuristic extraction and the grounding guard (plan §9)."""

import uuid

import pytest

from scrum_adapters.llm import HashingEmbedder
from scrum_core.schemas.extraction import LlmBlocker, LlmMemberExtraction, LlmWorkItem
from scrum_intelligence.blocker_match import Existing, decide
from scrum_intelligence.extraction import Line, MemberTurn, heuristic_extract
from scrum_intelligence.grounding import ground
from scrum_intelligence.resolution import Person, TeamRef, resolve

U = {
    k: uuid.uuid5(uuid.NAMESPACE_DNS, k)
    for k in ["rahul", "amit", "amits", "arjun", "priya", "meera", "payments", "backend"]
}
ROSTER = [
    Person(U["rahul"], "Rahul Verma", [], "Payments", {U["payments"]}),
    Person(U["amit"], "Amit Sharma", ["Amit from backend"], "Backend", {U["payments"], U["backend"]}),
    Person(U["amits"], "Amit Singh", ["Amit from QA"], "QA", set()),
    Person(U["arjun"], "Arjun Patel", [], "Backend", {U["backend"]}),
    Person(U["priya"], "Priya Nair", [], "Payments", {U["payments"]}),
    Person(U["meera"], "Meera Das", [], "Backend", {U["backend"]}),
]
TEAMS = [TeamRef(U["payments"], "Payments", U["priya"]), TeamRef(U["backend"], "Backend Platform", U["arjun"])]


async def _resolve(raw: str):
    return await resolve(raw, "", ROSTER, TEAMS, reporter_id=U["rahul"], reporter_team=U["payments"])


@pytest.mark.parametrize(
    "raw,who,auto",
    [
        ("Amit from backend", "amit", True),  # alias → auto (≥ 0.85)
        ("Arjun", "arjun", True),  # unique first name → auto
        ("Meera Das", "meera", True),  # exact
        ("the backend team", "arjun", True),  # team mention → that team's lead
        ("Amit", "amit", False),  # two Amits, no hint → review queue
    ],
)
async def test_people_resolution(raw, who, auto):
    r = await _resolve(raw)
    assert r and r.best and r.best.person.id == U[who]
    assert (r.confidence >= 0.85) is auto, (raw, r.confidence)
    if not auto:
        assert 0.6 <= r.confidence < 0.85 and len(r.candidates) == 2


async def test_unknown_people_stay_unresolved():
    r = await _resolve("DevOps")
    assert r is None or r.best is None or r.confidence < 0.6


def test_blocker_matching_rules():
    emb = HashingEmbedder()
    vec = emb._one("Waiting on code review for the Payment UI PROJ-150")
    priya, other = uuid.uuid4(), uuid.uuid4()
    existing = [Existing(uuid.uuid4(), priya, ["PROJ-150"], vec, "Waiting on code review for the Payment UI")]
    # Same reporter + shared ticket → same blocker, even when phrased differently.
    reworded = emb._one("PROJ-150 is still waiting on review PROJ-150")
    assert decide(reporter_id=priya, ticket_keys=["PROJ-150"], embedding=reworded, existing=existing).kind == "same"
    # Identical description from someone else, no ticket → same (cosine ≥ 0.90).
    assert decide(reporter_id=other, ticket_keys=[], embedding=vec, existing=existing).kind == "same"
    # Unrelated → new.
    unrelated = emb._one("Kafka consumer lag alerts are noisy")
    assert decide(reporter_id=other, ticket_keys=[], embedding=unrelated, existing=existing).kind == "new"


def test_blocker_matching_review_band():
    e = uuid.uuid4()
    base = [1.0] + [0.0] * 767
    near = [0.85, 0.5267826876426369] + [0.0] * 766  # cosine 0.85 with base
    d = decide(
        reporter_id=uuid.uuid4(), ticket_keys=[], embedding=near, existing=[Existing(e, uuid.uuid4(), [], base, "x")]
    )
    assert d.kind == "review" and d.blocker_id == e and 0.8 <= d.score < 0.9


def _rahul_tuesday() -> MemberTurn:
    seg = [uuid.uuid4() for _ in range(8)]
    lines = [
        Line(1, seg[0], "bot", "Rahul, yesterday you were working on PROJ-142, the refund API. How did that go?", 1),
        Line(2, seg[1], "member", "I finished the main logic, but the testing isn't done.", 1),
        Line(3, seg[2], "bot", "Got it. Will testing finish today, or is anything stopping it?", 3),
        Line(4, seg[3], "member", "I need the sandbox credentials from Amit, so I'm stuck.", 3),
        Line(5, seg[4], "bot", "What's your plan for today?", 2),
        Line(6, seg[5], "member", "Finish the refund API tests as soon as I have the credentials.", 2),
        Line(7, seg[6], "bot", "So: refund logic done, blocked on credentials from Amit. Correct?", None),
        Line(8, seg[7], "member", "Yes.", None),
    ]
    return MemberTurn(U["rahul"], "Rahul Verma", lines)


def test_heuristic_extraction_of_rahuls_tuesday():
    turn = _rahul_tuesday()
    upd, report = ground(turn, heuristic_extract(turn))
    assert report.invented == 0
    assert [(w.summary, w.status) for w in upd.completed] == [
        ("Main logic", "done"),
        ("Testing isn't done", "in_progress"),
    ]
    assert upd.completed[0].ticket_keys == ["PROJ-142"]
    assert upd.planned and "refund API tests" in upd.planned[0].summary
    [b] = upd.blockers
    assert b.blocked_on_raw == "Amit" and b.severity == "high" and b.ticket_keys == ["PROJ-142"]
    assert b.evidence_segment_ids == [turn.lines[3].segment_id]


def test_grounding_guard_drops_invented_items():
    turn = _rahul_tuesday()
    llm_out = LlmMemberExtraction(
        completed=[
            LlmWorkItem(summary="Main logic", status="done", evidence=[2], ticket_keys=["PROJ-142"]),
            LlmWorkItem(summary="Deployed to prod", status="done", evidence=[]),  # no evidence
            LlmWorkItem(summary="Refund docs", status="done", evidence=[1]),
        ],  # bot line, not the member
        blockers=[
            LlmBlocker(
                description="Needs sandbox credentials", blocked_on=None, evidence=[4], ticket_keys=["PROJ-999"]
            ),  # ticket never said
            LlmBlocker(description="No blockers", evidence=[8]),
        ],
    )
    upd, report = ground(turn, llm_out)
    assert [w.summary for w in upd.completed] == ["Main logic"]
    assert report.invented == 3
    [b] = upd.blockers
    assert b.ticket_keys == [] and b.blocked_on_raw == "Amit"  # recovered from the member's own words


def test_stt_vocabulary_snapping():
    from scrum_adapters.stt import snap_to_vocabulary

    vocab = ["Rahul Verma", "Amit Sharma", "Priya Nair", "PROJ-142"]
    assert (
        snap_to_vocabulary("I need the credentials from Anit, so I'm stuck.", vocab)
        == "I need the credentials from Amit, so I'm stuck."
    )
    assert snap_to_vocabulary("Priyah said Rahul would review.", vocab) == "Priya said Rahul would review."
    assert snap_to_vocabulary("Rahool", vocab) == "Rahool"  # conservative: < 75% similar stays as heard
    # Ordinary capitalized words and far-off names are left alone.
    assert snap_to_vocabulary("Today I will test. Arjun is away.", vocab) == "Today I will test. Arjun is away."
