"""Scripted participants for demo mode (``SCRUM_MEETING_PROVIDER=fake``): plausible, deterministic answers
built from each member's open tickets, so "Run now" in the UI produces a realistic standup end to end."""

from __future__ import annotations

import hashlib
from datetime import date

from scrum_adapters.meeting.fake import ScriptedParticipant
from scrum_core.schemas.workflow import StandupContext


def _h(*parts: object) -> int:
    return int.from_bytes(hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest(), "little")


def demo_participants(ctx: StandupContext) -> list[ScriptedParticipant]:
    out = []
    run = ctx.run_date or date.today()
    names = [m.first_name for m in ctx.members]
    for i, m in enumerate(ctx.members):
        h = _h(m.user_id, run)
        tickets = m.open_tickets or []
        a = tickets[0] if tickets else None
        b = tickets[1] if len(tickets) > 1 else a
        done = (
            f"I finished the {a.summary.lower()} changes for {a.key} and wrote tests."
            if a
            else "I wrapped up code reviews and fixed two small bugs."
        )
        today = (
            f"Today I'll continue on {b.key}, the {b.summary.lower()}."
            if b
            else "Today I'll pick up the next ticket from the sprint board."
        )
        if h % 5 == 0 and len(names) > 1:
            other = names[(i + 1) % len(names)]
            blockers = f"I'm waiting on {other} for a review, so I'm a bit stuck."
        elif h % 7 == 0:
            blockers = "Staging is failing on deploy, so I can't verify my change."
        else:
            blockers = "No blockers today."
        answers = [done, today, blockers][: len(ctx.questions)] + ["Nothing else."] * max(0, len(ctx.questions) - 3)
        out.append(
            ScriptedParticipant(
                user_id=str(m.user_id), name=m.display_name, email=m.email, present=h % 11 != 0, answers=answers
            )
        )
    return out
