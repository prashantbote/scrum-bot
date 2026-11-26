"""Thin Temporal client used by the API to manage per-team Schedules (plan §7.1) and signal workflows.

Lives in core (not in the orchestrator service) so the API never imports another service: it only
refers to the workflow by name and passes shared pydantic payloads.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from uuid import UUID

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError

from scrum_core.schedule import shift_cron_earlier, today_in
from scrum_core.schemas.workflow import (
    DEFAULT_QUEUE,
    WORKFLOW_NAME,
    AsyncCheckinSignal,
    StandupInput,
    schedule_id,
    workflow_id,
)
from scrum_core.settings import get_settings

_client: Client | None = None
_lock = asyncio.Lock()


async def get_client() -> Client:
    global _client
    async with _lock:
        if _client is None:
            s = get_settings()
            _client = await Client.connect(
                s.temporal_address, namespace=s.temporal_namespace, data_converter=pydantic_data_converter
            )
        return _client


def set_client(client: Client | None) -> None:
    """Tests inject a client connected to the Temporal test server."""
    global _client
    _client = client


def _schedule(org_id: UUID, team_id: UUID, cron: str, tz: str, lead_minutes: int, paused: bool) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            StandupInput(org_id=org_id, team_id=team_id),
            id=f"standup-{team_id}",  # Temporal appends the scheduled time
            task_queue=DEFAULT_QUEUE,
            execution_timeout=timedelta(hours=12),
        ),
        spec=ScheduleSpec(cron_expressions=[shift_cron_earlier(cron, lead_minutes)], time_zone_name=tz),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        state=ScheduleState(paused=paused, note="managed by scrum-bot api"),
    )


async def upsert_schedule(*, org_id: UUID, team_id: UUID, cron: str, tz: str, lead_minutes: int, paused: bool) -> str:
    client = await get_client()
    sid = schedule_id(team_id)
    sched = _schedule(org_id, team_id, cron, tz, lead_minutes, paused)
    try:
        await client.create_schedule(sid, sched)
    except ScheduleAlreadyRunningError:

        async def _update(_: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=sched)

        await client.get_schedule_handle(sid).update(_update)
    return sid


async def set_paused(team_id: UUID, paused: bool) -> None:
    handle = (await get_client()).get_schedule_handle(schedule_id(team_id))
    if paused:
        await handle.pause(note="paused from scrum-bot")
    else:
        await handle.unpause(note="resumed from scrum-bot")


async def delete_schedule(team_id: UUID) -> None:
    try:
        await (await get_client()).get_schedule_handle(schedule_id(team_id)).delete()
    except RPCError:
        pass


async def trigger_now(*, org_id: UUID, team_id: UUID, tz: str) -> str:
    client = await get_client()
    run_date = today_in(tz)
    # One manual run per minute (double-click guard); whether today already ran is decided by the DB.
    wid = f"{workflow_id(team_id, run_date, manual=True)}-{int(time.time() // 60)}"
    await client.start_workflow(
        WORKFLOW_NAME,
        StandupInput(org_id=org_id, team_id=team_id, run_date=run_date, manual=True),
        id=wid,
        task_queue=DEFAULT_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    return wid


async def ensure_retention_schedule(cron: str = "0 2 * * *") -> None:
    """Nightly retention sweeper (plan §12), created once by the orchestrator worker."""
    client = await get_client()
    sched = Schedule(
        action=ScheduleActionStartWorkflow("RetentionSweepWorkflow", id="retention-sweeper", task_queue=DEFAULT_QUEUE),
        spec=ScheduleSpec(cron_expressions=[cron], time_zone_name="UTC"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    try:
        await client.create_schedule("retention-sweeper", sched)
    except ScheduleAlreadyRunningError:
        pass


async def start_job(name: str, arg: object, *, id: str) -> str:
    """Fire-and-forget helper workflows (resend digest, alerts after a review decision)."""
    client = await get_client()
    await client.start_workflow(
        name, arg, id=id, task_queue=DEFAULT_QUEUE, id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE
    )
    return id


async def signal_async_checkin(workflow_id_: str, user_id: UUID) -> bool:
    """Best effort: the check-in is already stored in the DB; the signal only wakes the workflow early."""
    try:
        handle = (await get_client()).get_workflow_handle(workflow_id_)
        await handle.signal("submit_async_checkin", AsyncCheckinSignal(user_id=user_id))
        return True
    except Exception:
        return False
