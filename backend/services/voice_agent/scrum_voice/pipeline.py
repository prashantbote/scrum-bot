"""Turn-based audio pipeline over any MeetingProvider (plan §8.1).

    MeetingProvider.audio_in ─► EnergyVAD ─► STT (faster-whisper, vocabulary prompt) ─► controller
    MeetingProvider.audio_out ◄─ TTS (Piper) ◄──────────────────────────────────────────┘

The agent drives turn-taking (it calls on people by name), so a half-duplex pipeline is enough:
speak, then listen until end of speech. Fake providers run on a virtual clock so transcripts get
realistic, deterministic timestamps in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from scrum_adapters.meeting.base import AudioFrame, CallHandle, MeetingProvider
from scrum_adapters.stt import STTProvider
from scrum_adapters.tts import TTSProvider
from scrum_core.schemas.workflow import MemberCtx
from scrum_voice.vad import EnergyVAD

GAP_MS = 700


@dataclass
class Heard:
    text: str
    start_ms: int
    end_ms: int
    confidence: float
    speaker_id: str | None


class CallIO:
    def __init__(
        self,
        provider: MeetingProvider,
        call: CallHandle,
        stt: STTProvider,
        tts: TTSProvider,
        *,
        vocabulary: list[str],
        start_ms: int = 0,
    ) -> None:
        self.provider, self.call, self.stt, self.tts = provider, call, stt, tts
        self.vocabulary = vocabulary
        self._virtual = start_ms
        self._t0 = time.monotonic() - start_ms / 1000
        self._queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None

    # -- clock --------------------------------------------------------------------------
    def now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000) if self.provider.realtime else self._virtual

    def _advance(self, ms: int) -> None:
        if not self.provider.realtime:
            self._virtual += ms

    # -- lifecycle ----------------------------------------------------------------------
    async def start(self) -> None:
        async def read() -> None:
            async for frame in self.provider.audio_in(self.call):
                await self._queue.put(frame)

        self._reader = asyncio.create_task(read())

    async def stop(self) -> None:
        if self._reader:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader

    # -- speak / listen -----------------------------------------------------------------
    async def say(self, text: str) -> tuple[int, int]:
        speech = await self.tts.synthesize(text)
        start = self.now_ms()
        await self.provider.audio_out(
            self.call, AudioFrame(pcm=speech.pcm, sample_rate=speech.sample_rate, text=text, end_of_utterance=True)
        )
        if self.provider.realtime:
            await asyncio.sleep(speech.duration_ms / 1000)  # audio is playing out in the room
            while not self._queue.empty():  # drop what we heard of ourselves / room noise meanwhile
                self._queue.get_nowait()
        else:
            self._advance(speech.duration_ms)
        end = start + speech.duration_ms
        self._advance(GAP_MS)
        return start, end

    async def listen(self, expected: MemberCtx | None, timeout_s: float = 12.0) -> Heard | None:
        vad = EnergyVAD()
        deadline = time.monotonic() + timeout_s
        start_ms: int | None = None
        speaker: str | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except TimeoutError:
                return None
            if frame.text is not None:  # fake provider: whole utterance in one frame
                start = self.now_ms()
                self._advance(frame.duration_ms)
                t = await self.stt.transcribe(b"", frame.sample_rate, vocabulary=self.vocabulary, text_hint=frame.text)
                end = start + frame.duration_ms
                self._advance(GAP_MS)
                return Heard(t.text, start, end, t.confidence, frame.speaker_id)
            if start_ms is None:
                start_ms = self.now_ms()
            speaker = speaker or frame.speaker_id
            self._advance(frame.duration_ms)  # virtual clock follows the audio (non-realtime providers)
            utterance = vad.feed(frame.pcm, frame.duration_ms)
            if utterance is not None:
                t = await self.stt.transcribe(utterance, frame.sample_rate, vocabulary=self.vocabulary)
                if t.text:
                    return Heard(t.text, start_ms, self.now_ms(), t.confidence, speaker)
                start_ms, speaker = None, None
                deadline = max(deadline, time.monotonic() + 3)

    async def present_member_ids(self, members: list[MemberCtx]) -> set[str]:
        parts = await self.provider.participants(self.call)
        ids: set[str] = set()
        for m in members:
            for p in parts:
                if (
                    (p.email and p.email.lower() == m.email.lower())
                    or p.id.lower() == m.email.lower()
                    or p.name.lower() == m.display_name.lower()
                ):
                    ids.add(str(m.user_id))
        return ids
