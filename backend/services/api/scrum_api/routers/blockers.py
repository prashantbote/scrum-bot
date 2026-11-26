"""Blockers board and the review queue (plan §9.2, §9.3)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_adapters import registry
from scrum_adapters.pm import TicketChange
from scrum_api import projections as P
from scrum_api import schemas as S
from scrum_api.auth import Principal, current_user, db_session, require_role
from scrum_api.errors import Problem, forbidden, invalid, not_found
from scrum_api.pagination import Page
from scrum_api.rbac import can_configure, visible_team_ids
from scrum_core import workflow_client
from scrum_core.audit import write_audit
from scrum_core.models import Blocker, BlockerEvent, BlockerEvidence, ReviewItem, User
from scrum_core.models.base import BlockerEventKind, BlockerStatus, ReviewKind, ReviewStatus, Role
from scrum_core.schemas.workflow import BLOCKER_ALERTS_WORKFLOW, BlockerAlertsInput
from scrum_core.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["blockers"])


async def _audit(
    db: AsyncSession, p: Principal, action: str, entity_type: str, entity_id: object, diff: dict[str, Any]
) -> None:
    await write_audit(
        db,
        org_id=p.org_id,
        actor_user_id=p.user_id,
        actor_name=p.display_name,
        ip=p.ip,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        diff=diff,
    )


async def _queue_alerts(p: Principal, team_id: UUID, blocker_ids: list[UUID], key: str) -> None:
    if not blocker_ids or not get_settings().temporal_enabled:
        return
    try:
        await workflow_client.start_job(
            BLOCKER_ALERTS_WORKFLOW,
            BlockerAlertsInput(org_id=p.org_id, team_id=team_id, blocker_ids=blocker_ids),
            id=f"blocker-alerts-{key}",
        )
    except Exception as exc:  # the ledger makes a later retry safe
        log.warning("could not queue blocker alerts %s: %s", key, exc)


def apply_status(b: Blocker, new: BlockerStatus, now: datetime) -> BlockerEventKind | None:
    """Lifecycle transition; returns the event to record (plan §9.3: open → acknowledged → resolved)."""
    old = b.status
    if new == old:
        return None
    b.status = new
    if new == BlockerStatus.resolved:
        b.resolved_at = now
        return BlockerEventKind.resolved
    b.resolved_at = None
    if new == BlockerStatus.acknowledged:
        b.acknowledged_at = now
        return BlockerEventKind.acknowledged if old != BlockerStatus.resolved else BlockerEventKind.reopened
    return BlockerEventKind.reopened if old == BlockerStatus.resolved else None


# ------------------------------------------------------------------------------- blockers


@router.get("/blockers", response_model=S.Paginated[S.BlockerOut])
async def list_blockers(
    team: UUID | None = None,
    status: BlockerStatus | None = None,
    page: Page = Depends(),
    p: Principal = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> S.Paginated[S.BlockerOut]:
    ids = await visible_team_ids(p, db)
    stmt = select(Blocker).where(Blocker.team_id.in_(ids)).order_by(Blocker.first_seen_at.desc())
    if team:
        stmt = stmt.where(Blocker.team_id == team)
    if status:
        stmt = stmt.where(Blocker.status == status)
    rows, nxt = await page.fetch(db, stmt)
    return S.Paginated[S.BlockerOut](items=await P.blockers_out(db, rows), next_cursor=nxt)


async def _blocker(p: Principal, db: AsyncSession, blocker_id: UUID) -> Blocker:
    b = await db.get(Blocker, blocker_id)
    if b is None or b.team_id not in await visible_team_ids(p, db):
        raise Problem(404, "Blocker not found")
    return b


@router.get("/blockers/{blocker_id}", response_model=S.BlockerDetailOut)
async def get_blocker(
    blocker_id: UUID, p: Principal = Depends(current_user), db: AsyncSession = Depends(db_session)
) -> S.BlockerDetailOut:
    return await P.blocker_detail(db, await _blocker(p, db, blocker_id))


@router.patch("/blockers/{blocker_id}", response_model=S.BlockerOut)
async def patch_blocker(
    blocker_id: UUID,
    body: S.BlockerPatch,
    p: Principal = Depends(require_role(Role.org_admin, Role.scrum_lead, Role.member)),
    db: AsyncSession = Depends(db_session),
) -> S.BlockerOut:
    b = await _blocker(p, db, blocker_id)
    now = datetime.now(UTC)
    diff: dict[str, list[object]] = {}
    realert = False
    if "blocked_on_user_id" in body.model_fields_set and body.blocked_on_user_id != b.blocked_on_user_id:
        if not can_configure(p, b.team_id):
            raise forbidden("Only the scrum lead can reassign a blocker.")
        if body.blocked_on_user_id and await db.get(User, body.blocked_on_user_id) is None:
            raise invalid("blocked_on_user_id", "Unknown user")
        diff["blocked_on_user_id"] = [b.blocked_on_user_id, body.blocked_on_user_id]
        b.blocked_on_user_id = body.blocked_on_user_id
        b.alert_held = False
        realert = body.blocked_on_user_id is not None and b.status != BlockerStatus.resolved
    if body.status is not None and body.status != b.status:
        if body.status == BlockerStatus.needs_review:
            raise invalid("status", "needs_review is set by Scrum Bot, not by hand")
        before = b.status
        kind = apply_status(b, body.status, now)
        diff["status"] = [before, body.status]
        if kind:
            db.add(
                BlockerEvent(
                    org_id=p.org_id,
                    blocker_id=b.id,
                    at=now,
                    kind=kind,
                    actor_name=p.display_name,
                    note="Updated from blockers board",
                )
            )
    if diff:
        action = f"blocker.{body.status}" if body.status else "blocker.reassigned"
        await _audit(db, p, action, "blocker", b.id, diff)
    if realert:
        await db.flush()
        await _queue_alerts(p, b.team_id, [b.id], f"{b.id}-{int(now.timestamp())}")
    return (await P.blockers_out(db, [b]))[0]


# ------------------------------------------------------------------------------- review queue

LEADS = (Role.org_admin, Role.scrum_lead)


@router.get("/review-items", response_model=S.Paginated[S.ReviewItemOut])
async def list_review(
    kind: ReviewKind | None = None,
    status: str = Query(default="pending"),
    page: Page = Depends(),
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> S.Paginated[S.ReviewItemOut]:
    ids = await visible_team_ids(p, db) if p.role == Role.scrum_lead else None
    stmt = select(ReviewItem).order_by(ReviewItem.created_at.desc())
    if ids is not None:
        stmt = stmt.where(ReviewItem.team_id.in_(ids))
    if kind:
        stmt = stmt.where(ReviewItem.kind == kind)
    if status != "all":
        try:
            stmt = stmt.where(ReviewItem.status == ReviewStatus(status))
        except ValueError as exc:
            raise invalid("status", "Use pending, approved, rejected or all") from exc
    rows, nxt = await page.fetch(db, stmt)
    return S.Paginated[S.ReviewItemOut](items=await P.review_out(db, rows), next_cursor=nxt)


async def _review(p: Principal, db: AsyncSession, review_id: UUID) -> ReviewItem:
    r = await db.get(ReviewItem, review_id)
    if r is None or (r.team_id and r.team_id not in await visible_team_ids(p, db)):
        raise not_found("Review item")
    if r.team_id and not can_configure(p, r.team_id):
        raise forbidden("Only the team's scrum lead can decide this.")
    if r.status != ReviewStatus.pending:
        raise Problem(409, "Already decided")
    return r


async def _merge_blocker(db: AsyncSession, p: Principal, new_id: UUID, into: Blocker) -> None:
    """Fold a just-created blocker into an existing one (same blocker mentioned again)."""
    new = await db.get(Blocker, new_id)
    if new is None or new.id == into.id:
        return
    await db.execute(update(BlockerEvidence).where(BlockerEvidence.blocker_id == new.id).values(blocker_id=into.id))
    into.last_seen_session_id = new.last_seen_session_id or into.last_seen_session_id
    into.last_seen_at = new.first_seen_at
    if into.status == BlockerStatus.resolved:
        into.status, into.resolved_at = BlockerStatus.open, None
        db.add(
            BlockerEvent(
                org_id=p.org_id,
                blocker_id=into.id,
                at=datetime.now(UTC),
                kind=BlockerEventKind.reopened,
                actor_name=p.display_name,
                note="Reopened: mentioned again (review queue)",
            )
        )
    db.add(
        BlockerEvent(
            org_id=p.org_id,
            blocker_id=into.id,
            at=new.first_seen_at,
            kind=BlockerEventKind.mentioned,
            actor_name=p.display_name,
            note="Matched to existing blocker by reviewer",
            session_id=new.first_seen_session_id,
        )
    )
    await db.delete(new)


@router.post("/review-items/{review_id}/approve", response_model=S.ReviewItemOut)
async def approve(
    review_id: UUID,
    body: S.ApproveIn,
    p: Principal = Depends(require_role(*LEADS)),
    db: AsyncSession = Depends(db_session),
) -> S.ReviewItemOut:
    r = await _review(p, db, review_id)
    cand = next((c for c in r.payload.get("candidates", []) if c["id"] == body.candidate_id), None)
    if cand is None:
        raise Problem(422, "Validation failed", "Pick one of the candidates.")
    ctx = r.payload.get("context", {})
    alerts: list[UUID] = []

    if r.kind == ReviewKind.person_match:
        if blocker_id := ctx.get("blocker_id"):
            b = await db.get(Blocker, UUID(blocker_id))
            if b is not None:
                b.blocked_on_user_id = UUID(cand["id"])
                b.alert_held = False
                if b.status == BlockerStatus.needs_review:
                    b.status = BlockerStatus.open
                alerts.append(b.id)
        # Learn the spoken phrase as an alias so the next standup resolves it automatically.
        person = await db.get(User, UUID(cand["id"]))
        phrase = str(r.payload.get("raw_phrase", "")).strip()
        if person and phrase and phrase.lower() != person.display_name.lower() and phrase not in (person.aliases or []):
            person.aliases = [*(person.aliases or []), phrase]
    elif r.kind == ReviewKind.blocker_match:
        new_id = ctx.get("new_blocker_id")
        if body.candidate_id == "new":
            if new_id and (b := await db.get(Blocker, UUID(new_id))) is not None:
                if b.status == BlockerStatus.needs_review:
                    b.status = BlockerStatus.open
                b.alert_held = False
                alerts.append(b.id)
        else:
            existing = await db.get(Blocker, UUID(body.candidate_id))
            if existing is None:
                raise Problem(409, "Blocker no longer exists")
            if new_id:
                await _merge_blocker(db, p, UUID(new_id), existing)
    elif r.kind == ReviewKind.pm_writeback:
        pm = await registry.pm_for_org(db, p.org_id)
        if pm is None:
            raise Problem(409, "PM tool not connected", "Connect Jira before approving write-backs.")
        await pm.propose_update(
            ctx["ticket_key"], TicketChange(transition_to=ctx.get("transition_to"), comment=ctx.get("comment"))
        )

    r.status, r.decided_by, r.decided_at = ReviewStatus.approved, p.user_id, datetime.now(UTC)
    await _audit(db, p, "review.approved", "review_item", r.id, {"kind": r.kind, "choice": cand["label"]})
    await db.flush()
    if alerts and r.team_id:
        await _queue_alerts(p, r.team_id, alerts, f"review-{r.id}")
    return (await P.review_out(db, [r]))[0]


@router.post("/review-items/{review_id}/reject", response_model=S.ReviewItemOut)
async def reject(
    review_id: UUID, p: Principal = Depends(require_role(*LEADS)), db: AsyncSession = Depends(db_session)
) -> S.ReviewItemOut:
    r = await _review(p, db, review_id)
    ctx = r.payload.get("context", {})
    alerts: list[UUID] = []
    if r.kind == ReviewKind.person_match and (bid := ctx.get("blocker_id")):
        # None of the candidates: keep the blocker unassigned (shown in the report, no alert).
        if (b := await db.get(Blocker, UUID(bid))) is not None and b.status == BlockerStatus.needs_review:
            b.status, b.alert_held = BlockerStatus.open, False
    elif r.kind == ReviewKind.blocker_match and (nid := ctx.get("new_blocker_id")):
        # Not a repeat: it's a new blocker after all.
        if (b := await db.get(Blocker, UUID(nid))) is not None:
            b.status, b.alert_held = BlockerStatus.open, False
            alerts.append(b.id)
    r.status, r.decided_by, r.decided_at = ReviewStatus.rejected, p.user_id, datetime.now(UTC)
    await _audit(db, p, "review.rejected", "review_item", r.id, {"kind": r.kind})
    await db.flush()
    if alerts and r.team_id:
        await _queue_alerts(p, r.team_id, alerts, f"review-{r.id}")
    return (await P.review_out(db, [r]))[0]
