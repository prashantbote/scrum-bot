from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


class MeetingNotFound(Exception):
    """Non-retryable: the meeting URL is wrong or the room no longer exists."""


@dataclass
class AudioFrame:
    pcm: bytes  # 16-bit little-endian mono PCM
    sample_rate: int = 16_000
    speaker_id: str | None = None  # provider hint: participant identity (per-speaker streams on LiveKit)
    # Fake provider only: the words carried by this frame and the utterance boundary.
    text: str | None = None
    end_of_utterance: bool = False

    @property
    def duration_ms(self) -> int:
        if self.text is not None and not self.pcm:
            return speech_ms(self.text)
        return int(len(self.pcm) / 2 / self.sample_rate * 1000)


@dataclass
class Participant:
    id: str
    name: str
    email: str | None = None
    is_speaking: bool = False


@dataclass
class CallHandle:
    call_id: str
    join_url: str
    provider: str
    data: dict[str, Any] = field(default_factory=dict)


class MeetingProvider(Protocol):
    name: str
    #: False for the fake provider: the voice pipeline then runs on a virtual clock.
    realtime: bool

    async def join(self, join_url: str, display_name: str) -> CallHandle: ...
    async def set_recording_status(self, call: CallHandle, recording: bool) -> None: ...
    def audio_in(self, call: CallHandle) -> AsyncIterator[AudioFrame]: ...
    async def audio_out(self, call: CallHandle, frame: AudioFrame) -> None: ...
    async def participants(self, call: CallHandle) -> list[Participant]: ...
    async def leave(self, call: CallHandle) -> None: ...


def speech_ms(text: str) -> int:
    """Rough spoken duration of a line (≈ 16 characters per second)."""
    return min(9000, max(1600, len(text) * 62))
