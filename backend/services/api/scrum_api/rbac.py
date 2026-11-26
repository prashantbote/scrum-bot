"""Team scoping on top of roles (plan §6.1 capability matrix)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_api.auth import Principal
from scrum_api.errors import Problem, forbidden
from scrum_core.models import StandupSession, Team
from scrum_core.models.base import Role


async def visible_team_ids(p: Principal, db: AsyncSession) -> list[UUID]:
    """Org admins and viewers see every team; leads and members see the teams they lead or belong to."""
    if p.role in (Role.org_admin, Role.viewer):
        return list((await db.execute(select(Team.id))).scalars().all())
    return list(dict.fromkeys([*p.lead_team_ids, *p.member_team_ids]))


def can_configure(p: Principal, team_id: UUID) -> bool:
    return p.role == Role.org_admin or (p.role == Role.scrum_lead and team_id in p.lead_team_ids)


def require_configure(p: Principal, team_id: UUID) -> None:
    if not can_configure(p, team_id):
        raise forbidden("Only the team's scrum lead or an org admin can change this.")


async def team_or_404(p: Principal, db: AsyncSession, team_id: UUID) -> Team:
    team = await db.get(Team, team_id)
    if team is None or team.id not in await visible_team_ids(p, db):
        raise Problem(404, "Team not found")
    return team


async def session_or_404(p: Principal, db: AsyncSession, session_id: UUID) -> StandupSession:
    s = await db.get(StandupSession, session_id)
    if s is None or s.team_id not in await visible_team_ids(p, db):
        raise Problem(404, "Session not found")
    return s


def individual_scope(p: Principal, team_id: UUID) -> str:
    """'all' | 'self' | 'none' — who may see individual-level data for a team."""
    if p.role == Role.org_admin or (p.role == Role.scrum_lead and team_id in p.lead_team_ids):
        return "all"
    if p.role in (Role.member, Role.scrum_lead):
        return "self"
    return "none"
