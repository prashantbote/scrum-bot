"""Dashboard metrics (plan §11), team-level by default.

Computed on request over RLS-protected tables. (Plain materialized views would bypass RLS, so they'd
need their own org filter; at standup volumes — tens of rows per team per day — live SQL is fast.)
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_adapters import registry
from scrum_adapters.llm import cosine
from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session
from scrum_api.errors import invalid
from scrum_api.rbac import individual_scope, team_or_404
from scrum_core.models import Attendance, Blocker, BlockerEvent, MemberUpdateRow, StandupSession, Team, TeamMember, User
from scrum_core.models.base import BlockerEventKind, BlockerStatus

router = APIRouter(prefix="/metrics", tags=["metrics"])


class Range:
    def __init__(self, team: UUID = Query(...), from_: date = Query(alias="from"), to: date = Query(...)):
        if from_ > to:
            raise invalid("from", "'from' must be on or before 'to'")
        if (to - from_).days > 366:
            raise invalid("from", "Range is limited to one year")
        self.team, self.start, self.end = team, from_, to

    def previous(self) -> tuple[date, date]:
        n = (self.end - self.start).days + 1
        return self.start - timedelta(days=n), self.start - timedelta(days=1)


def _local(dt: datetime | None, tz: ZoneInfo) -> date | None:
    return dt.astimezone(tz).date() if dt else None


async def _sessions(db: AsyncSession, team_id: UUID, start: date, end: date) -> list[StandupSession]:
    return list(
        (
            await db.execute(
                select(StandupSession)
                .where(
                    StandupSession.team_id == team_id, StandupSession.run_date >= start, StandupSession.run_date <= end
                )
                .order_by(StandupSession.run_date)
            )
        ).scalars()
    )


# ------------------------------------------------------------------------------- participation


async def _participation(
    db: AsyncSession, team_id: UUID, start: date, end: date
) -> tuple[float, list[S.ParticipationPoint]]:
    sessions = await _sessions(db, team_id, start, end)
    counts: dict[UUID, dict[str, int]] = defaultdict(lambda: {"present": 0, "async": 0, "absent": 0})
    if sessions:
        for sid, status in await db.execute(
            select(Attendance.session_id, Attendance.status).where(Attendance.session_id.in_([s.id for s in sessions]))
        ):
            counts[sid][status.value] += 1
    series = []
    for s in sessions:
        c = counts[s.id]
        total = c["present"] + c["async"] + c["absent"]
        if total == 0:
            continue
        series.append(
            S.ParticipationPoint(
                date=s.run_date,
                rate=(c["present"] + c["async"]) / total,
                present=c["present"],
                async_=c["async"],
                absent=c["absent"],
            )
        )
    tot = sum(p.present + p.async_ + p.absent for p in series)
    ok = sum(p.present + p.async_ for p in series)
    return (ok / tot if tot else 0.0), series


@router.get("/participation", response_model=S.ParticipationMetrics, response_model_by_alias=True)
async def participation(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.ParticipationMetrics:
    await team_or_404(p, db, r.team)
    rate, series = await _participation(db, r.team, r.start, r.end)
    prev_rate, prev_series = await _participation(db, r.team, *r.previous())
    return S.ParticipationMetrics(rate=rate, delta=(rate - prev_rate) * 100 if prev_series else 0.0, series=series)


# ------------------------------------------------------------------------------- blockers


def _stats(blockers: list[Blocker], tz: ZoneInfo, start: date, end: date) -> tuple[list[Blocker], list[Blocker], float]:
    raised = [b for b in blockers if start <= (_local(b.first_seen_at, tz) or start) <= end]
    resolved = [b for b in blockers if b.resolved_at and start <= (_local(b.resolved_at, tz) or start) <= end]
    durations = [(b.resolved_at - b.first_seen_at).total_seconds() / 86_400 for b in resolved if b.resolved_at]
    return raised, resolved, (sum(durations) / len(durations) if durations else 0.0)


@router.get("/blockers", response_model=S.BlockerMetrics)
async def blocker_metrics(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.BlockerMetrics:
    team = await team_or_404(p, db, r.team)
    tz = ZoneInfo(team.timezone)
    blockers = list((await db.execute(select(Blocker).where(Blocker.team_id == team.id))).scalars())
    raised, resolved, avg = _stats(blockers, tz, r.start, r.end)
    _, prev_resolved, prev_avg = _stats(blockers, tz, *r.previous())
    open_ = [b for b in blockers if b.status != BlockerStatus.resolved]
    buckets = [("< 1 day", 0, 0), ("1–2 days", 1, 2), ("3–5 days", 3, 5), ("> 5 days", 6, 10**6)]  # noqa: RUF001 (labels match the UI)
    weekly = []
    for w in (3, 2, 1, 0):
        wend = r.end - timedelta(days=7 * w)
        wstart = wend - timedelta(days=6)
        wr, wres, _ = _stats(blockers, tz, wstart, wend)
        weekly.append(S.WeeklyBlockers(week=wstart.strftime("%m-%d"), raised=len(wr), resolved=len(wres)))
    return S.BlockerMetrics(
        raised=len(raised),
        resolved=len(resolved),
        open=len(open_),
        avg_resolve_days=round(avg, 2),
        avg_resolve_delta=round(avg - prev_avg, 2) if prev_resolved and resolved else 0.0,
        age_buckets=[
            S.AgeBucket(bucket=label, count=sum(1 for b in open_ if lo <= b.days_open <= hi))
            for label, lo, hi in buckets
        ],
        weekly=weekly,
    )


# ------------------------------------------------------------------------------- carry-over


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if set(a.get("ticket_keys") or []) & set(b.get("ticket_keys") or []):
        return True
    return fuzz.token_set_ratio(_norm(a.get("summary", "")), _norm(b.get("summary", ""))) >= 85


async def _carry_series(db: AsyncSession, team_id: UUID, start: date, end: date) -> list[S.RatePoint]:
    """Planned items that don't show up as completed in the member's next update (plan §11 mv_carry_over)."""
    sessions = await _sessions(db, team_id, start, end + timedelta(days=14))
    if not sessions:
        return []
    by_session: dict[UUID, dict[UUID, dict[str, Any]]] = defaultdict(dict)
    for sid, uid, payload in await db.execute(
        select(MemberUpdateRow.session_id, MemberUpdateRow.user_id, MemberUpdateRow.payload).where(
            MemberUpdateRow.session_id.in_([s.id for s in sessions])
        )
    ):
        by_session[sid][uid] = payload
    series = []
    for i, s in enumerate(sessions):
        if s.run_date > end:
            break
        planned_total = carried = 0
        for uid, upd in by_session[s.id].items():
            nxt = next((by_session[n.id][uid] for n in sessions[i + 1 :] if uid in by_session[n.id]), None)
            if nxt is None:
                continue
            done_next = nxt.get("completed", [])
            for item in upd.get("planned", []):
                planned_total += 1
                if not any(_same_item(item, d) for d in done_next):
                    carried += 1
        if planned_total:
            series.append(S.RatePoint(date=s.run_date, rate=carried / planned_total))
    return series


@router.get("/carry-over", response_model=S.CarryOverMetrics)
async def carry_over(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.CarryOverMetrics:
    await team_or_404(p, db, r.team)
    series = await _carry_series(db, r.team, r.start, r.end)
    prev = await _carry_series(db, r.team, *r.previous())
    rate = sum(x.rate for x in series) / len(series) if series else 0.0
    prev_rate = sum(x.rate for x in prev) / len(prev) if prev else 0.0
    return S.CarryOverMetrics(rate=rate, delta=round((rate - prev_rate) * 100, 1) if prev else 0.0, series=series)


# ------------------------------------------------------------------------------- said vs PM


@router.get("/mismatches", response_model=list[S.Mismatch])
async def mismatches(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.Mismatch]:
    """Items reported as done whose ticket isn't Done in the PM tool (plan §11 mv_said_vs_pm).

    An item counts as "the ticket is done" only when it names the ticket itself (summary ≈ ticket title),
    so finishing a sub-task ("refund API tests") isn't flagged against the parent ticket.
    """
    team = await team_or_404(p, db, r.team)
    pm = await registry.pm_for_org(db, p.org_id)
    if pm is None:
        return []
    sessions = {s.id: s for s in await _sessions(db, team.id, r.start, r.end)}
    if not sessions:
        return []
    rows = (
        await db.execute(
            select(MemberUpdateRow, User.display_name)
            .join(User, User.id == MemberUpdateRow.user_id)
            .where(MemberUpdateRow.session_id.in_(list(sessions)))
        )
    ).all()
    latest: dict[tuple[UUID, str], S.Mismatch] = {}
    tickets: dict[str, Any] = {}
    scope = individual_scope(p, team.id)
    for row, name in rows:
        for item in row.payload.get("completed", []):
            for key in item.get("ticket_keys", []):
                if key not in tickets:
                    tickets[key] = await pm.get_ticket(key)
                t = tickets[key]
                if t is None or t.status.lower() == "done":
                    continue
                if fuzz.ratio(_norm(item.get("summary", "")), _norm(t.summary)) < 90:
                    continue
                s = sessions[row.session_id]
                k = (row.user_id, key)
                if k not in latest or latest[k].date < s.run_date:
                    latest[k] = S.Mismatch(
                        member_name=name if scope == "all" or (scope == "self" and row.user_id == p.user_id) else "—",
                        ticket_key=key,
                        said=f"Done — {item.get('summary', '')}",
                        pm_status=t.status,
                        session_id=s.id,
                        date=s.run_date,
                    )
    out = sorted(latest.values(), key=lambda m: m.date, reverse=True)
    if scope == "self":
        out = [m for m in out if m.member_name != "—"]
    return out


# ------------------------------------------------------------------------------- dependencies


@router.get("/dependencies", response_model=S.DependencyGraph)
async def dependencies(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.DependencyGraph:
    team = await team_or_404(p, db, r.team)
    self_id = f"team:{team.id}"
    nodes: dict[str, S.GraphNode] = {self_id: S.GraphNode(id=self_id, label=team.name, kind="team", is_self=True)}
    edges: dict[str, int] = defaultdict(int)
    sessions = await _sessions(db, team.id, r.start, r.end)
    if sessions:
        payloads = (
            (
                await db.execute(
                    select(MemberUpdateRow.payload).where(MemberUpdateRow.session_id.in_([s.id for s in sessions]))
                )
            )
            .scalars()
            .all()
        )
        targets: list[tuple[str | None, str | None, str | None]] = []
        for pl in payloads:
            targets += [(b.get("blocked_on_member_id"), None, b.get("blocked_on_raw")) for b in pl.get("blockers", [])]
            targets += [
                (d.get("on_member_id"), d.get("on_team_id"), d.get("on_raw")) for d in pl.get("dependencies", [])
            ]
        users = (
            {
                str(u.id): u
                for u in (
                    await db.execute(select(User).where(User.id.in_([UUID(t[0]) for t in targets if t[0]])))
                ).scalars()
            }
            if targets
            else {}
        )
        tnames = {str(t.id): t.name for t in (await db.execute(select(Team))).scalars()}
        # A person's "home" team other than this one: a team they lead first, then one they belong to.
        home: dict[str, str] = {}
        for t in (await db.execute(select(Team))).scalars():
            if str(t.id) != str(team.id):
                home.setdefault(str(t.lead_user_id), t.name)
        for m_team, m_user in await db.execute(select(TeamMember.team_id, TeamMember.user_id)):
            if m_team != team.id:
                home.setdefault(str(m_user), tnames.get(str(m_team), ""))
        for uid, tid, raw in targets:
            if tid and tid in tnames and tnames[tid] != team.name:
                label = tnames[tid]
            elif uid and uid in home:
                label = home[uid]
            else:
                dept = users[uid].department if uid and uid in users else None
                label = dept if dept and dept != team.name else (raw or "External")
            nid = f"ext:{label}"
            nodes.setdefault(nid, S.GraphNode(id=nid, label=label, kind="team", is_self=False))
            edges[nid] += 1
    return S.DependencyGraph(
        nodes=list(nodes.values()), edges=[S.GraphEdge(source=self_id, target=t, weight=w) for t, w in edges.items()]
    )


# ------------------------------------------------------------------------------- themes

THEMES: list[tuple[str, tuple[str, ...]]] = [
    ("Code review latency", ("review", "pr ", "pull request", "approve")),
    ("Environment instability", ("staging", "environment", "deploy", "flaky", "sandbox env", "outage")),
    ("Credentials & access", ("credential", "access", "permission", "password", "token", "vpn")),
    ("API contract changes", ("contract", "api spec", "schema", "interface")),
    ("Database maintenance windows", ("dba", "maintenance window", "database", "migration window")),
    ("Design dependencies", ("design", "mockup", "figma", "ux")),
    ("External vendors & partners", ("vendor", "partner", "gateway", "third party", "kyc")),
    ("Infrastructure & capacity", ("timeout", "capacity", "latency", "kafka", "infra")),
]


def _theme(text: str) -> str | None:
    t = f" {text.lower()} "
    return next((label for label, words in THEMES if any(w in t for w in words)), None)


def _cluster(blockers: list[Blocker], threshold: float = 0.78) -> dict[UUID, str]:
    """Theme per blocker: taxonomy first, then greedy embedding clusters labeled by their first blocker."""
    out: dict[UUID, str] = {}
    centroids: list[tuple[list[float], str]] = []
    for b in blockers:
        label = _theme(f"{b.description} {b.blocked_on_raw or ''}")
        if label is None and b.embedding is not None:
            vec = list(b.embedding)
            match = next((lbl for c, lbl in centroids if cosine(vec, c) >= threshold), None)
            if match is None:
                match = b.description[:48]
                centroids.append((vec, match))
            label = match
        out[b.id] = label or "Other"
    return out


_theme_cache: dict[tuple[UUID, date, date], tuple[float, list[S.BlockerTheme]]] = {}


@router.get("/themes", response_model=list[S.BlockerTheme])
async def themes(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> list[S.BlockerTheme]:
    team = await team_or_404(p, db, r.team)
    cache_key = (team.id, r.start, r.end)
    if (hit := _theme_cache.get(cache_key)) and time.time() - hit[0] < 300:
        return hit[1]
    tz = ZoneInfo(team.timezone)
    prev_start, _ = r.previous()
    blockers = list((await db.execute(select(Blocker).where(Blocker.team_id == team.id))).scalars())
    labels = _cluster(blockers)
    events = (
        (
            await db.execute(
                select(BlockerEvent.blocker_id, BlockerEvent.at).where(
                    BlockerEvent.blocker_id.in_([b.id for b in blockers]),
                    BlockerEvent.kind.in_([BlockerEventKind.raised, BlockerEventKind.mentioned]),
                )
            )
        ).all()
        if blockers
        else []
    )
    cur: dict[str, int] = defaultdict(int)
    prev: dict[str, int] = defaultdict(int)
    for bid, at in events:
        d = at.astimezone(tz).date()
        if r.start <= d <= r.end:
            cur[labels[bid]] += 1
        elif prev_start <= d < r.start:
            prev[labels[bid]] += 1
    out = [
        S.BlockerTheme(label=label, count=n, trend="up" if n > prev[label] else "down" if n < prev[label] else "flat")
        for label, n in sorted(cur.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    _theme_cache[cache_key] = (time.time(), out)
    return out


# ------------------------------------------------------------------------------- burndown

_burndown_cache: dict[tuple[UUID, str], tuple[float, S.BurndownOut]] = {}


@router.get("/burndown", response_model=S.BurndownOut)
async def burndown(
    r: Range = Depends(), p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.BurndownOut:
    """Live from the PM tool, cached 15 minutes (plan §11)."""
    team = await team_or_404(p, db, r.team)
    board = team.pm_board_id or "default"
    key = (p.org_id, board)
    if (hit := _burndown_cache.get(key)) and time.time() - hit[0] < 900:
        return hit[1]
    pm = await registry.pm_for_org(db, p.org_id)
    if pm is None:
        return S.BurndownOut(sprint_name="Connect Jira to see the sprint burndown", points=[])
    bd = await pm.sprint_burndown(board)
    out = S.BurndownOut(
        sprint_name=bd.sprint_name,
        points=[S.BurndownPointOut(date=x.date, ideal=x.ideal, remaining=x.remaining) for x in bd.points],
    )
    _burndown_cache[key] = (time.time(), out)
    return out
