"""Scripted meeting for tests and demo mode (``SCRUM_MEETING_PROVIDER=fake``).

Participants "speak" scripted lines in response to the bot: when the bot addresses someone by
first name they become the current speaker; each bot question pops their next answer, a
confirmation ("…Correct?") gets their confirmation line.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from scrum_adapters.meeting.base import AudioFrame, CallHandle, MeetingNotFound, Participant

CONFIRM_RE = re.compile(r"\b(correct|right)\?\s*$", re.I)


@dataclass
class ScriptedParticipant:
    user_id: str
    name: str
    email: str
    present: bool = True
    answers: list[str] = field(default_factory=list)
    confirm: str = "Yes, that's right."
    #: Joins only after this many bot utterances (late joiner); 0 = from the start.
    joins_after: int = 0

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


@dataclass
class FakeCall:
    participants: list[ScriptedParticipant]
    inbox: asyncio.Queue[AudioFrame] = field(default_factory=asyncio.Queue)
    bot_lines: list[str] = field(default_factory=list)
    current: ScriptedParticipant | None = None
    recording: bool = False
    left: bool = False


class FakeMeetingProvider:
    name = "fake"
    realtime = False

    def __init__(self, participants: list[ScriptedParticipant] | None = None, *, fail_join: bool = False) -> None:
        self._participants = participants or []
        self._fail_join = fail_join
        self.calls: dict[str, FakeCall] = {}

    @property
    def has_script(self) -> bool:
        return bool(self._participants)

    def set_script(self, participants: list[ScriptedParticipant]) -> None:
        self._participants = participants

    async def join(self, join_url: str, display_name: str) -> CallHandle:
        if self._fail_join or not join_url:
            raise MeetingNotFound(join_url)
        call_id = f"fake-{len(self.calls) + 1}"
        self.calls[call_id] = FakeCall(participants=[*self._participants])
        return CallHandle(call_id=call_id, join_url=join_url, provider=self.name)

    def _call(self, call: CallHandle) -> FakeCall:
        return self.calls[call.call_id]

    async def set_recording_status(self, call: CallHandle, recording: bool) -> None:
        self._call(call).recording = recording

    async def audio_in(self, call: CallHandle) -> AsyncIterator[AudioFrame]:
        fc = self._call(call)
        while not fc.left:
            yield await fc.inbox.get()

    async def audio_out(self, call: CallHandle, frame: AudioFrame) -> None:
        fc = self._call(call)
        if frame.text is None or not frame.end_of_utterance:
            return
        text = frame.text
        fc.bot_lines.append(text)
        present = self._present(fc)
        # Who is being addressed? The bot calls on people as "Name, …" at the start of a sentence.
        best = -1
        for p in present:
            for m in re.finditer(rf"(?:^|[.!?]\s+){re.escape(p.first_name)},", text):
                if m.start() > best:
                    best, fc.current = m.start(), p
        cur = fc.current
        if cur is None or cur not in present:
            return
        if text.startswith("Thanks") and not text.rstrip().endswith("?"):
            return  # hand-over line ("Thanks, Rahul. Amit, your turn.") handled on the next question
        if CONFIRM_RE.search(text):
            reply = cur.confirm
        elif text.rstrip().endswith("?"):
            reply = cur.answers.pop(0) if cur.answers else "That's all from me."
        else:
            return
        await fc.inbox.put(AudioFrame(pcm=b"", speaker_id=cur.email, text=reply, end_of_utterance=True))

    def _present(self, fc: FakeCall) -> list[ScriptedParticipant]:
        n = len(fc.bot_lines)
        return [p for p in fc.participants if p.present and n >= p.joins_after]

    async def participants(self, call: CallHandle) -> list[Participant]:
        fc = self._call(call)
        return [Participant(id=p.email, name=p.name, email=p.email) for p in self._present(fc)]

    async def leave(self, call: CallHandle) -> None:
        self._call(call).left = True
