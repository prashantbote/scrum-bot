"""Real open-source speech stack: Piper TTS → energy VAD → faster-whisper STT → controller.

Needs ``uv sync --extra voice`` and the Piper voice (``make voices``); Whisper ``base.en`` downloads on
first run. Run with ``pytest -m voice_models``.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from scrum_adapters.meeting.base import AudioFrame, CallHandle, Participant
from scrum_adapters.meeting.fake import CONFIRM_RE
from scrum_core.settings import get_settings

pytestmark = pytest.mark.voice_models

VOICE_DIR = Path(__file__).resolve().parents[2] / ".data" / "piper"


@pytest.fixture(scope="module")
def speech():
    pytest.importorskip("faster_whisper")
    pytest.importorskip("piper")
    if not (VOICE_DIR / f"{get_settings().piper_voice}.onnx").exists():
        pytest.skip("Piper voice not downloaded (make voices)")
    from scrum_adapters.stt import WhisperSTT
    from scrum_adapters.tts import PiperTTS

    return PiperTTS(get_settings().piper_voice, str(VOICE_DIR)), WhisperSTT("base.en")


def frames_of(pcm: bytes, rate: int, speaker: str) -> list[AudioFrame]:
    from scrum_adapters.meeting.livekit import resample_pcm16

    pcm16 = resample_pcm16(pcm, rate, 16_000) + b"\x00" * 16_000 * 2  # + 1 s of silence (end of turn)
    step = 16_000 * 20 // 1000 * 2
    return [
        AudioFrame(pcm=pcm16[i : i + step], sample_rate=16_000, speaker_id=speaker) for i in range(0, len(pcm16), step)
    ]


async def test_piper_to_whisper_round_trip(speech):
    tts, stt = speech
    said = "I need the sandbox credentials from Amit, so I'm stuck on PROJ-142."
    audio = await tts.synthesize(said)
    assert audio.sample_rate in (16_000, 22_050) and audio.duration_ms > 2000
    from scrum_voice.vad import EnergyVAD

    vad, utterance = EnergyVAD(), None
    for f in frames_of(audio.pcm, audio.sample_rate, "rahul"):
        utterance = vad.feed(f.pcm, f.duration_ms) or utterance
    assert utterance and len(utterance) > 16_000  # VAD found one utterance of > 0.5 s
    heard = await stt.transcribe(utterance, 16_000, vocabulary=["Rahul Verma", "Amit Sharma", "PROJ-142", "sandbox"])
    text = heard.text.lower()
    assert "sandbox" in text and "credential" in text and "amit" in text, heard.text
    assert heard.confidence > 0.4


class PiperMeeting:
    """Like FakeMeetingProvider, but participants answer with real synthesized audio (PCM frames)."""

    name, realtime = "piper-sim", False

    def __init__(self, tts, people: dict[str, tuple[str, list[str]]]) -> None:
        self.tts, self.people = tts, people  # email -> (first name, answers)
        self.inbox: asyncio.Queue[AudioFrame] = asyncio.Queue()
        self.current: str | None = None

    async def join(self, join_url, display_name):
        return CallHandle("c1", join_url, self.name)

    async def set_recording_status(self, call, recording):
        pass

    async def audio_in(self, call):
        while True:
            yield await self.inbox.get()

    async def audio_out(self, call, frame):
        import re

        text = frame.text or ""
        for email, (first, _) in self.people.items():
            if re.search(rf"(?:^|[.!?]\s+){first},", text):
                self.current = email
        if not self.current or not text.rstrip().endswith("?"):
            return
        first, answers = self.people[self.current]
        reply = "Yes, that's right." if CONFIRM_RE.search(text) else (answers.pop(0) if answers else "That's all.")
        audio = await self.tts.synthesize(reply)
        for f in frames_of(audio.pcm, audio.sample_rate, self.current):
            await self.inbox.put(f)

    async def participants(self, call):
        return [Participant(id=e, name=f, email=e) for e, (f, _) in self.people.items()]

    async def leave(self, call):
        pass


async def test_standup_over_real_audio(speech):
    from scrum_core.schemas.workflow import MemberCtx, QuestionCtx, StandupContext
    from scrum_voice.controller import Budget, StandupController
    from scrum_voice.judge import HeuristicJudge
    from scrum_voice.pipeline import CallIO
    from scrum_voice.transcript import TranscriptWriter

    class MemoryWriter(TranscriptWriter):
        async def flush(self) -> None:
            pass

    tts, stt = speech
    rahul = MemberCtx(user_id=uuid.uuid4(), display_name="Rahul Verma", first_name="Rahul", email="rahul@acme.example")
    provider = PiperMeeting(
        tts,
        {
            rahul.email: (
                "Rahul",
                [
                    "I finished the refund API main logic.",
                    "Today I will write the refund API tests.",
                    "I need the sandbox credentials from Amit, so I'm stuck.",
                ],
            )
        },
    )
    questions = [
        QuestionCtx(
            id=uuid.uuid4(), position=i + 1, text=t, type="text", required=True, followup_policy="none", max_followups=0
        )
        for i, t in enumerate(
            ["What did you complete yesterday?", "What will you work on today?", "Any blockers or dependencies?"]
        )
    ]
    ctx = StandupContext(
        org_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        team_name="Payments",
        timezone="UTC",
        run_date="2026-11-10",
        session_id=uuid.uuid4(),
        lead_user_id=uuid.uuid4(),
        lead_email="",
        lead_name="",
        members=[rahul],
        template_id=None,
        questions=questions,
        consent_text="This standup is being recorded.",
        async_window_minutes=0,
        join_url="sim://",
    )
    call = await provider.join("sim://", "Scrum Bot")
    io = CallIO(provider, call, stt, tts, vocabulary=["Rahul Verma", "Amit Sharma", "sandbox", "refund API"])
    await io.start()
    writer = MemoryWriter(ctx.org_id, ctx.session_id)
    progress = await StandupController(
        ctx, io, HeuristicJudge(), writer, Budget(900, 60, 180), listen_timeout_s=60
    ).run()
    await io.stop()
    said = [s.text.lower() for s in writer.all if s.speaker_user_id == rahul.user_id]
    assert progress.attended == [str(rahul.user_id)]
    assert len(said) == 4, said  # three answers + the confirmation
    assert "refund" in said[0] and "test" in said[1] and "sandbox" in said[2] and "yes" in said[3]
