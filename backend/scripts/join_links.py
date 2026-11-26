"""Print browser join links for a team's standup room on the local LiveKit server.

Lets you talk to Scrum Bot with your own microphone — no Teams or company account involved.
Each link signs you in to the room *as* a team member (identity = their email, which is how the bot
recognises who is present).

    uv run python scripts/join_links.py --team Payments
    uv run python scripts/join_links.py --team Payments --member u-rahul

Open a link in Chrome, allow the microphone, then click "Run now" on the team's Schedule page
(worker started with SCRUM_MEETING_PROVIDER=livekit SCRUM_STT_PROVIDER=whisper SCRUM_TTS_PROVIDER=piper).
"""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import quote

from sqlalchemy import func, select

from scrum_adapters.meeting.livekit import mint_token, room_from_url
from scrum_core.db import dispose_engines, owner_session
from scrum_core.models import Schedule, Team, TeamMember, User
from scrum_core.settings import get_settings

MEET = "https://meet.livekit.io/custom"


async def main(team_name: str, member: str | None) -> None:
    s = get_settings()
    async with owner_session() as db:  # local dev helper: owner role reads across the seeded org
        team = (await db.execute(select(Team).where(func.lower(Team.name) == team_name.lower()))).scalars().first()
        if team is None:
            raise SystemExit(f"No team named {team_name!r}. Run scripts/seed.py first.")
        sched = (await db.execute(select(Schedule).where(Schedule.team_id == team.id))).scalar_one_or_none()
        if sched is None or not sched.join_url:
            raise SystemExit("Team has no schedule yet: save one on the Schedule page first.")
        room = room_from_url(sched.join_url)
        stmt = (
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team.id)
            .order_by(TeamMember.speaking_order)
        )
        if member:
            stmt = stmt.where(User.idp_subject == member)
        users = (await db.execute(stmt)).scalars().all()
    if not users:
        raise SystemExit("No matching members.")
    secret = s.livekit_api_secret.get_secret_value()
    print(f"Room {room} on {s.livekit_url}\n")
    for u in users:
        token = mint_token(s.livekit_api_key, secret, room=room, identity=u.email, name=u.display_name)
        print(
            f"{u.display_name} ({u.idp_subject}):\n  {MEET}?liveKitUrl={quote(s.livekit_url, safe='')}&token={token}\n"
        )
    await dispose_engines()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", default="Payments")
    ap.add_argument("--member", help="persona key, e.g. u-rahul (default: every member)")
    args = ap.parse_args()
    asyncio.run(main(args.team, args.member))
