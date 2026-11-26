"""Text-to-speech. Open-source default: Piper (fast local neural TTS, ONNX)."""

from __future__ import annotations

import asyncio
import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scrum_adapters.meeting.base import speech_ms


@dataclass
class Speech:
    pcm: bytes
    sample_rate: int
    text: str

    @property
    def duration_ms(self) -> int:
        if not self.pcm:
            return speech_ms(self.text)
        return int(len(self.pcm) / 2 / self.sample_rate * 1000)


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str) -> Speech: ...


class FakeTTS:
    name = "fake"

    async def synthesize(self, text: str) -> Speech:
        return Speech(pcm=b"", sample_rate=16_000, text=text)


class PiperTTS:
    """Piper voice loaded from ``<voice_dir>/<voice>.onnx`` (+ ``.onnx.json``).

    Download voices with ``python -m piper.download_voices en_US-lessac-medium --data-dir .data/piper``
    (``make voices``).
    """

    name = "piper"

    def __init__(self, voice: str, voice_dir: str) -> None:
        self._path = Path(voice_dir) / f"{voice}.onnx"
        self._voice: Any = None

    def _load(self) -> Any:
        if self._voice is None:
            from piper import PiperVoice

            if not self._path.exists():
                raise FileNotFoundError(f"Piper voice not found: {self._path} (run `make voices`)")
            self._voice = PiperVoice.load(str(self._path))
        return self._voice

    def _run(self, text: str) -> Speech:
        voice = self._load()
        # piper-tts >= 1.3 streams AudioChunk objects; older versions write a WAV file.
        if hasattr(voice, "synthesize_wav"):
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                voice.synthesize_wav(text, wav)
            buf.seek(0)
            with wave.open(buf, "rb") as wav:
                return Speech(pcm=wav.readframes(wav.getnframes()), sample_rate=wav.getframerate(), text=text)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice.synthesize(text, wav)
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            return Speech(pcm=wav.readframes(wav.getnframes()), sample_rate=wav.getframerate(), text=text)

    async def synthesize(self, text: str) -> Speech:
        return await asyncio.to_thread(self._run, text)
