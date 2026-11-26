"""Speech-to-text. Open-source default: faster-whisper (CTranslate2 Whisper), CPU int8 friendly."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Transcription:
    text: str
    confidence: float


class STTProvider(Protocol):
    name: str

    async def transcribe(
        self, pcm: bytes, sample_rate: int, *, vocabulary: list[str], text_hint: str | None = None
    ) -> Transcription: ...


class FakeSTT:
    """Returns the text carried by fake frames (FakeMeetingProvider)."""

    name = "fake"

    async def transcribe(
        self, pcm: bytes, sample_rate: int, *, vocabulary: list[str], text_hint: str | None = None
    ) -> Transcription:
        return Transcription(text=(text_hint or "").strip(), confidence=0.92)


class WhisperSTT:
    """faster-whisper with vocabulary biasing through ``initial_prompt`` (names, ticket prefixes, tech terms)."""

    name = "faster-whisper"

    def __init__(self, model: str = "base.en", device: str = "cpu", compute_type: str = "int8") -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_name, device=self._device, compute_type=self._compute_type)
        return self._model

    def _run(self, pcm: bytes, sample_rate: int, vocabulary: list[str]) -> Transcription:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16_000:
            n_out = int(len(audio) * 16_000 / sample_rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio).astype(np.float32)
        prompt = ("Standup meeting. Names and terms: " + ", ".join(vocabulary[:80])) if vocabulary else None
        segments, _info = self._load().transcribe(
            audio, language="en", beam_size=1, vad_filter=True, initial_prompt=prompt, condition_on_previous_text=False
        )
        segs = list(segments)
        text = snap_to_vocabulary(" ".join(s.text.strip() for s in segs).strip(), vocabulary)
        if not segs:
            return Transcription(text="", confidence=0.0)
        avg = sum(s.avg_logprob for s in segs) / len(segs)
        return Transcription(text=text, confidence=round(min(1.0, math.exp(avg)), 3))

    async def transcribe(
        self, pcm: bytes, sample_rate: int, *, vocabulary: list[str], text_hint: str | None = None
    ) -> Transcription:
        if not pcm:
            return Transcription(text=(text_hint or "").strip(), confidence=0.9)
        return await asyncio.to_thread(self._run, pcm, sample_rate, vocabulary)


_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")


def snap_to_vocabulary(text: str, vocabulary: list[str], *, threshold: int = 75) -> str:
    """Correct near-miss proper nouns against the team vocabulary ("Anit" → "Amit").

    Only capitalized words are considered (Whisper capitalizes names), the first letter must match and
    lengths may differ by at most one character, so ordinary words are never rewritten.
    """
    from rapidfuzz import fuzz

    names = {w for v in vocabulary for w in re.findall(r"[A-Z][a-z]{2,}", v)}
    if not names:
        return text

    def fix(m: re.Match[str]) -> str:
        word = m.group(0)
        if word in names:
            return word
        best = max(names, key=lambda n: fuzz.ratio(word, n))
        ok = best[0] == word[0] and abs(len(best) - len(word)) <= 1 and fuzz.ratio(word, best) >= threshold
        return best if ok else word

    return _WORD.sub(fix, text)
