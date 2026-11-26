"""Utterance segmentation for real audio: adaptive energy VAD with hangover.

Whisper then runs its own Silero VAD (``vad_filter=True``) on each utterance to trim silence, so this
stage only needs to find "someone started talking" and "they stopped for ~0.7 s".
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field


def rms_pcm16(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n)


@dataclass
class EnergyVAD:
    end_silence_ms: int = 700
    min_speech_ms: int = 200
    max_utterance_ms: int = 30_000
    threshold_ratio: float = 3.0
    floor: float = 150.0
    _noise: float = 200.0
    _speaking: bool = False
    _speech_ms: int = 0
    _silence_ms: int = 0
    _buf: bytearray = field(default_factory=bytearray)

    def reset(self) -> None:
        self._speaking, self._speech_ms, self._silence_ms = False, 0, 0
        self._buf = bytearray()

    def feed(self, pcm: bytes, duration_ms: int) -> bytes | None:
        """Feed one frame; returns the full utterance PCM when an utterance ends."""
        level = rms_pcm16(pcm)
        voiced = level > max(self.floor, self._noise * self.threshold_ratio)
        if not voiced and not self._speaking:
            self._noise = 0.95 * self._noise + 0.05 * level  # track background noise
        if voiced:
            self._speaking = True
            self._silence_ms = 0
        if self._speaking:
            self._buf.extend(pcm)
            self._speech_ms += duration_ms
            if not voiced:
                self._silence_ms += duration_ms
            if (
                self._silence_ms >= self.end_silence_ms and self._speech_ms - self._silence_ms >= self.min_speech_ms
            ) or self._speech_ms >= self.max_utterance_ms:
                out = bytes(self._buf)
                self.reset()
                return out
            if self._silence_ms >= self.end_silence_ms:  # too short: a click or cough
                self.reset()
        return None
