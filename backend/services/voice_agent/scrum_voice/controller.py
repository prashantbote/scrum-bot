"""The standup conversation (plan §8.2).

    INTRO ─► for each member in speaking order:
               CALL_ON(name) ─► ASK(q_i) ─► LISTEN ─► JUDGE ─(vague, followups < max)─► FOLLOW_UP ─► LISTEN …
               ─► [stale blocker? "Is that resolved now?"] ─► CONFIRM(one-line summary) ─► yes | AMEND once
            ─► retry members who were missing ─► OUTRO ─► leave()

Speaker attribution: the agent calls on people by name, so each answer is tagged with the expected
speaker; a provider speaker hint that disagrees lowers ``speaker_confidence``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from scrum_core.schemas.workflow import MemberCtx, QuestionCtx, StandupContext
from scrum_voice.judge import TurnJudge, is_affirmative, summarize
from scrum_voice.pipeline import CallIO
from scrum_voice.transcript import Segment, TranscriptWriter

log = logging.getLogger(__name__)
BOT = "Scrum Bot"


@dataclass
class Budget:
    total_seconds: int
    min_seconds: int
    max_seconds: int

    def per_person(self, n_present: int) -> int:
        return max(self.min_seconds, min(self.max_seconds, self.total_seconds // max(1, n_present)))


@dataclass
class Progress:
    """Heartbeat details: lets a retried activity resume where the call dropped (plan §8.2)."""

    done_member_ids: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    attended: list[str] = field(default_factory=list)
    resolved_blockers: list[str] = field(default_factory=list)


class StandupController:
    def __init__(
        self,
        ctx: StandupContext,
        io: CallIO,
        judge: TurnJudge,
        writer: TranscriptWriter,
        budget: Budget,
        heartbeat: Callable[[Progress], None] = lambda _p: None,
        *,
        listen_timeout_s: float = 12.0,
        progress: Progress | None = None,
    ) -> None:
        self.ctx, self.io, self.judge, self.writer, self.budget = ctx, io, judge, writer, budget
        self.heartbeat = heartbeat
        self.listen_timeout_s = listen_timeout_s
        self.progress = progress or Progress()
        self._last_name: str | None = None

    # ------------------------------------------------------------------ primitives
    async def say(self, text: str, question: QuestionCtx | None = None) -> None:
        start, end = await self.io.say(text)
        self.writer.add(Segment(None, BOT, question.id if question else None, start, end, text))

    async def hear(self, m: MemberCtx, question: QuestionCtx | None) -> str | None:
        heard = await self.io.listen(m, self.listen_timeout_s)
        if heard is None or not heard.text.strip():
            return None
        speaker_ok = heard.speaker_id is None or heard.speaker_id.lower() in (m.email.lower(), str(m.user_id))
        self.writer.add(
            Segment(
                m.user_id,
                m.display_name,
                question.id if question else None,
                heard.start_ms,
                heard.end_ms,
                heard.text,
                heard.confidence,
                1.0 if speaker_ok else 0.4,
            )
        )
        return heard.text

    # ------------------------------------------------------------------ flow
    def _opener(self, m: MemberCtx, q: QuestionCtx) -> str:
        thanks = f"Thanks, {self._last_name}. " if self._last_name else ""
        q_text = q.text[0].lower() + q.text[1:] if q.text else q.text
        if m.open_tickets and q.position == 1:
            t = m.open_tickets[0]
            return f"{thanks}{m.first_name}, you had {t.key}, {t.summary}, in progress. {q.text}"
        return f"{thanks}{m.first_name}, {q_text}"

    async def run_member(self, m: MemberCtx, n_present: int) -> bool:
        budget_ms = self.budget.per_person(n_present) * 1000
        started = self.io.now_ms()
        answers: list[tuple[QuestionCtx, str]] = []
        spoke = False
        for i, q in enumerate(self.ctx.questions):
            if self.io.now_ms() - started > budget_ms:
                await self.say("We're short on time, so let's capture the rest async. Thanks!")
                break
            await self.say(self._opener(m, q) if i == 0 else q.text, q)
            answer = await self.hear(m, q)
            if answer is None:
                if i == 0:
                    await self.say(f"{m.first_name}, I didn't catch that — I'll come back to you.")
                    return False
                continue
            spoke = True
            followups = 0
            pieces = [answer]
            while True:
                # Judge the latest reply only: a good follow-up answer settles an earlier vague one.
                d = await self.judge.judge(q, pieces[-1], followups, m)
                if d.action != "follow_up" or not d.utterance or self.io.now_ms() - started > budget_ms:
                    break
                await self.say(d.utterance, q)
                followups += 1
                more = await self.hear(m, q)
                if more is None:
                    break
                pieces.append(more)
            answers.append((q, max(pieces, key=len)))  # read back the most informative piece

        for sb in m.stale_blockers[:1]:
            await self.say(f"{m.first_name}, earlier you mentioned: {sb.description}. Is that resolved now?")
            reply = await self.hear(m, None)
            if reply and is_affirmative(reply):
                self.progress.resolved_blockers.append(str(sb.id))

        if spoke:
            await self.say(f"So: {summarize(m, answers)}. Correct?")
            reply = await self.hear(m, None)
            if reply and not is_affirmative(reply):
                await self.say("Thanks — I've noted that correction. Anything else to change?")
                again = await self.hear(m, None)
                if again and not is_affirmative(again) and not again.lower().startswith("no"):
                    await self.say("Got it, noted.")
        self._last_name = m.first_name
        return spoke

    async def run(self) -> Progress:
        p = self.progress
        members = self.ctx.members
        if not p.done_member_ids:
            first = next(iter(members), None)
            intro = f"Good morning, everyone! {self.ctx.consent_text}"
            await self.say(intro + (" I'll go through the team one by one." if first else ""))
        present = await self.io.present_member_ids(members)
        missing: list[MemberCtx] = []
        for m in members:
            if str(m.user_id) in p.done_member_ids:
                continue
            if str(m.user_id) not in present:
                missing.append(m)
                continue
            if await self.run_member(m, max(1, len(present))):
                p.attended.append(str(m.user_id))
            else:
                missing.append(m)
            p.done_member_ids.append(str(m.user_id))
            p.elapsed_ms = self.io.now_ms()
            await self.writer.flush()
            self.heartbeat(p)

        # Absence detection: one more try at the end for people who weren't there at their turn.
        if missing:
            present = await self.io.present_member_ids(members)
            for m in missing:
                if str(m.user_id) in present and str(m.user_id) not in p.attended:
                    await self.say(f"{m.first_name}, I see you've joined.")
                    if await self.run_member(m, max(1, len(present))):
                        p.attended.append(str(m.user_id))
                if str(m.user_id) not in p.done_member_ids:
                    p.done_member_ids.append(str(m.user_id))
                await self.writer.flush()
                self.heartbeat(p)

        absent = [m.first_name for m in members if str(m.user_id) not in p.attended]
        thanks = f"Thanks, {self._last_name}. " if self._last_name else ""
        follow = f"I'll send {' and '.join(absent)} a quick check-in. " if absent else ""
        await self.say(f"{thanks}That's everyone. {follow}Have a productive day!")
        p.elapsed_ms = self.io.now_ms()
        await self.writer.flush()
        return p
