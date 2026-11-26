"""`make seed`: load the "A day with Scrum Bot" world (Neha's Payments team) into PostgreSQL.

Mirrors frontend/mocks/data/*.ts so the UI shows the same story against the real backend:
four weeks of standups for Payments and Backend Platform, the story week's blockers and their
lifecycle (Rahul's sandbox credentials, Priya's review escalated on Thursday, …), review items and
audit history. The story Friday is the most recent Friday on or before today (Asia/Kolkata).

Usage:  uv run python scripts/seed.py [--no-temporal]
Dev sign-in personas (X-Mock-User): u-neha, u-deepa, u-rahul, u-vikram (and every other u-* below).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete

from scrum_adapters import registry
from scrum_core.db import dispose_engines, owner_session, set_org_context
from scrum_core.models import (
    Attendance,
    AuditLog,
    Blocker,
    BlockerEvent,
    BlockerEvidence,
    Integration,
    MemberUpdateRow,
    Notification,
    Organization,
    Question,
    QuestionTemplate,
    Report,
    ReviewItem,
    Schedule,
    StandupSession,
    Team,
    TeamMember,
    TranscriptSegment,
    User,
)
from scrum_core.models.base import (
    AttendanceStatus,
    BlockerEventKind,
    BlockerStatus,
    FollowupPolicy,
    IntegrationKind,
    IntegrationStatus,
    MeetingProviderKind,
    NotificationStatus,
    NotificationType,
    QuestionType,
    ReviewKind,
    Role,
    SessionStatus,
    Severity,
    UpdateSource,
)
from scrum_core.settings import get_settings

TZ = ZoneInfo("Asia/Kolkata")
NS = uuid.UUID("5c7a4e1e-9b1a-4c55-8f0e-5c12ab0b7a11")
ORG_ID = uuid.uuid5(NS, "org-acme")


def sid(slug: str) -> uuid.UUID:
    return uuid.uuid5(NS, slug)


# ------------------------------------------------------------------------------- clock


def story_friday(today: datetime | None = None) -> date:
    d = (today or datetime.now(UTC)).astimezone(TZ).date()
    return d - timedelta(days=(d.weekday() - 4) % 7)


def shift(d: date, days: int) -> date:
    return d + timedelta(days=days)


def at(d: date, hhmm: str, plus_ms: int = 0) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ) + timedelta(milliseconds=plus_ms)


def weekdays(start: date, end: date) -> list[date]:
    return [shift(start, i) for i in range((end - start).days + 1) if shift(start, i).weekday() < 5]


# ------------------------------------------------------------------------------- people

USERS: list[tuple[str, str, Role, str | None, list[str]]] = [
    ("u-deepa", "Deepa Iyer", Role.org_admin, "Engineering Ops", []),
    ("u-neha", "Neha Kapoor", Role.scrum_lead, "Payments", []),
    ("u-rahul", "Rahul Verma", Role.member, "Payments", []),
    ("u-amit", "Amit Sharma", Role.member, "Backend", ["Amit from backend"]),
    ("u-priya", "Priya Nair", Role.member, "Payments", []),
    ("u-karan", "Karan Mehta", Role.member, "Payments", []),
    ("u-sneha", "Sneha Joshi", Role.member, "Payments", []),
    ("u-arjun", "Arjun Patel", Role.scrum_lead, "Backend", []),
    ("u-meera", "Meera Das", Role.member, "Backend", []),
    ("u-amits", "Amit Singh", Role.member, "QA", ["Amit from QA"]),
    ("u-vikram", "Vikram Rao", Role.viewer, "Leadership", []),
]
NAME = {k: n for k, n, *_ in USERS}
EMAIL = {k: f"{n.lower().replace(' ', '.')}@acme.example" for k, n, *_ in USERS}


def first(u: str) -> str:
    return NAME[u].split()[0]


TEAMS = [
    (
        "team-payments",
        "Payments",
        "u-neha",
        "30 10 * * 1-5",
        ["u-rahul", "u-amit", "u-priya", "u-karan", "u-sneha"],
        ["PROJ"],
    ),
    ("team-backend", "Backend Platform", "u-arjun", "0 10 * * 1-5", ["u-amit", "u-meera", "u-amits"], ["BE"]),
]

PAY = [
    ("PROJ-131", "Card tokenization"),
    ("PROJ-134", "UPI retry flow"),
    ("PROJ-136", "Fraud rules engine"),
    ("PROJ-138", "Webhook signature validation"),
    ("PROJ-142", "Refund API"),
    ("PROJ-147", "Invoice PDF"),
    ("PROJ-150", "Payment UI"),
    ("PROJ-152", "Merchant onboarding form"),
    ("PROJ-155", "Settlement report export"),
    ("PROJ-158", "Payout reconciliation"),
]
BE = [
    ("BE-210", "Sandbox credential rotation"),
    ("BE-214", "Rate limiter"),
    ("BE-219", "Ledger service migration"),
    ("BE-223", "Kafka consumer lag alerts"),
    ("BE-227", "API contract v2"),
    ("BE-230", "Postgres connection pooling"),
]


def fnv(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


# ------------------------------------------------------------------------------- day specs


@dataclass
class Item:
    text: str
    tickets: list[str] = field(default_factory=list)


@dataclass
class BSpec:
    text: str
    say: str
    on_raw: str | None
    on_user: str | None
    tickets: list[str]
    severity: str
    confidence: float


@dataclass
class DSpec:
    text: str
    on_raw: str
    on_user: str | None
    on_team: str | None
    tickets: list[str]


@dataclass
class Day:
    user: str
    status: str
    done: list[Item]
    today: list[Item]
    blockers: list[BSpec] = field(default_factory=list)
    deps: list[DSpec] = field(default_factory=list)
    script: list[tuple[str, str, int]] | None = None  # (who, text, q index; -1 = confirmation)


def generic_day(user: str, d: date, team: str, prev: Item | None = None) -> Day:
    """Same hash as frontend/mocks (FNV-1a). Yesterday's plan usually becomes today's done item, so
    carry-over metrics are realistic (~1 in 4 plans slip)."""
    pool = PAY if team == "team-payments" else BE
    h = fnv(f"{user}-{d.isoformat()}")
    a, b = pool[h % len(pool)], pool[(h >> 3) % len(pool)]
    status = "absent" if h % 29 == 0 else "async" if h % 13 == 0 else "present"
    verbs = ["Implemented", "Wrapped up", "Fixed edge cases in", "Wrote tests for", "Reviewed PRs for"]
    plans = ["Continue", "Start on", "Pair on", "Polish", "Ship"]
    if prev and prev.tickets and h % 4 != 0:
        a = next((t for t in pool if t[0] == prev.tickets[0]), a)
    return Day(
        user,
        status,
        [Item(f"{verbs[h % len(verbs)]} {a[1]}", [a[0]])],
        [Item(f"{plans[(h >> 5) % len(plans)]} {b[1]}", [b[0]])],
    )


def story_week(fri: date) -> dict[date, list[Day]]:
    mon, tue, wed, thu = (shift(fri, -4), shift(fri, -3), shift(fri, -2), shift(fri, -1))

    def priya(say: str = "Still waiting for a code review on PROJ-150. Arjun said he'd look at it.") -> BSpec:
        return BSpec("Waiting on code review for the Payment UI", say, "Arjun", "u-arjun", ["PROJ-150"], "medium", 0.93)

    return {
        mon: [
            Day(
                "u-rahul",
                "present",
                [Item("Refund API request validation", ["PROJ-142"])],
                [Item("Refund API main logic", ["PROJ-142"])],
            ),
            Day(
                "u-amit",
                "present",
                [Item("Webhook signature validation", ["PROJ-138"])],
                [Item("Deploy webhook validation to staging", ["PROJ-138"])],
                blockers=[
                    BSpec(
                        "Staging DB migrations failing, blocks deploy",
                        "Staging migrations are failing, so I can't deploy PROJ-138. DevOps is looking at it.",
                        "DevOps",
                        None,
                        ["PROJ-138"],
                        "high",
                        0.9,
                    )
                ],
            ),
            Day(
                "u-priya",
                "present",
                [Item("Payment UI responsive layout", ["PROJ-150"])],
                [Item("Address design feedback on Payment UI", ["PROJ-150"])],
                blockers=[priya()],
            ),
            Day(
                "u-karan",
                "present",
                [Item("Payout reconciliation job skeleton", ["PROJ-158"])],
                [Item("Payout reconciliation matching rules", ["PROJ-158"])],
            ),
            Day(
                "u-sneha",
                "present",
                [Item("Settlement report query", ["PROJ-155"])],
                [Item("Settlement report CSV export", ["PROJ-155"])],
            ),
        ],
        tue: [
            Day(
                "u-rahul",
                "present",
                [Item("Refund API main logic", ["PROJ-142"])],
                [Item("Finish refund API tests once credentials arrive", ["PROJ-142"])],
                blockers=[
                    BSpec(
                        "Needs sandbox credentials to test the refund API",
                        "I need the sandbox credentials from Amit, so I'm stuck.",
                        "Amit from backend",
                        "u-amit",
                        ["PROJ-142"],
                        "high",
                        0.95,
                    )
                ],
                script=[
                    ("bot", "Rahul, yesterday you were working on PROJ-142, the refund API. How did that go?", 0),
                    ("member", "I finished the main logic, but the testing isn't done.", 0),
                    ("bot", "Got it. Will testing finish today, or is anything stopping it?", 2),
                    ("member", "I need the sandbox credentials from Amit, so I'm stuck.", 2),
                    ("bot", "What's your plan for today?", 1),
                    ("member", "Finish the refund API tests as soon as I have the credentials.", 1),
                    (
                        "bot",
                        "So: refund logic done, testing pending, blocked on sandbox credentials from Amit. Correct?",
                        -1,
                    ),
                    ("member", "Yes.", -1),
                ],
            ),
            Day(
                "u-amit",
                "present",
                [Item("Fixed staging migration ordering", ["PROJ-138"])],
                [Item("Rotate sandbox credentials", ["BE-210"])],
            ),
            Day(
                "u-priya",
                "present",
                [Item("Payment UI design feedback", ["PROJ-150"])],
                [Item("Payment UI error states", ["PROJ-150"])],
                blockers=[priya("PROJ-150 is still waiting on review.")],
            ),
            Day(
                "u-karan",
                "async",
                [Item("Payout reconciliation matching rules", ["PROJ-158"])],
                [Item("Integrate payouts with the v2 API", ["PROJ-160"])],
                blockers=[
                    BSpec(
                        "Waiting on the v2 API contract from Backend Platform",
                        "Waiting on the API contract from the backend team for PROJ-160.",
                        "Backend team",
                        "u-arjun",
                        ["PROJ-160"],
                        "medium",
                        0.88,
                    )
                ],
            ),
            Day(
                "u-sneha",
                "present",
                [Item("Settlement report CSV export", ["PROJ-155"])],
                [Item("Settlement report filters", ["PROJ-155"])],
                deps=[DSpec("Settlement schema sign-off", "Meera", "u-meera", "team-backend", ["PROJ-155"])],
            ),
        ],
        wed: [
            Day(
                "u-rahul",
                "present",
                [Item("Refund API tests", ["PROJ-142"])],
                [Item("Refund API docs and handoff", ["PROJ-142"])],
            ),
            Day(
                "u-amit",
                "present",
                [Item("Sandbox credential rotation", ["BE-210"])],
                [Item("Webhook retry configuration", ["PROJ-138"])],
            ),
            Day(
                "u-priya",
                "present",
                [Item("Payment UI error states", ["PROJ-150"])],
                [Item("Payment UI accessibility pass", ["PROJ-150"])],
                blockers=[priya("Still no review on PROJ-150.")],
            ),
            Day(
                "u-karan",
                "present",
                [Item("Payout API client stub", ["PROJ-160"])],
                [Item("Payout integration against the v2 contract", ["PROJ-160"])],
            ),
            Day("u-sneha", "absent", [], []),
        ],
        thu: [
            Day(
                "u-rahul",
                "present",
                [Item("Refund API docs", ["PROJ-142"])],
                [Item("Webhook retry integration", ["PROJ-138"])],
                deps=[DSpec("Webhook retry config", "Amit", None, None, ["PROJ-138"])],
            ),
            Day(
                "u-amit",
                "present",
                [Item("Webhook retry configuration", ["PROJ-138"])],
                [Item("Rate limiter rollout", ["BE-214"])],
            ),
            Day(
                "u-priya",
                "present",
                [Item("Payment UI accessibility pass", ["PROJ-150"])],
                [Item("Start Invoice PDF", ["PROJ-147"])],
                blockers=[priya("I'm still waiting for the code review on PROJ-150.")],
            ),
            Day(
                "u-karan",
                "present",
                [Item("Payout integration", ["PROJ-160"])],
                [Item("Payout reconciliation tests", ["PROJ-158"])],
            ),
            Day(
                "u-sneha",
                "present",
                [Item("Settlement report export", ["PROJ-155"])],
                [Item("Merchant onboarding form validation", ["PROJ-152"])],
            ),
        ],
        fri: [
            Day(
                "u-rahul",
                "present",
                [Item("Webhook retry integration", ["PROJ-138"])],
                [Item("Refund API load test", ["PROJ-142"])],
            ),
            Day(
                "u-amit",
                "present",
                [Item("Rate limiter rollout", ["BE-214"])],
                [Item("Ledger migration dry run", ["BE-219"])],
            ),
            Day(
                "u-priya",
                "present",
                [Item("Invoice PDF layout", ["PROJ-147"])],
                [Item("Invoice PDF totals", ["PROJ-147"])],
                blockers=[priya("PROJ-150 review is still pending.")],
            ),
            Day(
                "u-karan",
                "present",
                [Item("Payout reconciliation tests", ["PROJ-158"])],
                [Item("Payout dashboard", ["PROJ-158"])],
            ),
            Day(
                "u-sneha",
                "present",
                [Item("Merchant onboarding form validation", ["PROJ-152"])],
                [Item("Merchant onboarding API wiring", ["PROJ-152"])],
            ),
        ],
    }


def join_items(items: list[Item]) -> str:
    return ", and ".join(i.text[:1].lower() + i.text[1:] for i in items)


def default_script(d: Day) -> list[tuple[str, str, int]]:
    name = first(d.user)
    last = d.done[0].tickets[0] if d.done and d.done[0].tickets else None
    opener = (
        f"{name}, you had {last} in progress. How did yesterday go?"
        if last
        else f"{name}, what did you complete yesterday?"
    )
    if d.blockers:
        blocker_answer = " ".join(b.say for b in d.blockers)
    elif d.deps:
        blocker_answer = f"No blockers, but I depend on {d.deps[0].on_raw} for {d.deps[0].text.lower()}."
    else:
        blocker_answer = "No blockers today."
    bits = [
        f"{', '.join(x.tickets[0] if x.tickets else x.text for x in d.done)} done" if d.done else None,
        f"today {d.today[0].text.lower()}" if d.today else None,
        f"blocked on {d.blockers[0].on_raw or 'an external dependency'}" if d.blockers else "no blockers",
    ]
    return [
        ("bot", opener, 0),
        ("member", f"I finished {join_items(d.done)}." if d.done else "Mostly reviews and meetings yesterday.", 0),
        ("bot", "What will you work on today?", 1),
        ("member", f"Today I'll {join_items(d.today)}.", 1),
        ("bot", "Any blockers or dependencies?", 2),
        ("member", blocker_answer, 2),
        ("bot", f"So: {'; '.join(b for b in bits if b)}. Correct?", -1),
        ("member", "Yes, that's right.", -1),
    ]


def speech_ms(text: str) -> int:
    return min(9000, max(1600, len(text) * 62))


@dataclass
class Built:
    segments: list[dict[str, Any]]
    attendance: list[dict[str, Any]]
    updates: list[dict[str, Any]]
    started: datetime
    ended: datetime
    evidence: dict[str, dict[int, list[uuid.UUID]]]


def build_standup(session_slug: str, d: date, start: str, qids: list[uuid.UUID], days: list[Day]) -> Built:
    segs: list[dict[str, Any]] = []
    evidence: dict[str, dict[int, list[uuid.UUID]]] = {}
    t, n = 4000, 0

    def push(user: str | None, text: str, q: int) -> uuid.UUID:
        nonlocal t, n
        n += 1
        dur = speech_ms(text)
        seg_id = sid(f"seg-{session_slug}-{n}")
        segs.append(
            {
                "id": seg_id,
                "speaker_user_id": sid(user) if user else None,
                "speaker_label": NAME[user] if user else "Scrum Bot",
                "question_id": qids[q] if 0 <= q < len(qids) else None,
                "start_ms": t,
                "end_ms": t + dur,
                "text": text,
                "confidence": (0.86 + ((n * 7) % 12) / 100) if user else 1.0,
            }
        )
        t += dur + 700
        return seg_id

    present = [x for x in days if x.status == "present"]
    absent = [first(x.user) for x in days if x.status != "present"]
    push(
        None,
        "Good morning, everyone! This standup is being recorded for notes. "
        + (f"Let's start with {first(present[0].user)}." if present else ""),
        -1,
    )
    for i, day in enumerate(present):
        evidence[day.user] = {}
        for who, text, q in day.script or default_script(day):
            member = who == "member"
            seg_id = push(day.user if member else None, text, q)
            if member:
                evidence[day.user].setdefault(q, []).append(seg_id)
        if i + 1 < len(present):
            push(None, f"Thanks, {first(day.user)}. {first(present[i + 1].user)}, your turn.", -1)
    push(
        None,
        "Thanks, everyone. "
        + (f"I'll send {' and '.join(absent)} a quick check-in. " if absent else "")
        + "Have a productive day!",
        -1,
    )

    started = at(d, start)
    attendance = [
        {
            "user": x.user,
            "status": x.status,
            "joined_at": at(d, start, 1000 * ((len(x.user) * 13) % 50)) if x.status == "present" else None,
        }
        for x in days
    ]
    updates = []
    for x in days:
        if x.status == "absent":
            continue
        ev = evidence.get(x.user, {})

        def item(s: Item, status: str, q: int, ev: dict[int, list[uuid.UUID]] = ev) -> dict[str, Any]:
            return {
                "summary": s.text,
                "ticket_keys": s.tickets,
                "status": status,
                "evidence_segment_ids": [str(e) for e in ev.get(q, [])],
            }

        updates.append(
            {
                "user": x.user,
                "source": "async" if x.status == "async" else "voice",
                "payload": {
                    "member_id": str(sid(x.user)),
                    "completed": [item(s, "done", 0) for s in x.done],
                    "planned": [item(s, "planned", 1) for s in x.today],
                    "blockers": [
                        {
                            "description": b.text,
                            "blocked_on_raw": b.on_raw,
                            "blocked_on_member_id": str(sid(b.on_user)) if b.on_user else None,
                            "ticket_keys": b.tickets,
                            "severity": b.severity,
                            "confidence": b.confidence,
                            "evidence_segment_ids": [str(e) for e in ev.get(2, [])],
                        }
                        for b in x.blockers
                    ],
                    "dependencies": [
                        {
                            "description": dp.text,
                            "on_raw": dp.on_raw,
                            "on_member_id": str(sid(dp.on_user)) if dp.on_user else None,
                            "on_team_id": str(sid(dp.on_team)) if dp.on_team else None,
                            "ticket_keys": dp.tickets,
                            "evidence_segment_ids": [str(e) for e in ev.get(2, [])],
                        }
                        for dp in x.deps
                    ],
                    "challenges": [],
                    "answers": {},
                },
            }
        )
    return Built(segs, attendance, updates, started, started + timedelta(milliseconds=t), evidence)


def questions_for(
    team: str, version: int, followup: FollowupPolicy
) -> list[tuple[uuid.UUID, int, str, QuestionType, FollowupPolicy, int]]:
    texts = [
        ("What did you complete yesterday?", QuestionType.ticket_list),
        ("What will you work on today?", QuestionType.ticket_list),
        ("Any blockers or dependencies?", QuestionType.text),
    ]
    return [
        (
            sid(f"q-{team}-v{version}-{i + 1}"),
            i + 1,
            txt,
            typ,
            FollowupPolicy.if_vague if i == 2 else followup,
            0 if followup == FollowupPolicy.none and i != 2 else 2,
        )
        for i, (txt, typ) in enumerate(texts)
    ]


# ------------------------------------------------------------------------------- main


async def seed(with_temporal: bool) -> None:
    s = get_settings()
    fri = story_friday()
    mon, tue, wed, thu = shift(fri, -4), shift(fri, -3), shift(fri, -2), shift(fri, -1)
    story = story_week(fri)
    emb = registry.embedder()

    async with owner_session() as db:
        await set_org_context(db, ORG_ID)
        await db.execute(delete(AuditLog).where(AuditLog.org_id == ORG_ID))
        await db.execute(delete(Organization).where(Organization.id == ORG_ID))
        await db.flush()

        db.add(
            Organization(
                id=ORG_ID,
                name="Acme Payments Pvt Ltd",
                onboarded_at=at(shift(fri, -40), "09:30"),
                consent_text="This standup is being recorded for notes.",
                retention_days_audio=0,
                retention_days_transcript=90,
                escalation_days=3,
                settings={"pm_writeback_enabled": True},
            )
        )
        await db.flush()
        for key, name, role, dept, aliases in USERS:
            db.add(
                User(
                    id=sid(key),
                    org_id=ORG_ID,
                    idp_subject=key,
                    email=EMAIL[key],
                    display_name=name,
                    aliases=aliases,
                    department=dept,
                    role=role,
                )
            )
        await db.flush()

        provider = MeetingProviderKind.livekit if s.meeting_provider == "livekit" else MeetingProviderKind.fake
        for tslug, tname, lead, cron, members, keys in TEAMS:
            tid = sid(tslug)
            db.add(
                Team(
                    id=tid,
                    org_id=ORG_ID,
                    name=tname,
                    lead_user_id=sid(lead),
                    timezone="Asia/Kolkata",
                    meeting_provider=provider,
                    active=True,
                    pm_board_id="1" if tslug == "team-payments" else "2",
                    pm_project_keys=keys,
                )
            )
            await db.flush()
            for i, m in enumerate(members):
                db.add(
                    TeamMember(
                        org_id=ORG_ID, team_id=tid, user_id=sid(m), speaking_order=i + 1, pm_account_id=f"jira-{m[2:]}"
                    )
                )
            versions = [(1, FollowupPolicy.none, tslug != "team-payments", lead, shift(fri, -40))]
            if tslug == "team-payments":
                versions.append((2, FollowupPolicy.if_vague, True, "u-neha", shift(fri, -30)))
            for v, policy, active, author, when in versions:
                tpl = QuestionTemplate(
                    id=sid(f"tpl-{tslug}-v{v}"),
                    org_id=ORG_ID,
                    team_id=tid,
                    version=v,
                    is_active=active,
                    created_by=sid(author),
                )
                tpl.questions = [
                    Question(
                        id=qid,
                        org_id=ORG_ID,
                        position=pos,
                        text=txt,
                        type=typ,
                        required=True,
                        followup_policy=pol,
                        max_followups=mx,
                    )
                    for qid, pos, txt, typ, pol, mx in questions_for(tslug, v, policy)
                ]
                db.add(tpl)
                await db.flush()
                tpl.created_at = at(when, "10:00")
            room = f"standup-{tid}"
            db.add(
                Schedule(
                    org_id=ORG_ID,
                    team_id=tid,
                    cron=cron,
                    timezone="Asia/Kolkata",
                    holiday_calendar="IN",
                    skip_dates=[shift(fri, 13)],
                    async_window_minutes=120,
                    lead_minutes=5,
                    paused=False,
                    recurring_meeting_id=room,
                    join_url=s.meeting_join_url_template.format(room=room),
                    temporal_schedule_id=f"standup-{tid}",
                )
            )
        await db.flush()

        integ = [
            (
                IntegrationKind.teams,
                IntegrationStatus.connected,
                "Meetings (LiveKit)" if provider == MeetingProviderKind.livekit else "Meetings (demo provider)",
                "Scripted demo meetings · LiveKit-ready",
            ),
            (
                IntegrationKind.jira,
                IntegrationStatus.connected,
                "Jira (demo catalog)",
                "Demo ticket catalog · PROJ, BE",
            ),
            (
                IntegrationKind.mail,
                IntegrationStatus.connected,
                "Email (SMTP)",
                f"SMTP {s.smtp_host}:{s.smtp_port} · from {s.mail_from}",
            ),
            (IntegrationKind.ado, IntegrationStatus.disconnected, "Azure DevOps", "Not connected"),
        ]
        for kind, status, label, detail in integ:
            db.add(
                Integration(
                    org_id=ORG_ID,
                    kind=kind,
                    status=status,
                    display_name=label,
                    detail=detail,
                    last_checked_at=at(fri, "09:00") if status != IntegrationStatus.disconnected else None,
                )
            )

        # ---------------- sessions: four weeks of weekdays
        dates = weekdays(shift(fri, -25), fri)
        session_ids: dict[tuple[str, date], uuid.UUID] = {}
        segments_by_session: dict[uuid.UUID, list[dict[str, Any]]] = {}
        viewers = [k for k, _, r, *_ in USERS if r == Role.viewer]
        for tslug, tname, lead, cron, members, _keys in TEAMS:
            tid = sid(tslug)
            version = 2 if tslug == "team-payments" else 1
            tpl_id = sid(f"tpl-{tslug}-v{version}")
            qids = [q[0] for q in questions_for(tslug, version, FollowupPolicy.if_vague)]
            start = "10:30" if cron.startswith("30 10") else "10:00"
            prev_plan: dict[str, Item] = {}
            for d in dates:
                days = (
                    story[d]
                    if tslug == "team-payments" and d in story
                    else [generic_day(m, d, tslug, prev_plan.get(m)) for m in members]
                )
                prev_plan.update({x.user: x.today[0] for x in days if x.today})
                slug = f"ses-{tslug.removeprefix('team-')}-{d.isoformat()}"
                ses_id = sid(slug)
                session_ids[(tslug, d)] = ses_id
                b = build_standup(slug, d, start, qids, days)
                db.add(
                    StandupSession(
                        id=ses_id,
                        org_id=ORG_ID,
                        team_id=tid,
                        run_date=d,
                        template_id=tpl_id,
                        status=SessionStatus.delivered,
                        workflow_id=f"standup-{tid}-{d}",
                        started_at=b.started,
                        ended_at=b.ended,
                    )
                )
                await db.flush()
                for a in b.attendance:
                    db.add(
                        Attendance(
                            org_id=ORG_ID,
                            session_id=ses_id,
                            user_id=sid(a["user"]),
                            status=AttendanceStatus(a["status"]),
                            joined_at=a["joined_at"],
                        )
                    )
                db.add_all([TranscriptSegment(org_id=ORG_ID, session_id=ses_id, **seg) for seg in b.segments])
                for u in b.updates:
                    db.add(
                        MemberUpdateRow(
                            org_id=ORG_ID,
                            session_id=ses_id,
                            user_id=sid(u["user"]),
                            source=UpdateSource(u["source"]),
                            payload=u["payload"],
                            extraction_model="seed",
                            version=1,
                        )
                    )
                sent = b.ended + timedelta(minutes=8)
                for r in dict.fromkeys([lead, *members, *viewers]):
                    db.add(
                        Notification(
                            org_id=ORG_ID,
                            idempotency_key=f"digest:{ses_id}:{EMAIL[r]}",
                            session_id=ses_id,
                            recipient=EMAIL[r],
                            type=NotificationType.digest,
                            status=NotificationStatus.sent,
                            subject=f"{tname} standup",
                            sent_at=sent,
                            provider_message_id=f"<seed-{ses_id}-{r}@scrumbot>",
                        )
                    )
                segments_by_session[ses_id] = b.segments
        await db.flush()

        # ---------------- blockers (lifecycle as of Friday)
        def ev(d: date, user: str, team: str = "team-payments") -> list[uuid.UUID]:
            ses = session_ids[(team, d)]
            q3 = sid(f"q-{team}-v{2 if team == 'team-payments' else 1}-3")
            return [
                x["id"]
                for x in segments_by_session[ses]
                if x["speaker_user_id"] == sid(user) and x["question_id"] == q3
            ]

        def ses(d: date, team: str = "team-payments") -> uuid.UUID:
            return session_ids[(team, d)]

        blockers: list[dict[str, Any]] = [
            dict(
                slug="blk-rahul-sandbox",
                team="team-payments",
                desc="Needs sandbox credentials to test the refund API",
                reporter="u-rahul",
                on="u-amit",
                raw="Amit from backend",
                tickets=["PROJ-142"],
                sev="high",
                status=BlockerStatus.resolved,
                days=0,
                esc=False,
                first=at(tue, "10:33"),
                resolved=at(tue, "15:20"),
                fs=ses(tue),
                events=[
                    (at(tue, "10:33"), "raised", "Rahul Verma", "Raised in standup", ses(tue)),
                    (
                        at(tue, "10:50"),
                        "alert_sent",
                        "Scrum Bot",
                        "Alert emailed to Amit Sharma (cc Rahul, Neha)",
                        ses(tue),
                    ),
                    (at(tue, "15:20"), "resolved", "Amit Sharma", "Marked resolved from email link", None),
                ],
                evidence=ev(tue, "u-rahul"),
            ),
            dict(
                slug="blk-priya-review",
                team="team-payments",
                desc="Waiting on code review for the Payment UI",
                reporter="u-priya",
                on="u-arjun",
                raw="Arjun",
                tickets=["PROJ-150"],
                sev="medium",
                status=BlockerStatus.open,
                days=4,
                esc=True,
                first=at(mon, "10:36"),
                resolved=None,
                fs=ses(mon),
                events=[
                    (at(mon, "10:36"), "raised", "Priya Nair", "Raised in standup", ses(mon)),
                    (
                        at(mon, "10:52"),
                        "alert_sent",
                        "Scrum Bot",
                        "Alert emailed to Arjun Patel (cc Priya, Neha)",
                        ses(mon),
                    ),
                    (
                        at(tue, "10:37"),
                        "mentioned",
                        "Priya Nair",
                        "Matched to existing blocker (PROJ-150, 0.94)",
                        ses(tue),
                    ),
                    (
                        at(wed, "10:37"),
                        "mentioned",
                        "Priya Nair",
                        "Matched to existing blocker (PROJ-150, 0.92)",
                        ses(wed),
                    ),
                    (
                        at(thu, "10:38"),
                        "mentioned",
                        "Priya Nair",
                        "Matched to existing blocker — no repeat alert",
                        ses(thu),
                    ),
                    (
                        at(thu, "10:51"),
                        "escalated",
                        "Scrum Bot",
                        "Open for 3 days — escalated to Neha Kapoor",
                        ses(thu),
                    ),
                    (at(fri, "10:38"), "mentioned", "Priya Nair", "Matched to existing blocker", ses(fri)),
                ],
                evidence=[*ev(mon, "u-priya"), *ev(thu, "u-priya")],
            ),
            dict(
                slug="blk-karan-contract",
                team="team-payments",
                desc="Waiting on the v2 API contract from Backend Platform",
                reporter="u-karan",
                on="u-arjun",
                raw="Backend team",
                tickets=["PROJ-160"],
                sev="medium",
                status=BlockerStatus.resolved,
                days=0,
                esc=False,
                first=at(tue, "11:15"),
                resolved=at(wed, "13:40"),
                fs=ses(tue),
                events=[
                    (at(tue, "11:15"), "raised", "Karan Mehta", "Raised via async check-in", ses(tue)),
                    (at(tue, "11:20"), "alert_sent", "Scrum Bot", "Alert emailed to Arjun Patel", ses(tue)),
                    (at(tue, "14:05"), "acknowledged", "Arjun Patel", None, None),
                    (at(wed, "13:40"), "resolved", "Arjun Patel", "Contract published (BE-227)", None),
                ],
                evidence=[],
            ),
            dict(
                slug="blk-amit-staging",
                team="team-payments",
                desc="Staging DB migrations failing, blocks deploy",
                reporter="u-amit",
                on=None,
                raw="DevOps",
                tickets=["PROJ-138"],
                sev="high",
                status=BlockerStatus.resolved,
                days=0,
                esc=False,
                first=at(mon, "10:34"),
                resolved=at(wed, "17:50"),
                fs=ses(mon),
                events=[
                    (at(mon, "10:34"), "raised", "Amit Sharma", "Raised in standup", ses(mon)),
                    (at(wed, "17:50"), "resolved", "Neha Kapoor", "Resolved from blockers board", None),
                ],
                evidence=ev(mon, "u-amit"),
            ),
            dict(
                slug="blk-meera-ledger",
                team="team-backend",
                desc="Ledger migration needs a DBA maintenance window",
                reporter="u-meera",
                on=None,
                raw="DBA team",
                tickets=["BE-219"],
                sev="medium",
                status=BlockerStatus.acknowledged,
                days=2,
                esc=False,
                first=at(wed, "10:06"),
                resolved=None,
                fs=ses(wed, "team-backend"),
                events=[
                    (at(wed, "10:06"), "raised", "Meera Das", "Raised in standup", ses(wed, "team-backend")),
                    (at(wed, "12:00"), "acknowledged", "Arjun Patel", None, None),
                ],
                evidence=[],
            ),
            dict(
                slug="blk-meera-staging",
                team="team-backend",
                desc="Staging has been flaky again since this morning's deploy",
                reporter="u-meera",
                on=None,
                raw="staging is flaky again",
                tickets=[],
                sev="medium",
                status=BlockerStatus.needs_review,
                days=0,
                esc=False,
                first=at(fri, "10:14"),
                resolved=None,
                fs=ses(fri, "team-backend"),
                events=[
                    (
                        at(fri, "10:14"),
                        "raised",
                        "Meera Das",
                        "Raised in standup — possible repeat, sent for review",
                        ses(fri, "team-backend"),
                    )
                ],
                evidence=[],
            ),
        ]
        for i, (text, who, raw, tick, dur) in enumerate(
            [
                ("Merchant KYC API timeouts", "u-sneha", "Partner team", "PROJ-152", 1.2),
                ("Waiting on design for invoice PDF", "u-priya", "Design", "PROJ-147", 1.8),
                ("Flaky payment gateway sandbox", "u-rahul", "Gateway vendor", "PROJ-131", 1.8),
            ]
        ):
            start_d = shift(fri, -11 + i)
            first_at = at(start_d, "10:40")
            blockers.append(
                dict(
                    slug=f"blk-hist-{i}",
                    team="team-payments",
                    desc=text,
                    reporter=who,
                    on=None,
                    raw=raw,
                    tickets=[tick],
                    sev="low",
                    status=BlockerStatus.resolved,
                    days=0,
                    esc=False,
                    first=first_at,
                    resolved=first_at + timedelta(days=dur),
                    fs=ses(start_d),
                    events=[(first_at, "raised", None, None, ses(start_d))],
                    evidence=[],
                )
            )

        vectors = await emb.embed([f"{b['desc']} {' '.join(b['tickets'])}" for b in blockers])
        for b, vec in zip(blockers, vectors, strict=True):
            bid = sid(b["slug"])
            db.add(
                Blocker(
                    id=bid,
                    org_id=ORG_ID,
                    team_id=sid(b["team"]),
                    reporter_user_id=sid(b["reporter"]),
                    blocked_on_user_id=sid(b["on"]) if b["on"] else None,
                    blocked_on_raw=b["raw"],
                    description=b["desc"],
                    ticket_keys=b["tickets"],
                    severity=Severity(b["sev"]),
                    status=b["status"],
                    first_seen_session_id=b["fs"],
                    last_seen_session_id=b["events"][-1][4] or b["fs"],
                    first_seen_at=b["first"],
                    last_seen_at=b["events"][-1][0],
                    days_open=b["days"],
                    escalated=b["esc"],
                    embedding=vec,
                    resolved_at=b["resolved"],
                    alert_held=b["status"] == BlockerStatus.needs_review,
                    acknowledged_at=next((e[0] for e in b["events"] if e[1] == "acknowledged"), None),
                )
            )
            await db.flush()
            for when, kind, actor, note, s_id in b["events"]:
                db.add(
                    BlockerEvent(
                        org_id=ORG_ID,
                        blocker_id=bid,
                        at=when,
                        kind=BlockerEventKind(kind),
                        actor_name=actor,
                        note=note,
                        session_id=s_id,
                    )
                )
            for seg in dict.fromkeys(b["evidence"]):
                db.add(BlockerEvidence(org_id=ORG_ID, blocker_id=bid, segment_id=seg))
            # Link the extracted blocker in the member update to its lifecycle row (as the pipeline does).
        await db.flush()

        # ---------------- review queue
        thu_rahul = next(
            (
                x
                for x in segments_by_session[ses(thu)]
                if x["speaker_user_id"] == sid("u-rahul") and "Amit" in x["text"]
            ),
            None,
        )
        reviews = [
            (
                ReviewKind.person_match,
                "team-payments",
                ses(thu),
                0.74,
                "Amit",
                thu_rahul["text"] if thu_rahul else "No blockers, but I depend on Amit for webhook retry config.",
                "Rahul Verma",
                [
                    {
                        "id": str(sid("u-amit")),
                        "label": "Amit Sharma",
                        "sublabel": "Backend · works on PROJ-138",
                        "confidence": 0.74,
                    },
                    {"id": str(sid("u-amits")), "label": "Amit Singh", "sublabel": "QA", "confidence": 0.61},
                ],
                {},
                at(thu, "10:46"),
                "rev-person-amit",
            ),
            (
                ReviewKind.blocker_match,
                "team-backend",
                ses(fri, "team-backend"),
                0.84,
                "staging is flaky again",
                "Staging has been flaky again since this morning's deploy.",
                "Meera Das",
                [
                    {
                        "id": str(sid("blk-amit-staging")),
                        "label": "Staging DB migrations failing, blocks deploy",
                        "sublabel": "Payments · resolved Wed",
                        "confidence": 0.84,
                    },
                    {"id": "new", "label": "Create as a new blocker", "sublabel": None, "confidence": 0.16},
                ],
                {"new_blocker_id": str(sid("blk-meera-staging"))},
                at(fri, "10:16"),
                "rev-blocker-staging",
            ),
            (
                ReviewKind.pm_writeback,
                "team-payments",
                ses(wed),
                0.9,
                "Refund API tests done",
                "I finished refund API tests.",
                "Rahul Verma",
                [
                    {
                        "id": "transition-done",
                        "label": "Transition PROJ-142 → Done",
                        "sublabel": "Jira currently: In Review",
                        "confidence": 0.9,
                    }
                ],
                {"ticket_key": "PROJ-142", "transition_to": "Done"},
                at(wed, "10:47"),
                "rev-pm-142",
            ),
        ]
        for kind, team, s_id, conf, raw, quote, speaker, cands, ctx, created, slug in reviews:
            r = ReviewItem(
                id=sid(slug),
                org_id=ORG_ID,
                kind=kind,
                team_id=sid(team),
                session_id=s_id,
                confidence=conf,
                dedupe_key=slug,
                payload={
                    "raw_phrase": raw,
                    "evidence_quote": quote,
                    "evidence_speaker": speaker,
                    "candidates": cands,
                    "context": ctx,
                },
            )
            db.add(r)
            await db.flush()
            r.created_at = created

        # ---------------- audit history
        audit = [
            (
                at(shift(fri, -40), "09:58"),
                "u-deepa",
                "integration.connected",
                "integration",
                "teams",
                {"kind": "teams"},
            ),
            (at(shift(fri, -40), "10:02"), "u-deepa", "integration.connected", "integration", "jira", {"kind": "jira"}),
            (
                at(shift(fri, -40), "10:05"),
                "u-neha",
                "team.created",
                "team",
                str(sid("team-payments")),
                {"name": "Payments", "timezone": "Asia/Kolkata"},
            ),
            (
                at(shift(fri, -40), "10:08"),
                "u-neha",
                "schedule.updated",
                "schedule",
                str(sid("team-payments")),
                {"cron": [None, "30 10 * * 1-5"]},
            ),
            (
                at(shift(fri, -30), "16:20"),
                "u-neha",
                "template.created",
                "question_template",
                str(sid("tpl-team-payments-v2")),
                {"version": 2, "followup_policy": ["none", "if_vague"]},
            ),
            (at(tue, "10:50"), None, "mail.sent", "notification", str(ses(tue)), {"type": "digest", "recipients": 7}),
            (
                at(tue, "10:50"),
                None,
                "mail.sent",
                "notification",
                str(sid("blk-rahul-sandbox")),
                {"type": "blocker_alert", "to": EMAIL["u-amit"]},
            ),
            (
                at(tue, "15:20"),
                "u-amit",
                "blocker.resolved",
                "blocker",
                str(sid("blk-rahul-sandbox")),
                {"status": ["open", "resolved"], "via": "email_link"},
            ),
            (
                at(thu, "10:51"),
                None,
                "mail.sent",
                "notification",
                str(sid("blk-priya-review")),
                {"type": "escalation", "to": EMAIL["u-neha"]},
            ),
            (at(fri, "10:50"), None, "mail.sent", "notification", str(ses(fri)), {"type": "digest", "recipients": 7}),
        ]
        for when, actor, action, etype, eid, diff in audit:
            db.add(
                AuditLog(
                    org_id=ORG_ID,
                    at=when,
                    actor_user_id=sid(actor) if actor else None,
                    actor_name=NAME[actor] if actor else "Scrum Bot",
                    action=action,
                    entity_type=etype,
                    entity_id=eid,
                    diff=diff,
                )
            )
        await db.flush()

        # Tie extracted blockers in updates to their lifecycle rows (so the digest shows "day N").
        links = {("u-rahul", tue): "blk-rahul-sandbox", ("u-amit", mon): "blk-amit-staging"}
        for d in (mon, tue, wed, thu, fri):
            links[("u-priya", d)] = "blk-priya-review"
        for (user, d), slug in links.items():
            row = (
                await db.execute(
                    MemberUpdateRow.__table__.select().where(
                        MemberUpdateRow.session_id == ses(d), MemberUpdateRow.user_id == sid(user)
                    )
                )
            ).first()
            if row:
                payload = dict(row.payload)
                for b in payload.get("blockers", []):
                    b["_blocker_id"] = str(sid(slug))
                await db.execute(
                    MemberUpdateRow.__table__.update().where(MemberUpdateRow.id == row.id).values(payload=payload)
                )

    # ---------------- reports (rendered with the real digest template)
    from scrum_delivery.activities import _digest_context  # scripts may compose services
    from scrum_delivery.render import render

    async with owner_session() as db:
        await set_org_context(db, ORG_ID)
        for ses_id in session_ids.values():
            sess = await db.get(StandupSession, ses_id)
            assert sess is not None
            html = render("digest.html.j2", **await _digest_context(db, sess))
            db.add(Report(org_id=ORG_ID, session_id=ses_id, html=html, summary={}))

    if with_temporal and s.temporal_enabled:
        from scrum_core import workflow_client

        try:
            for tslug, _n, _l, cron, *_ in TEAMS:
                await workflow_client.upsert_schedule(
                    org_id=ORG_ID, team_id=sid(tslug), cron=cron, tz="Asia/Kolkata", lead_minutes=5, paused=False
                )
            print("Temporal schedules upserted.")
        except Exception as exc:
            print(f"Skipped Temporal schedules ({exc.__class__.__name__}: {exc})")

    print(f"Seeded org {ORG_ID} - story week {mon} to {fri}, {len(session_ids)} sessions, embedder={emb.name}.")
    print("Dev personas (X-Mock-User): u-neha (lead), u-deepa (admin), u-rahul (member), u-vikram (viewer).")
    await dispose_engines()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-temporal", action="store_true", help="don't create Temporal schedules")
    asyncio.run(seed(with_temporal=not ap.parse_args().no_temporal))


if __name__ == "__main__":
    main()
