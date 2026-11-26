"""Temporal activities on the ``intelligence`` task queue (plan §7.3, §9)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from temporalio import activity

from scrum_adapters import registry
from scrum_core.db import session_for
from scrum_core.models import (
    AsyncCheckin,
    Blocker,
    BlockerEvent,
    BlockerEvidence,
    Dependency,
    MemberUpdateRow,
    Organization,
    Question,
    ReviewItem,
    StandupSession,
    Team,
    TeamMember,
    TranscriptSegment,
    User,
)
from scrum_core.models.base import BlockerEventKind, BlockerStatus, ReviewKind, Severity, UpdateSource
from scrum_core.schedule import weekdays_between
from scrum_core.schemas.extraction import MemberUpdate
from scrum_core.schemas.workflow import BlockerRefs, ExtractResult, SessionRef
from scrum_core.settings import get_settings
from scrum_intelligence.blocker_match import Existing, decide, embed_text
from scrum_intelligence.extraction import Line, MemberTurn, extract_turn
from scrum_intelligence.grounding import ground
from scrum_intelligence.resolution import Person, TeamRef, resolve

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------------- helpers


async def build_turns(db: AsyncSession, session_id: UUID) -> list[MemberTurn]:
    """Group the transcript per member: each bot line belongs to the next member who speaks."""
    qrows = (
        await db.execute(
            select(Question.id, Question.position, Question.text)
            .join(StandupSession, StandupSession.template_id == Question.template_id)
            .where(StandupSession.id == session_id)
        )
    ).all()
    qpos = {qid: (pos, text) for qid, pos, text in qrows}
    names = {u.id: u.display_name for u in (await db.execute(select(User))).scalars()}
    segs = (
        (
            await db.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.session_id == session_id)
                .order_by(TranscriptSegment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    turns: dict[UUID, MemberTurn] = {}
    pending_bot: list[TranscriptSegment] = []
    handle = 0

    def line(seg: TranscriptSegment, speaker: str) -> Line:
        nonlocal handle
        handle += 1
        pos, qtext = qpos.get(seg.question_id, (None, None)) if seg.question_id else (None, None)
        return Line(
            handle=handle, segment_id=seg.id, speaker=speaker, text=seg.text, question_position=pos, question_text=qtext
        )

    for seg in segs:
        if seg.speaker_user_id is None:
            pending_bot.append(seg)
            continue
        uid = seg.speaker_user_id
        turn = turns.setdefault(uid, MemberTurn(member_id=uid, member_name=names.get(uid, "Member")))
        for b in pending_bot:
            turn.lines.append(line(b, "bot"))
        pending_bot = []
        turn.lines.append(line(seg, "member"))

    # Async check-ins become pseudo-turns (no segment ids; the check-in itself is the evidence).
    checkins = (await db.execute(select(AsyncCheckin).where(AsyncCheckin.session_id == session_id))).scalars().all()
    for ci in checkins:
        turn = MemberTurn(member_id=ci.user_id, member_name=names.get(ci.user_id, "Member"), source="async")
        for qid, (pos, qtext) in sorted(qpos.items(), key=lambda kv: kv[1][0]):
            ans = (ci.answers or {}).get(str(qid), "").strip()
            if not ans:
                continue
            handle += 1
            turn.lines.append(Line(handle, None, "bot", qtext, pos, qtext))
            handle += 1
            turn.lines.append(Line(handle, None, "member", ans, pos, qtext))
        turns[ci.user_id] = turn
    return list(turns.values())


async def _roster(db: AsyncSession) -> tuple[list[Person], list[TeamRef]]:
    teams = (await db.execute(select(Team))).scalars().all()
    memberships: dict[UUID, set[UUID]] = {}
    for tid, uid in await db.execute(select(TeamMember.team_id, TeamMember.user_id)):
        memberships.setdefault(uid, set()).add(tid)
    for t in teams:
        memberships.setdefault(t.lead_user_id, set()).add(t.id)
    people = [
        Person(
            id=u.id,
            name=u.display_name,
            aliases=u.aliases or [],
            department=u.department,
            team_ids=memberships.get(u.id, set()),
        )
        for u in (await db.execute(select(User).where(User.erased_at.is_(None)))).scalars()
    ]
    return people, [TeamRef(id=t.id, name=t.name, lead_id=t.lead_user_id) for t in teams]


# ------------------------------------------------------------------------------- activities


@activity.defn(name="extract_updates")
async def extract_updates(ref: SessionRef) -> ExtractResult:
    s = get_settings()
    llm = registry.llm("strong")
    member_ids: list[UUID] = []
    async with session_for(ref.org_id) as db:
        turns = await build_turns(db, ref.session_id)
    for turn in turns:
        activity.heartbeat(str(turn.member_id))
        raw, model = await extract_turn(turn, llm, model=s.llm_strong_model)
        update, report = ground(turn, raw)
        update.answers = {str(ln.handle): ln.text for ln in turn.member_lines()}
        payload: dict[str, Any] = update.model_dump(mode="json")
        payload["grounding_dropped"] = report.dropped
        async with session_for(ref.org_id) as db:
            stmt = (
                insert(MemberUpdateRow)
                .values(
                    org_id=ref.org_id,
                    session_id=ref.session_id,
                    user_id=turn.member_id,
                    source=UpdateSource.async_ if turn.source == "async" else UpdateSource.voice,
                    payload=payload,
                    extraction_model=model,
                    version=1,
                )
                .on_conflict_do_update(
                    index_elements=["session_id", "user_id"],
                    set_={
                        "payload": payload,
                        "extraction_model": model,
                        "version": MemberUpdateRow.version + 1,
                        "updated_at": datetime.now(UTC),
                    },
                )
            )
            await db.execute(stmt)
        member_ids.append(turn.member_id)
    return ExtractResult(org_id=ref.org_id, session_id=ref.session_id, team_id=ref.team_id, member_ids=member_ids)


@activity.defn(name="resolve_people_and_tickets")
async def resolve_people_and_tickets(res: ExtractResult) -> ExtractResult:
    s = get_settings()
    llm = registry.llm("fast")
    async with session_for(res.org_id) as db:
        people, teams = await _roster(db)
        pm = await registry.pm_for_org(db, res.org_id)
        rows = (
            (await db.execute(select(MemberUpdateRow).where(MemberUpdateRow.session_id == res.session_id)))
            .scalars()
            .all()
        )
        ticket_ok: dict[str, bool] = {}

        async def valid(keys: list[str]) -> list[str]:
            if pm is None:
                return keys
            out = []
            for k in keys:
                if k not in ticket_ok:
                    try:
                        ticket_ok[k] = await pm.get_ticket(k) is not None
                    except Exception:  # PM tool hiccup: keep the key rather than lose data
                        ticket_ok[k] = True
                if ticket_ok[k]:
                    out.append(k)
            return out

        for row in rows:
            p = dict(row.payload)
            answers = " ".join(p.get("answers", {}).values())
            for item in [*p.get("completed", []), *p.get("planned", [])]:
                item["ticket_keys"] = await valid(item.get("ticket_keys", []))
            for b in p.get("blockers", []):
                b["ticket_keys"] = await valid(b.get("ticket_keys", []))
                r = await resolve(
                    b.get("blocked_on_raw"),
                    answers,
                    people,
                    teams,
                    reporter_id=row.user_id,
                    reporter_team=res.team_id,
                    llm=llm,
                    model=s.llm_fast_model,
                )
                b.pop("_person_review", None)
                if r is None or r.best is None:
                    continue
                if r.confidence >= s.person_auto_threshold:
                    b["blocked_on_member_id"] = str(r.best.person.id)
                elif r.confidence >= s.person_review_threshold:
                    b["blocked_on_member_id"] = None
                    b["_person_review"] = {
                        "confidence": r.confidence,
                        "candidates": [
                            {
                                "id": str(c.person.id),
                                "label": c.person.name,
                                "sublabel": c.person.department,
                                "confidence": round(c.score, 2),
                            }
                            for c in r.candidates
                        ],
                    }
            for d in p.get("dependencies", []):
                d["ticket_keys"] = await valid(d.get("ticket_keys", []))
                r = await resolve(
                    d.get("on_raw"),
                    answers,
                    people,
                    teams,
                    reporter_id=row.user_id,
                    reporter_team=res.team_id,
                    llm=llm,
                    model=s.llm_fast_model,
                )
                if r and r.team:
                    d["on_team_id"] = str(r.team.id)
                if r and r.best and r.confidence >= s.person_auto_threshold:
                    d["on_member_id"] = str(r.best.person.id)
            MemberUpdate.model_validate({k: v for k, v in p.items() if not k.startswith("_")})  # schema guard
            row.payload = p
            flag_modified(row, "payload")  # nested JSONB edits aren't detected by assignment alone
    return res


async def _segment_times(db: AsyncSession, session: StandupSession, seg_ids: list[str]) -> datetime:
    base = session.started_at or datetime.now(UTC)
    if seg_ids:
        start = (
            await db.execute(
                select(TranscriptSegment.start_ms)
                .where(TranscriptSegment.id.in_([UUID(x) for x in seg_ids]))
                .order_by(TranscriptSegment.start_ms)
            )
        ).scalar()
        if start is not None:
            return base + timedelta(milliseconds=start)
    return base


@activity.defn(name="match_and_upsert_blockers")
async def match_and_upsert_blockers(res: ExtractResult) -> BlockerRefs:
    s = get_settings()
    emb = registry.embedder()
    new_ids: list[UUID] = []
    matched_ids: list[UUID] = []
    async with session_for(res.org_id) as db:
        session = await db.get(StandupSession, res.session_id)
        team = await db.get(Team, res.team_id)
        assert session is not None and team is not None
        tz = ZoneInfo(team.timezone)
        rows = (
            (await db.execute(select(MemberUpdateRow).where(MemberUpdateRow.session_id == session.id))).scalars().all()
        )
        names = {u.id: u.display_name for u in (await db.execute(select(User))).scalars()}

        # Idempotent re-runs: forget what this activity already wrote for this session.
        already = (
            (await db.execute(select(Blocker.id).where(Blocker.first_seen_session_id == session.id))).scalars().all()
        )
        if already:
            new_ids.extend(already)

        for row in rows:
            for b in row.payload.get("blockers", []):
                if b.get("_blocker_id"):
                    continue  # processed on a previous attempt
                tickets = b.get("ticket_keys", [])
                [vec] = await emb.embed([embed_text(b["description"], tickets)])
                nearest = (
                    (
                        await db.execute(
                            select(Blocker)
                            .where(
                                Blocker.team_id == team.id,
                                Blocker.status.in_(
                                    [BlockerStatus.open, BlockerStatus.acknowledged, BlockerStatus.needs_review]
                                ),
                                Blocker.embedding.is_not(None),
                            )
                            .order_by(Blocker.embedding.cosine_distance(vec))
                            .limit(5)
                        )
                    )
                    .scalars()
                    .all()
                )
                # Ticket-sharing candidates even if they aren't among the nearest embeddings.
                if tickets:
                    nearest = list(
                        {
                            x.id: x
                            for x in [
                                *nearest,
                                *(
                                    await db.execute(
                                        select(Blocker).where(
                                            Blocker.team_id == team.id,
                                            Blocker.ticket_keys.overlap(tickets),
                                            Blocker.status.in_([BlockerStatus.open, BlockerStatus.acknowledged]),
                                        )
                                    )
                                ).scalars(),
                            ]
                        }.values()
                    )
                decision = decide(
                    reporter_id=row.user_id,
                    ticket_keys=tickets,
                    embedding=vec,
                    existing=[
                        Existing(
                            x.id,
                            x.reporter_user_id,
                            x.ticket_keys or [],
                            list(x.embedding) if x.embedding is not None else None,
                            x.description,
                        )
                        for x in nearest
                    ],
                    same_with_ticket=s.blocker_same_with_ticket,
                    same_without_ticket=s.blocker_same_without_ticket,
                )
                at = await _segment_times(db, session, b.get("evidence_segment_ids", []))
                seg_ids = [UUID(x) for x in b.get("evidence_segment_ids", [])]
                if decision.kind == "same" and decision.blocker_id:
                    ex = await db.get(Blocker, decision.blocker_id)
                    assert ex is not None
                    ex.last_seen_session_id, ex.last_seen_at = session.id, at
                    if not ex.blocked_on_user_id and b.get("blocked_on_member_id"):
                        ex.blocked_on_user_id = UUID(b["blocked_on_member_id"])
                    db.add(
                        BlockerEvent(
                            org_id=res.org_id,
                            blocker_id=ex.id,
                            at=at,
                            kind=BlockerEventKind.mentioned,
                            actor_name=names.get(row.user_id),
                            session_id=session.id,
                            note=f"Matched to existing blocker ({decision.reason}) — no repeat alert",
                        )
                    )
                    target = ex
                    matched_ids.append(ex.id)
                else:
                    person_review = b.get("_person_review")
                    hold = bool(person_review) or decision.kind == "review"
                    target = Blocker(
                        org_id=res.org_id,
                        team_id=team.id,
                        reporter_user_id=row.user_id,
                        blocked_on_user_id=UUID(b["blocked_on_member_id"]) if b.get("blocked_on_member_id") else None,
                        blocked_on_raw=b.get("blocked_on_raw"),
                        description=b["description"],
                        ticket_keys=tickets,
                        severity=Severity(b.get("severity", "medium")),
                        status=BlockerStatus.needs_review if hold else BlockerStatus.open,
                        first_seen_session_id=session.id,
                        last_seen_session_id=session.id,
                        first_seen_at=at,
                        last_seen_at=at,
                        days_open=0,
                        embedding=vec,
                        alert_held=hold,
                    )
                    db.add(target)
                    await db.flush()
                    source = "async check-in" if row.source == UpdateSource.async_ else "standup"
                    db.add(
                        BlockerEvent(
                            org_id=res.org_id,
                            blocker_id=target.id,
                            at=at,
                            kind=BlockerEventKind.raised,
                            actor_name=names.get(row.user_id),
                            note=f"Raised in {source}",
                            session_id=session.id,
                        )
                    )
                    quote = " ".join(v for v in row.payload.get("answers", {}).values())[:400]
                    if person_review:
                        db.add(
                            ReviewItem(
                                org_id=res.org_id,
                                kind=ReviewKind.person_match,
                                team_id=team.id,
                                session_id=session.id,
                                confidence=person_review["confidence"],
                                dedupe_key=f"person:{target.id}",
                                payload={
                                    "raw_phrase": b.get("blocked_on_raw") or "",
                                    "evidence_quote": quote,
                                    "evidence_speaker": names.get(row.user_id, ""),
                                    "candidates": person_review["candidates"],
                                    "context": {"blocker_id": str(target.id)},
                                },
                            )
                        )
                    if decision.kind == "review" and decision.blocker_id:
                        ex = await db.get(Blocker, decision.blocker_id)
                        db.add(
                            ReviewItem(
                                org_id=res.org_id,
                                kind=ReviewKind.blocker_match,
                                team_id=team.id,
                                session_id=session.id,
                                confidence=decision.score,
                                dedupe_key=f"blocker:{target.id}",
                                payload={
                                    "raw_phrase": b["description"],
                                    "evidence_quote": quote,
                                    "evidence_speaker": names.get(row.user_id, ""),
                                    "candidates": [
                                        {
                                            "id": str(decision.blocker_id),
                                            "label": ex.description if ex else "",
                                            "sublabel": f"{team.name} · {ex.status if ex else ''}",
                                            "confidence": round(decision.score, 2),
                                        },
                                        {
                                            "id": "new",
                                            "label": "Create as a new blocker",
                                            "sublabel": None,
                                            "confidence": round(1 - decision.score, 2),
                                        },
                                    ],
                                    "context": {"new_blocker_id": str(target.id)},
                                },
                            )
                        )
                    new_ids.append(target.id)
                for sid in seg_ids:
                    await db.execute(
                        insert(BlockerEvidence)
                        .values(org_id=res.org_id, blocker_id=target.id, segment_id=sid)
                        .on_conflict_do_nothing()
                    )
                b["_blocker_id"] = str(target.id)
            for d in row.payload.get("dependencies", []):
                if d.get("_dependency_id"):
                    continue
                dep = Dependency(
                    org_id=res.org_id,
                    session_id=session.id,
                    from_user_id=row.user_id,
                    to_user_id=UUID(d["on_member_id"]) if d.get("on_member_id") else None,
                    to_team_id=UUID(d["on_team_id"]) if d.get("on_team_id") else None,
                    on_raw=d["on_raw"],
                    description=d["description"],
                    ticket_keys=d.get("ticket_keys", []),
                )
                db.add(dep)
                await db.flush()
                d["_dependency_id"] = str(dep.id)
            flag_modified(row, "payload")  # persist the _blocker_id/_dependency_id markers (idempotent re-runs)

        # Age every still-open blocker in "standup days" since the standup that first raised it
        # (drives escalation, plan §9.3). Falls back to the timestamp for blockers without a session.
        first_dates = dict(
            (
                await db.execute(
                    select(Blocker.id, StandupSession.run_date)
                    .join(StandupSession, StandupSession.id == Blocker.first_seen_session_id)
                    .where(Blocker.team_id == team.id)
                )
            ).all()
        )
        for blk in (
            await db.execute(
                select(Blocker).where(
                    Blocker.team_id == team.id,
                    Blocker.status.in_([BlockerStatus.open, BlockerStatus.acknowledged, BlockerStatus.needs_review]),
                )
            )
        ).scalars():
            start = first_dates.get(blk.id) or blk.first_seen_at.astimezone(tz).date()
            blk.days_open = weekdays_between(start, session.run_date)

    return BlockerRefs(
        org_id=res.org_id,
        session_id=res.session_id,
        team_id=res.team_id,
        new_blocker_ids=list(dict.fromkeys(new_ids)),
        matched_blocker_ids=matched_ids,
    )


@activity.defn(name="resolve_confirmed_blockers")
async def resolve_confirmed_blockers(args: dict[str, Any]) -> int:
    """Blockers the member confirmed as resolved when the bot asked "Is that resolved now?"."""
    org_id = UUID(args["org_id"])
    ids = [UUID(x) for x in args.get("blocker_ids", [])]
    if not ids:
        return 0
    n = 0
    async with session_for(org_id) as db:
        for b in (await db.execute(select(Blocker).where(Blocker.id.in_(ids)))).scalars():
            if b.status != BlockerStatus.resolved:
                b.status, b.resolved_at = BlockerStatus.resolved, datetime.now(UTC)
                db.add(
                    BlockerEvent(
                        org_id=org_id,
                        blocker_id=b.id,
                        at=b.resolved_at,
                        kind=BlockerEventKind.resolved,
                        actor_name="Scrum Bot",
                        note="Confirmed resolved in standup",
                        session_id=UUID(args["session_id"]) if args.get("session_id") else None,
                    )
                )
                n += 1
    return n


@activity.defn(name="propose_pm_updates")
async def propose_pm_updates(res: ExtractResult) -> int:
    """v2 PM write-back: items said to be done whose ticket isn't Done → approval-gated review items."""
    created = 0
    async with session_for(res.org_id) as db:
        org = await db.get(Organization, res.org_id)
        if not org or not (org.settings or {}).get("pm_writeback_enabled"):
            return 0
        pm = await registry.pm_for_org(db, res.org_id)
        if pm is None:
            return 0
        names = {u.id: u.display_name for u in (await db.execute(select(User))).scalars()}
        rows = (await db.execute(select(MemberUpdateRow).where(MemberUpdateRow.session_id == res.session_id))).scalars()
        for row in rows:
            for item in row.payload.get("completed", []):
                if item.get("status") != "done":
                    continue
                for key in item.get("ticket_keys", []):
                    t = await pm.get_ticket(key)
                    if t is None or t.status.lower() == "done":
                        continue
                    if fuzz.ratio(item["summary"].lower(), t.summary.lower()) < 85:
                        continue
                    stmt = (
                        insert(ReviewItem)
                        .values(
                            org_id=res.org_id,
                            kind=ReviewKind.pm_writeback,
                            team_id=res.team_id,
                            session_id=res.session_id,
                            confidence=0.9,
                            dedupe_key=f"pm:{res.session_id}:{key}",
                            payload={
                                "raw_phrase": item["summary"],
                                "evidence_quote": item["summary"],
                                "evidence_speaker": names.get(row.user_id, ""),
                                "candidates": [
                                    {
                                        "id": "transition-done",
                                        "label": f"Transition {key} → Done",
                                        "sublabel": f"Jira currently: {t.status}",
                                        "confidence": 0.9,
                                    }
                                ],
                                "context": {"ticket_key": key, "transition_to": "Done"},
                            },
                        )
                        .on_conflict_do_nothing()
                    )
                    created += (await db.execute(stmt)).rowcount or 0  # type: ignore[attr-defined]
    return created


ACTIVITIES: list[Callable[..., Any]] = [
    extract_updates,
    resolve_people_and_tickets,
    match_and_upsert_blockers,
    resolve_confirmed_blockers,
    propose_pm_updates,
]
