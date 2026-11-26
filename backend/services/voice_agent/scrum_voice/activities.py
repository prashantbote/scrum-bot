"""``run_voice_standup`` activity on the ``voice-agents`` queue (plan §7.3, §8)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from temporalio import activity
from temporalio.exceptions import ApplicationError

from scrum_adapters import registry
from scrum_adapters.meeting.base import MeetingNotFound
from scrum_adapters.meeting.fake import FakeMeetingProvider
from scrum_core.db import session_for
from scrum_core.models import Attendance, StandupSession
from scrum_core.models.base import AttendanceStatus, SessionStatus
from scrum_core.schemas.workflow import StandupContext, VoiceResult
from scrum_core.settings import get_settings
from scrum_voice.controller import Budget, Progress, StandupController
from scrum_voice.demo_script import demo_participants
from scrum_voice.judge import HeuristicJudge, LlmJudge, TurnJudge
from scrum_voice.pipeline import CallIO
from scrum_voice.transcript import TranscriptWriter

log = logging.getLogger(__name__)


def _judge() -> TurnJudge:
    s = get_settings()
    llm = registry.llm("fast")
    return LlmJudge(llm, s.llm_fast_model, s.llm_turn_timeout_seconds) if llm else HeuristicJudge()


async def _warm_up() -> None:
    """Load the fast model before joining so the first turn isn't a cold start (Ollama swaps models)."""
    llm = registry.llm("fast")
    if llm is None:
        return
    try:
        await asyncio.wait_for(llm.complete([{"role": "user", "content": "Reply ok"}], max_tokens=2), timeout=90)
    except Exception as exc:  # warm-up is best effort; the judge falls back to heuristics anyway
        log.info("fast model warm-up failed: %s", exc.__class__.__name__)


@activity.defn(name="run_voice_standup")
async def run_voice_standup(ctx: StandupContext) -> VoiceResult:
    s = get_settings()
    info = activity.info()
    progress = Progress()
    if info.attempt > 1 and info.heartbeat_details:
        try:
            progress = Progress(**info.heartbeat_details[0])
            log.info("resuming standup %s after %d member(s)", ctx.session_id, len(progress.done_member_ids))
        except TypeError:
            progress = Progress()

    await _warm_up()
    provider = registry.meeting()
    if isinstance(provider, FakeMeetingProvider) and not provider.has_script:
        provider = FakeMeetingProvider(demo_participants(ctx))  # demo mode: a fresh scripted call per run
    try:
        call = await provider.join(ctx.join_url or "", s.bot_display_name)
    except MeetingNotFound as exc:
        raise ApplicationError(str(exc), type="MeetingNotFound", non_retryable=True) from exc

    started = datetime.now(UTC)
    async with session_for(ctx.org_id) as db:
        row = await db.get(StandupSession, ctx.session_id)
        if row is not None and row.started_at is None:
            row.started_at = started
        if row is not None:
            row.status = SessionStatus.running
        started = row.started_at if row and row.started_at else started

    await provider.set_recording_status(call, True)  # consent: recording notice before any audio is kept
    io = CallIO(provider, call, registry.stt(), registry.tts(), vocabulary=ctx.vocabulary, start_ms=progress.elapsed_ms)
    await io.start()
    writer = TranscriptWriter(ctx.org_id, ctx.session_id)

    stop = asyncio.Event()

    async def keepalive() -> None:  # heartbeat every 10 s even while a member is talking
        while not stop.is_set():
            activity.heartbeat(progress.__dict__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except TimeoutError:
                pass

    beat = asyncio.create_task(keepalive())
    controller = StandupController(
        ctx,
        io,
        _judge(),
        writer,
        Budget(s.standup_budget_seconds, s.per_person_min_seconds, s.per_person_max_seconds),
        heartbeat=lambda p: activity.heartbeat(p.__dict__),
        listen_timeout_s=12.0 if provider.realtime else 2.0,
        progress=progress,
    )
    try:
        progress = await controller.run()
    finally:
        stop.set()
        await beat
        await io.stop()
        await provider.set_recording_status(call, False)
        await provider.leave(call)

    attended = {UUID(x) for x in progress.attended}
    async with session_for(ctx.org_id) as db:
        row = await db.get(StandupSession, ctx.session_id)
        if row is not None:
            row.ended_at = row.started_at + timedelta(milliseconds=progress.elapsed_ms) if row.started_at else None
        for m in ctx.members:
            status = AttendanceStatus.present if m.user_id in attended else AttendanceStatus.absent
            # do-nothing on conflict: never overwrite an "async" row written by an early check-in.
            await db.execute(
                insert(Attendance)
                .values(
                    org_id=ctx.org_id,
                    session_id=ctx.session_id,
                    user_id=m.user_id,
                    status=status,
                    joined_at=started if status == AttendanceStatus.present else None,
                )
                .on_conflict_do_nothing(index_elements=["session_id", "user_id"])
            )
    return VoiceResult(
        session_id=ctx.session_id,
        attended_user_ids=sorted(attended, key=str),
        segment_count=writer.count,
        duration_seconds=progress.elapsed_ms // 1000,
        resolved_blocker_ids=[UUID(x) for x in progress.resolved_blockers],
    )


ACTIVITIES: list[Callable[..., Any]] = [run_voice_standup]
