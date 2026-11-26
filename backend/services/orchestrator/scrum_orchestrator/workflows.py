"""DailyStandupWorkflow and helper workflows (plan §7.2).

Activities are referenced by name and routed to their service's task queue, so this module never
imports the voice, intelligence or delivery services.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from scrum_core.schemas.workflow import (
        DEFAULT_QUEUE,
        DELIVERY_QUEUE,
        INTELLIGENCE_QUEUE,
        VOICE_QUEUE,
        AsyncCheckinSignal,
        AsyncRequest,
        BlockerAlertsInput,
        BlockerRefs,
        ExtractResult,
        ResendDigestInput,
        SendResult,
        SessionRef,
        StandupContext,
        StandupInput,
        VoiceResult,
    )

RETRY_3 = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2), backoff_coefficient=2.0)
RETRY_5 = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=2), backoff_coefficient=2.0)


@workflow.defn(name="DailyStandupWorkflow")
class DailyStandupWorkflow:
    def __init__(self) -> None:
        self.async_responses: set[str] = set()
        self.stage = "starting"

    @workflow.signal
    def submit_async_checkin(self, checkin: AsyncCheckinSignal) -> None:
        self.async_responses.add(str(checkin.user_id))

    @workflow.query
    def status(self) -> dict[str, Any]:
        return {"stage": self.stage, "async_responses": sorted(self.async_responses)}

    async def _mark(self, ctx: StandupContext, status: str, **extra: Any) -> None:
        await workflow.execute_activity(
            "mark_session",
            {"org_id": str(ctx.org_id), "session_id": str(ctx.session_id), "status": status, **extra},
            task_queue=DEFAULT_QUEUE,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_5,
        )

    @workflow.run
    async def run(self, inp: StandupInput) -> dict[str, Any]:
        self.stage = "load_context"
        ctx: StandupContext = await workflow.execute_activity(
            "load_context",
            inp,
            result_type=StandupContext,
            task_queue=DEFAULT_QUEUE,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RETRY_3,
        )
        if ctx.skip_today:
            already = bool(ctx.skip_reason and ctx.skip_reason.startswith("Standup already"))
            await self._mark(ctx, "skipped", reason=ctx.skip_reason, already=already)
            return {"session_id": str(ctx.session_id), "skipped": ctx.skip_reason}

        ref = SessionRef(org_id=ctx.org_id, session_id=ctx.session_id, team_id=ctx.team_id)
        try:
            self.stage = "voice"
            voice: VoiceResult = await workflow.execute_activity(
                "run_voice_standup",
                ctx,
                result_type=VoiceResult,
                task_queue=VOICE_QUEUE,
                start_to_close_timeout=timedelta(minutes=45),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2, non_retryable_error_types=["MeetingNotFound"]),
            )
            await self._mark(ctx, "extracting")

            # Async fallback (plan §7.2): wait for absentees' check-ins until the window closes.
            attended = {str(u) for u in voice.attended_user_ids}
            absentees = [str(m.user_id) for m in ctx.members if str(m.user_id) not in attended]
            if absentees and ctx.async_window_minutes > 0:
                self.stage = "async_window"
                await workflow.execute_activity(
                    "send_async_checkin",
                    AsyncRequest(
                        org_id=ctx.org_id,
                        session_id=ctx.session_id,
                        user_ids=absentees,
                        window_minutes=ctx.async_window_minutes,
                    ),
                    result_type=SendResult,
                    task_queue=DELIVERY_QUEUE,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RETRY_5,
                )
                # Check-ins that landed before we started waiting (signals are only a wake-up; the DB is truth).
                pending: list[str] = await workflow.execute_activity(
                    "pending_async_users",
                    {"org_id": str(ctx.org_id), "session_id": str(ctx.session_id), "user_ids": absentees},
                    task_queue=DEFAULT_QUEUE,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RETRY_3,
                )
                self.async_responses |= set(absentees) - set(pending)
                try:
                    await workflow.wait_condition(
                        lambda: set(absentees) <= self.async_responses,
                        timeout=timedelta(minutes=ctx.async_window_minutes),
                    )
                except TimeoutError:
                    pass  # window closed: continue with whoever replied (the DB has their answers)

            self.stage = "extract"
            res: ExtractResult = await workflow.execute_activity(
                "extract_updates",
                ref,
                result_type=ExtractResult,
                task_queue=INTELLIGENCE_QUEUE,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=3),
                retry_policy=RETRY_3,
            )
            res = await workflow.execute_activity(
                "resolve_people_and_tickets",
                res,
                result_type=ExtractResult,
                task_queue=INTELLIGENCE_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RETRY_3,
            )
            blockers: BlockerRefs = await workflow.execute_activity(
                "match_and_upsert_blockers",
                res,
                result_type=BlockerRefs,
                task_queue=INTELLIGENCE_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RETRY_3,
            )
            if voice.resolved_blocker_ids:
                await workflow.execute_activity(
                    "resolve_confirmed_blockers",
                    {
                        "org_id": str(ctx.org_id),
                        "session_id": str(ctx.session_id),
                        "blocker_ids": [str(b) for b in voice.resolved_blocker_ids],
                    },
                    task_queue=INTELLIGENCE_QUEUE,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RETRY_3,
                )

            self.stage = "deliver"
            await workflow.execute_activity(
                "render_report",
                ref,
                task_queue=DELIVERY_QUEUE,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_3,
            )
            digest: SendResult = await workflow.execute_activity(
                "send_digest",
                ref,
                result_type=SendResult,
                task_queue=DELIVERY_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RETRY_5,
            )
            alerts: SendResult = await workflow.execute_activity(
                "send_blocker_alerts",
                blockers,
                result_type=SendResult,
                task_queue=DELIVERY_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RETRY_5,
            )
            escalations: SendResult = await workflow.execute_activity(
                "escalate_stale_blockers",
                ref,
                result_type=SendResult,
                task_queue=DELIVERY_QUEUE,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_5,
            )
            if ctx.pm_writeback_enabled:
                await workflow.execute_activity(
                    "propose_pm_updates",
                    res,
                    task_queue=INTELLIGENCE_QUEUE,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RETRY_3,
                )
            await self._mark(ctx, "delivered")
        except (ActivityError, asyncio.CancelledError) as exc:
            await self._mark(
                ctx, "failed", error=str(exc.cause or exc) if isinstance(exc, ActivityError) else "cancelled"
            )
            raise
        self.stage = "done"
        return {
            "session_id": str(ctx.session_id),
            "attended": len(voice.attended_user_ids),
            "segments": voice.segment_count,
            "new_blockers": len(blockers.new_blocker_ids),
            "digest_sent": digest.sent,
            "alerts_sent": alerts.sent,
            "escalations": escalations.sent,
        }


@workflow.defn(name="ResendDigestWorkflow")
class ResendDigestWorkflow:
    @workflow.run
    async def run(self, inp: ResendDigestInput) -> SendResult:
        res: SendResult = await workflow.execute_activity(
            "resend_digest",
            inp,
            result_type=SendResult,
            task_queue=DELIVERY_QUEUE,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RETRY_5,
        )
        return res


@workflow.defn(name="BlockerAlertsWorkflow")
class BlockerAlertsWorkflow:
    @workflow.run
    async def run(self, inp: BlockerAlertsInput) -> SendResult:
        res: SendResult = await workflow.execute_activity(
            "send_alerts_for",
            inp,
            result_type=SendResult,
            task_queue=DELIVERY_QUEUE,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RETRY_5,
        )
        return res


@workflow.defn(name="RetentionSweepWorkflow")
class RetentionSweepWorkflow:
    @workflow.run
    async def run(self) -> dict[str, int]:
        res: dict[str, int] = await workflow.execute_activity(
            "retention_sweep",
            task_queue=DEFAULT_QUEUE,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RETRY_3,
        )
        return res


WORKFLOWS = [DailyStandupWorkflow, ResendDigestWorkflow, BlockerAlertsWorkflow, RetentionSweepWorkflow]
