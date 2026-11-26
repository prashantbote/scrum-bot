"""LiveKit meeting provider (open-source WebRTC SFU, Apache-2.0). Requires the ``[voice]`` extra.

The bot joins a LiveKit room as a participant, publishes one audio track (TTS) and subscribes to
every remote audio track. LiveKit delivers one stream per participant, so each frame carries an
exact ``speaker_id`` (the participant identity, which we set to the user's email when minting
join tokens) — better attribution than mixed-audio diarization.

``join_url`` is the room URL produced by ``calendar.livekit_rooms`` (``.../rooms/<room>``); only
the last path segment (the room name) is used here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from scrum_adapters.meeting.base import AudioFrame, CallHandle, MeetingNotFound, Participant

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_MS = 20


def room_from_url(join_url: str) -> str:
    path = urlparse(join_url).path.rstrip("/")
    room = path.rsplit("/", 1)[-1] if path else join_url
    if not room:
        raise MeetingNotFound(join_url)
    return room


def mint_token(api_key: str, api_secret: str, *, room: str, identity: str, name: str, ttl_hours: int = 12) -> str:
    from livekit import api

    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(timedelta(hours=ttl_hours))
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )


class LiveKitMeetingProvider:
    name = "livekit"
    realtime = True

    def __init__(self, url: str, api_key: str, api_secret: str) -> None:
        self._url = url
        self._key = api_key
        self._secret = api_secret
        self._rooms: dict[str, Any] = {}

    async def join(self, join_url: str, display_name: str) -> CallHandle:
        from livekit import rtc

        room_name = room_from_url(join_url)
        token = mint_token(self._key, self._secret, room=room_name, identity="scrum-bot", name=display_name)
        room = rtc.Room()
        queue: asyncio.Queue[AudioFrame] = asyncio.Queue(maxsize=2000)
        pumps: list[asyncio.Task[None]] = []

        async def pump(track: Any, participant: Any) -> None:
            stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
            async for ev in stream:
                frame = ev.frame
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(
                        AudioFrame(
                            pcm=bytes(frame.data), sample_rate=frame.sample_rate, speaker_id=participant.identity
                        )
                    )

        @room.on("track_subscribed")
        def _on_track(track: Any, _pub: Any, participant: Any) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                pumps.append(asyncio.create_task(pump(track, participant)))

        try:
            await room.connect(self._url, token, options=rtc.RoomOptions(auto_subscribe=True))
        except Exception as exc:
            raise MeetingNotFound(f"Could not join LiveKit room {room_name}: {exc}") from exc

        source = rtc.AudioSource(SAMPLE_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("scrum-bot-voice", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        call_id = f"{room_name}:{room.local_participant.sid}"
        self._rooms[call_id] = {"room": room, "queue": queue, "source": source, "pumps": pumps}
        return CallHandle(call_id=call_id, join_url=join_url, provider=self.name, data={"room": room_name})

    async def set_recording_status(self, call: CallHandle, recording: bool) -> None:
        # LiveKit has no Teams-style banner; clients render this participant attribute as a notice.
        room = self._rooms[call.call_id]["room"]
        await room.local_participant.set_attributes({"recording": "true" if recording else "false"})

    async def audio_in(self, call: CallHandle) -> AsyncIterator[AudioFrame]:
        queue: asyncio.Queue[AudioFrame] = self._rooms[call.call_id]["queue"]
        while True:
            yield await queue.get()

    async def audio_out(self, call: CallHandle, frame: AudioFrame) -> None:
        from livekit import rtc

        if not frame.pcm:
            return
        source = self._rooms[call.call_id]["source"]
        pcm = frame.pcm
        if frame.sample_rate != SAMPLE_RATE:
            pcm = resample_pcm16(pcm, frame.sample_rate, SAMPLE_RATE)
        step = SAMPLE_RATE * FRAME_MS // 1000 * 2
        for i in range(0, len(pcm), step):
            chunk = pcm[i : i + step]
            if len(chunk) < step:
                chunk = chunk + b"\x00" * (step - len(chunk))
            await source.capture_frame(
                rtc.AudioFrame(data=chunk, sample_rate=SAMPLE_RATE, num_channels=1, samples_per_channel=step // 2)
            )

    async def participants(self, call: CallHandle) -> list[Participant]:
        room = self._rooms[call.call_id]["room"]
        speaking = {p.identity for p in getattr(room, "active_speakers", [])}
        return [
            Participant(
                id=p.identity,
                name=p.name or p.identity,
                email=p.identity if "@" in p.identity else None,
                is_speaking=p.identity in speaking,
            )
            for p in room.remote_participants.values()
        ]

    async def leave(self, call: CallHandle) -> None:
        state = self._rooms.pop(call.call_id, None)
        if not state:
            return
        for t in state["pumps"]:
            t.cancel()
        await state["room"].disconnect()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resampler (numpy) — adequate for speech."""
    import numpy as np

    if src_rate == dst_rate or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_out = int(len(x) * dst_rate / src_rate)
    idx = np.linspace(0, len(x) - 1, n_out)
    return np.interp(idx, np.arange(len(x)), x).astype(np.int16).tobytes()
