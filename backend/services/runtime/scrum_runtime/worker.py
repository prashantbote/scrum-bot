"""Temporal workers (plan §7.3): one Deployment per role in Kubernetes, or all roles in one process locally.

scrum-worker orchestrator   # workflows + default queue
scrum-worker voice          # voice-agents queue (voice node pool)
scrum-worker intelligence   # intelligence queue
scrum-worker delivery       # delivery queue
scrum-worker all            # everything (make run)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from scrum_core import telemetry
from scrum_core.schemas.workflow import DEFAULT_QUEUE, DELIVERY_QUEUE, INTELLIGENCE_QUEUE, VOICE_QUEUE
from scrum_core.workflow_client import ensure_retention_schedule, get_client

log = logging.getLogger("scrum.worker")
ROLES = ("orchestrator", "voice", "intelligence", "delivery")


def build_workers(client: Client, roles: Sequence[str], *, voice_concurrency: int = 4) -> list[Worker]:
    from scrum_delivery.activities import ACTIVITIES as DELIVERY
    from scrum_intelligence.activities import ACTIVITIES as INTELLIGENCE
    from scrum_orchestrator.activities import ACTIVITIES as ORCH_ACTIVITIES
    from scrum_orchestrator.workflows import WORKFLOWS
    from scrum_voice.activities import ACTIVITIES as VOICE

    workers: list[Worker] = []
    pool = ThreadPoolExecutor(max_workers=8)
    common: dict[str, Any] = {"activity_executor": pool}
    if "orchestrator" in roles:
        workers.append(
            Worker(client, task_queue=DEFAULT_QUEUE, workflows=WORKFLOWS, activities=ORCH_ACTIVITIES, **common)
        )
    if "voice" in roles:
        # Each pod runs N concurrent calls (plan §8.3).
        workers.append(
            Worker(
                client, task_queue=VOICE_QUEUE, activities=VOICE, max_concurrent_activities=voice_concurrency, **common
            )
        )
    if "intelligence" in roles:
        workers.append(
            Worker(
                client, task_queue=INTELLIGENCE_QUEUE, activities=INTELLIGENCE, max_concurrent_activities=8, **common
            )
        )
    if "delivery" in roles:
        workers.append(Worker(client, task_queue=DELIVERY_QUEUE, activities=DELIVERY, **common))
    return workers


async def run(roles: Sequence[str]) -> None:
    telemetry.setup(f"scrum-worker-{'-'.join(roles)}")
    client = await get_client()
    if "orchestrator" in roles:
        await ensure_retention_schedule()
    workers = build_workers(client, roles)
    log.info("starting workers: %s", ", ".join(w.task_queue for w in workers))
    await asyncio.gather(*(w.run() for w in workers))


def main(argv: Sequence[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:]) or ["all"]
    roles = ROLES if args == ["all"] else tuple(args)
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        raise SystemExit(f"unknown worker role(s): {unknown}; choose from {ROLES} or 'all'")
    asyncio.run(run(roles))


if __name__ == "__main__":
    main()
