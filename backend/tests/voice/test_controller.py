"""Conversation controller over the scripted FakeMeetingProvider (plan §8.2, §14 "Voice")."""

import uuid
from datetime import date

from scrum_adapters.meeting.fake import FakeMeetingProvider, ScriptedParticipant
from scrum_adapters.stt import FakeSTT
from scrum_adapters.tts import FakeTTS
from scrum_core.schemas.workflow import MemberCtx, QuestionCtx, StaleBlocker, StandupContext, TicketRef
from scrum_voice.controller import Budget, StandupController
from scrum_voice.judge import HeuristicJudge, summarize
from scrum_voice.pipeline import CallIO
from scrum_voice.transcript import TranscriptWriter


class MemoryWriter(TranscriptWriter):
    async def flush(self) -> None:
        self.count = len(self.all)


def member(name: str, tickets: list[TicketRef] | None = None, stale: list[StaleBlocker] | None = None) -> MemberCtx:
    return MemberCtx(
        user_id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        display_name=name,
        first_name=name.split()[0],
        email=f"{name.split()[0].lower()}@acme.example",
        open_tickets=tickets or [],
        stale_blockers=stale or [],
    )


QUESTIONS = [
    QuestionCtx(
        id=uuid.uuid4(),
        position=1,
        text="What did you complete yesterday?",
        type="ticket_list",
        required=True,
        followup_policy="if_vague",
        max_followups=2,
    ),
    QuestionCtx(
        id=uuid.uuid4(),
        position=2,
        text="What will you work on today?",
        type="ticket_list",
        required=True,
        followup_policy="if_vague",
        max_followups=2,
    ),
    QuestionCtx(
        id=uuid.uuid4(),
        position=3,
        text="Any blockers or dependencies?",
        type="text",
        required=True,
        followup_policy="if_vague",
        max_followups=1,
    ),
]


def ctx(members: list[MemberCtx]) -> StandupContext:
    return StandupContext(
        org_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        team_name="Payments",
        timezone="Asia/Kolkata",
        run_date=date(2026, 11, 10),
        session_id=uuid.uuid4(),
        lead_user_id=uuid.uuid4(),
        lead_email="neha@acme.example",
        lead_name="Neha Kapoor",
        members=members,
        template_id=None,
        questions=QUESTIONS,
        consent_text="This standup is being recorded for notes.",
        async_window_minutes=120,
        join_url="fake://room",
    )


async def run(members, script):
    provider = FakeMeetingProvider(script)
    c = ctx(members)
    call = await provider.join("fake://room", "Scrum Bot")
    io = CallIO(provider, call, FakeSTT(), FakeTTS(), vocabulary=[])
    await io.start()
    writer = MemoryWriter(c.org_id, c.session_id)
    progress = await StandupController(
        c, io, HeuristicJudge(), writer, Budget(900, 60, 180), listen_timeout_s=0.5
    ).run()
    await io.stop()
    return provider, call, writer, progress


async def test_turn_order_follow_up_confirmation_and_tags():
    rahul = member("Rahul Verma", [TicketRef(key="PROJ-142", summary="Refund API", status="In Progress")])
    amit = member("Amit Sharma")
    karan = member("Karan Mehta")
    script = [
        ScriptedParticipant(
            str(rahul.user_id),
            rahul.display_name,
            rahul.email,
            answers=[
                "Stuff.",  # vague → follow-up
                "I finished the refund API main logic for PROJ-142.",
                "Refund API tests for PROJ-142.",
                "I need the sandbox credentials from Amit, so I'm stuck.",
            ],
        ),
        ScriptedParticipant(
            str(amit.user_id),
            amit.display_name,
            amit.email,
            answers=[
                "Fixed staging migration ordering for PROJ-138.",
                "Rotate sandbox credentials, BE-210.",
                "No blockers.",
            ],
        ),
        ScriptedParticipant(str(karan.user_id), karan.display_name, karan.email, present=False),
    ]
    provider, call, writer, progress = await run([rahul, amit, karan], script)

    lines = [(s.speaker_label, s.text) for s in writer.all]
    bot = [t for who, t in lines if who == "Scrum Bot"]
    assert "recorded for notes" in bot[0]  # consent spoken first
    assert len(provider.calls[call.call_id].bot_lines) == len(bot)  # everything said reached the meeting
    assert bot[1].startswith("Rahul, you had PROJ-142, Refund API, in progress.")  # Jira-personalized opener
    assert "Which ticket or task" in bot[2]  # follow-up after the vague answer
    assert any(t.startswith("Thanks, Rahul. Amit,") for t in bot)  # hand-over by name
    confirms = [t for t in bot if t.endswith("Correct?")]
    assert len(confirms) == 2 and "blocker: need the sandbox credentials from Amit" in confirms[0]
    assert "I'll send Karan a quick check-in" in bot[-1]  # absentee mentioned in the outro

    rahul_segs = [s for s in writer.all if s.speaker_user_id == rahul.user_id]
    assert {s.question_id for s in rahul_segs[:2]} == {QUESTIONS[0].id}  # answer + follow-up tagged to Q1
    assert all(s.speaker_confidence == 1.0 for s in rahul_segs)
    starts = [s.start_ms for s in writer.all]
    assert starts == sorted(starts) and starts[-1] > 30_000  # virtual clock advances realistically
    assert set(progress.attended) == {str(rahul.user_id), str(amit.user_id)}


async def test_stale_acknowledged_blocker_prompt_resolves():
    blk = uuid.uuid4()
    meera = member("Meera Das", stale=[StaleBlocker(id=blk, description="Ledger migration needs a DBA window")])
    script = [
        ScriptedParticipant(
            str(meera.user_id),
            meera.display_name,
            meera.email,
            answers=[
                "Ledger migration dry run on BE-219.",
                "I'll work on connection pooling for BE-230.",
                "No blockers.",
                "Yes, it's resolved.",
            ],
        )
    ]
    _, _, writer, progress = await run([meera], script)
    assert any("Is that resolved now?" in s.text for s in writer.all)
    assert progress.resolved_blockers == [str(blk)]


async def test_late_joiner_is_retried_at_the_end():
    a, b = member("Priya Nair"), member("Sneha Joshi")
    script = [
        ScriptedParticipant(
            str(a.user_id),
            a.display_name,
            a.email,
            answers=["Invoice PDF layout PROJ-147.", "Invoice totals PROJ-147.", "None."],
        ),
        ScriptedParticipant(
            str(b.user_id),
            b.display_name,
            b.email,
            joins_after=3,
            answers=["Settlement export PROJ-155.", "Filters PROJ-155.", "No blockers."],
        ),
    ]
    _, _, writer, progress = await run([a, b], script)
    assert any("I see you've joined" in s.text for s in writer.all)
    assert set(progress.attended) == {str(a.user_id), str(b.user_id)}


def test_summary_read_back():
    m = member("Rahul Verma")
    s = summarize(
        m,
        [
            (QUESTIONS[0], "I finished the refund api changes for PROJ-142 and wrote tests."),
            (QUESTIONS[1], "Today I will continue on PROJ-142."),
            (QUESTIONS[2], "No blockers today."),
        ],
    )
    assert s == "done: finished the refund api changes for PROJ-142; today: continue on PROJ-142; no blockers"
