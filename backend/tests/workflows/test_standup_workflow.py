"""E2E story (plan §14, B2.8): Neha's week through the real DailyStandupWorkflow.

Temporal's time-skipping test server runs the workflow; all four worker roles run in-process against
the test database with scripted meetings, the heuristic engine and an in-memory outbox.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from scrum_adapters import registry
from scrum_adapters.mail import MemoryMailAdapter
from scrum_adapters.meeting.fake import FakeMeetingProvider, ScriptedParticipant
from scrum_api.main import create_app
from scrum_core.db import owner_session, session_for, set_org_context
from scrum_core.models import (
    Attendance,
    Blocker,
    Organization,
    Question,
    QuestionTemplate,
    Schedule,
    StandupSession,
    Team,
    TeamMember,
    User,
)
from scrum_core.models.base import AttendanceStatus, BlockerStatus, FollowupPolicy, QuestionType, Role, SessionStatus
from scrum_core.schemas.workflow import (
    BLOCKER_ALERTS_WORKFLOW,
    DEFAULT_QUEUE,
    AsyncCheckinSignal,
    BlockerAlertsInput,
    SendResult,
    StandupInput,
)

pytestmark = [pytest.mark.db, pytest.mark.temporal]

MON, TUE, WED, THU = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)
PEOPLE = {
    "neha": ("Neha Kapoor", Role.scrum_lead, "Payments", []),
    "rahul": ("Rahul Verma", Role.member, "Payments", []),
    "amit": ("Amit Sharma", Role.member, "Backend", ["Amit from backend"]),
    "amits": ("Amit Singh", Role.member, "QA", ["Amit from QA"]),
    "priya": ("Priya Nair", Role.member, "Payments", []),
    "karan": ("Karan Mehta", Role.member, "Payments", []),
    "arjun": ("Arjun Patel", Role.scrum_lead, "Backend", []),
}


class World:
    def __init__(self) -> None:
        self.org = uuid.uuid4()
        self.ids = {k: uuid.uuid4() for k in PEOPLE}
        self.payments = uuid.uuid4()
        self.backend = uuid.uuid4()

    def email(self, k: str) -> str:
        return f"{k}.{self.org.hex[:6]}@acme.example"

    def p(self, k: str, answers: list[str], present: bool = True) -> ScriptedParticipant:
        return ScriptedParticipant(str(self.ids[k]), PEOPLE[k][0], self.email(k), present=present, answers=answers)


async def make_world() -> World:
    w = World()
    async with owner_session() as db:
        db.add(Organization(id=w.org, name="Story Org", escalation_days=3, consent_text="This standup is recorded."))
        await db.flush()
        await set_org_context(db, w.org)
        for k, (name, role, dept, aliases) in PEOPLE.items():
            db.add(
                User(
                    id=w.ids[k],
                    org_id=w.org,
                    idp_subject=f"{k}-{w.org}",
                    email=w.email(k),
                    display_name=name,
                    role=role,
                    department=dept,
                    aliases=aliases,
                )
            )
        await db.flush()
        db.add(Team(id=w.payments, org_id=w.org, name="Payments", lead_user_id=w.ids["neha"], timezone="Asia/Kolkata"))
        db.add(
            Team(
                id=w.backend,
                org_id=w.org,
                name="Backend Platform",
                lead_user_id=w.ids["arjun"],
                timezone="Asia/Kolkata",
            )
        )
        await db.flush()
        for i, k in enumerate(["rahul", "amit", "priya", "karan"]):
            db.add(TeamMember(org_id=w.org, team_id=w.payments, user_id=w.ids[k], speaking_order=i + 1))
        tpl = QuestionTemplate(org_id=w.org, team_id=w.payments, version=1, is_active=True)
        tpl.questions = [
            Question(
                org_id=w.org, position=i + 1, text=t, type=ty, followup_policy=FollowupPolicy.if_vague, max_followups=1
            )
            for i, (t, ty) in enumerate(
                [
                    ("What did you complete yesterday?", QuestionType.ticket_list),
                    ("What will you work on today?", QuestionType.ticket_list),
                    ("Any blockers or dependencies?", QuestionType.text),
                ]
            )
        ]
        db.add(tpl)
        db.add(
            Schedule(
                org_id=w.org,
                team_id=w.payments,
                cron="30 10 * * 1-5",
                timezone="Asia/Kolkata",
                holiday_calendar=None,
                async_window_minutes=120,
                join_url="fake://standup-payments",
            )
        )
    return w


@pytest.fixture(scope="module")
async def env(migrated_db):
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    from scrum_runtime.worker import ROLES, build_workers

    try:
        e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    except Exception as exc:  # pragma: no cover - offline machines
        pytest.skip(f"Temporal test server unavailable: {exc}")
    workers = build_workers(e.client, ROLES)
    tasks = [asyncio.create_task(wk.run()) for wk in workers]
    yield e
    for wk in workers:
        await wk.shutdown()
    for t in tasks:
        t.cancel()
    await e.shutdown()


async def run_day(env, w: World, day: date, script: list[ScriptedParticipant], *, on_checkin_email=None) -> dict:
    registry.override("meeting", FakeMeetingProvider(script))
    handle = await env.client.start_workflow(
        "DailyStandupWorkflow",
        StandupInput(org_id=w.org, team_id=w.payments, run_date=day),
        id=f"standup-{w.payments}-{day}",
        task_queue=DEFAULT_QUEUE,
    )
    if on_checkin_email:
        await on_checkin_email(handle)
    return await handle.result()


def outbox() -> list:
    return registry.mail().outbox  # type: ignore[attr-defined]


def sent_to(kind: str, who: str) -> list:
    return [m for key, m in outbox() if key.startswith(kind) and who in m.to[0]]


async def test_neha_story_week(env):
    registry.override("mail", MemoryMailAdapter())
    w = await make_world()

    # ---- Monday: Priya is blocked on Arjun's review.
    r = await run_day(
        env,
        w,
        MON,
        [
            w.p(
                "rahul",
                ["Refund API request validation for PROJ-142.", "Refund API main logic, PROJ-142.", "No blockers."],
            ),
            w.p("amit", ["Webhook signature validation PROJ-138.", "Deploy PROJ-138 to staging.", "No blockers."]),
            w.p(
                "priya",
                [
                    "Payment UI responsive layout PROJ-150.",
                    "Design feedback on PROJ-150.",
                    "Still waiting for a code review on PROJ-150. Arjun said he'd look at it.",
                ],
            ),
            w.p("karan", ["Payout reconciliation skeleton PROJ-158.", "Matching rules for PROJ-158.", "No blockers."]),
        ],
    )
    assert r["new_blockers"] == 1 and r["alerts_sent"] == 1
    assert len(sent_to("blocker_alert", "arjun")) == 1

    # ---- Tuesday: Rahul blocked on "Amit from backend"; Karan absent → async check-in → blocked on Backend team.
    async def karan_checks_in(handle) -> None:
        for _ in range(200):
            if sent_to("async_checkin", "karan"):
                break
            await asyncio.sleep(0.05)
        assert sent_to("async_checkin", "karan"), "absentee got no check-in email"
        # Karan opens the emailed link and submits the web form (real public API endpoint).
        url = sent_to("async_checkin", "karan")[0].text.split("update: ", 1)[1]
        token = url.split("/a/", 1)[1].split("?", 1)[0]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test/api/v1"
        ) as api:
            preview = (await api.get(f"/actions/{token}")).json()
            q = [x["id"] for x in preview["checkin"]["questions"]]
            r = await api.post(
                f"/async-checkins/{token}",
                json={
                    "answers": {
                        q[0]: "Payout reconciliation matching rules, PROJ-158.",
                        q[1]: "Integrate payouts with the v2 API, PROJ-160.",
                        q[2]: "Waiting on the API contract from the backend team for PROJ-160.",
                    }
                },
            )
            assert r.json() == {"status": "submitted"}
        await handle.signal("submit_async_checkin", AsyncCheckinSignal(user_id=w.ids["karan"]))

    r = await run_day(
        env,
        w,
        TUE,
        [
            w.p(
                "rahul",
                [
                    "I finished the refund API main logic for PROJ-142.",
                    "Refund API tests for PROJ-142.",
                    "I need the sandbox credentials from Amit from backend, so I'm stuck.",
                ],
            ),
            w.p(
                "amit",
                ["Fixed staging migration ordering, PROJ-138.", "Rotate sandbox credentials, BE-210.", "No blockers."],
            ),
            w.p(
                "priya",
                [
                    "Payment UI design feedback PROJ-150.",
                    "Payment UI error states PROJ-150.",
                    "PROJ-150 is still waiting on review.",
                ],
            ),
            w.p("karan", [], present=False),
        ],
        on_checkin_email=karan_checks_in,
    )
    assert r["new_blockers"] == 2  # Rahul's and Karan's; Priya's matched the open one
    assert len(sent_to("blocker_alert", "amit.")) == 1  # Rahul → Amit Sharma (alias), not Amit Singh
    assert sent_to("blocker_alert", "amits.") == []
    assert len(sent_to("blocker_alert", "arjun")) == 2  # Karan's "backend team" → its lead; Priya NOT re-alerted
    async with session_for(w.org) as db:
        att = {
            a.user_id: a.status
            for a in (await db.execute(select(Attendance))).scalars()
            if a.session_id
            == (await db.execute(select(StandupSession.id).where(StandupSession.run_date == TUE))).scalar()
        }
        assert att[w.ids["karan"]] == AttendanceStatus.async_
        karan_blk = (await db.execute(select(Blocker).where(Blocker.reporter_user_id == w.ids["karan"]))).scalar_one()
        assert karan_blk.blocked_on_user_id == w.ids["arjun"] and karan_blk.ticket_keys == ["PROJ-160"]

    # ---- Wednesday & Thursday: Priya repeats; on Thursday (3 standup days) Neha gets an escalation.
    for day in (WED, THU):
        r = await run_day(
            env,
            w,
            day,
            [
                w.p("rahul", ["Refund API tests PROJ-142.", "Refund API docs PROJ-142.", "No blockers."]),
                w.p("amit", ["Sandbox credential rotation BE-210.", "Webhook retry config PROJ-138.", "No blockers."]),
                w.p(
                    "priya",
                    [
                        "Payment UI error states PROJ-150.",
                        "Accessibility pass on PROJ-150.",
                        "Still no review on PROJ-150.",
                    ],
                ),
                w.p("karan", ["Payout API client stub PROJ-160.", "Payout integration PROJ-160.", "No blockers."]),
            ],
        )
        assert r["new_blockers"] == 0 and r["alerts_sent"] == 0
        assert r["escalations"] == (1 if day == THU else 0)
    assert len(sent_to("escalation", "neha")) == 1
    async with session_for(w.org) as db:
        priya_blk = (await db.execute(select(Blocker).where(Blocker.reporter_user_id == w.ids["priya"]))).scalar_one()
        assert priya_blk.days_open == 3 and priya_blk.escalated and priya_blk.status == BlockerStatus.open
        statuses = (await db.execute(select(StandupSession.status))).scalars().all()
        assert set(statuses) == {SessionStatus.delivered}

    # ---- Digests: every team member + lead got one per day; a retried alert job sends nothing new.
    assert len([1 for key, _ in outbox() if key.startswith("digest:")]) == 4 * 5
    before = len(outbox())
    res = await env.client.execute_workflow(
        BLOCKER_ALERTS_WORKFLOW,
        BlockerAlertsInput(org_id=w.org, team_id=w.payments, blocker_ids=[karan_blk.id]),
        id=f"retry-{uuid.uuid4()}",
        task_queue=DEFAULT_QUEUE,
        result_type=SendResult,
    )
    assert (res.sent, res.skipped) == (0, 1) and len(outbox()) == before


async def test_skips_holidays_and_inactive_teams(env):
    registry.override("mail", MemoryMailAdapter())
    w = await make_world()
    async with session_for(w.org) as db:
        sched = (await db.execute(select(Schedule))).scalar_one()
        sched.holiday_calendar = "IN"
    res = await env.client.execute_workflow(
        "DailyStandupWorkflow",
        StandupInput(org_id=w.org, team_id=w.payments, run_date=date(2026, 1, 26)),
        id=f"holiday-{w.org}",
        task_queue=DEFAULT_QUEUE,
    )
    assert "Republic" in res["skipped"]
    assert outbox() == []


async def test_retention_sweeper_deletes_old_transcripts(env):
    from datetime import timedelta

    from scrum_core.models import TranscriptSegment

    w = await make_world()
    async with owner_session() as db:
        await set_org_context(db, w.org)
        org = await db.get(Organization, w.org)
        org.retention_days_transcript = 30
        old = StandupSession(
            org_id=w.org, team_id=w.payments, run_date=date.today() - timedelta(days=45), status=SessionStatus.delivered
        )
        new = StandupSession(
            org_id=w.org, team_id=w.payments, run_date=date.today() - timedelta(days=2), status=SessionStatus.delivered
        )
        db.add_all([old, new])
        await db.flush()
        for s in (old, new):
            db.add(
                TranscriptSegment(
                    org_id=w.org, session_id=s.id, speaker_label="Scrum Bot", start_ms=0, end_ms=1, text="hello"
                )
            )
    totals = await env.client.execute_workflow("RetentionSweepWorkflow", id=f"sweep-{w.org}", task_queue=DEFAULT_QUEUE)
    assert totals["segments"] >= 1
    async with session_for(w.org) as db:
        left = (await db.execute(select(TranscriptSegment.session_id))).scalars().all()
    assert left == [new.id]
