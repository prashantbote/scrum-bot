"""Test configuration.

Everything runs offline by default: heuristic extraction, hashing embeddings, in-memory mail, fake
meeting/STT/TTS/PM. DB tests use ``scrum_test`` on the compose Postgres (as the non-owner app role, so
RLS is enforced) and are skipped when it isn't reachable. Override with SCRUM_TEST_DATABASE_URL /
SCRUM_TEST_DATABASE_OWNER_URL.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

APP_URL = os.environ.get(
    "SCRUM_TEST_DATABASE_URL", "postgresql+asyncpg://scrum_app:scrum_app@localhost:55432/scrum_test"
)
OWNER_URL = os.environ.get(
    "SCRUM_TEST_DATABASE_OWNER_URL", "postgresql+asyncpg://scrum:scrum@localhost:55432/scrum_test"
)

os.environ.update(
    {
        "SCRUM_ENV": "test",
        "SCRUM_DATABASE_URL": APP_URL,
        "SCRUM_DATABASE_OWNER_URL": OWNER_URL,
        "SCRUM_AUTH_MODE": "dev",
        "SCRUM_LLM_PROVIDER": "heuristic",
        "SCRUM_EMBED_PROVIDER": "hashing",
        "SCRUM_MAIL_PROVIDER": "memory",
        "SCRUM_FAKE_PROVIDERS": "1",
        "SCRUM_TEMPORAL_ENABLED": "false",
        "SCRUM_BLOB_DIR": str(ROOT / ".data" / "test-blobs"),
        "SCRUM_RATE_LIMIT_PER_MINUTE": "0",
        "SCRUM_REDIS_URL": "",
    }
)
os.environ.pop("SCRUM_REDIS_URL")


def _db_reachable() -> bool:
    import asyncpg

    async def ping() -> bool:
        try:
            conn = await asyncpg.connect(OWNER_URL.replace("+asyncpg", ""), timeout=3)
        except Exception:
            return False
        await conn.close()
        return True

    return asyncio.run(ping())


DB_OK = _db_reachable()


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    if not DB_OK:
        pytest.skip("PostgreSQL test database not reachable (start infra/docker-compose.yml)")
    import asyncpg

    async def reset() -> None:
        conn = await asyncpg.connect(OWNER_URL.replace("+asyncpg", ""))
        await conn.execute(
            "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public; "
            "CREATE EXTENSION IF NOT EXISTS vector; GRANT USAGE ON SCHEMA public TO scrum_app;"
        )
        await conn.close()

    asyncio.run(reset())
    env = {**os.environ, "ALEMBIC_DATABASE_URL": OWNER_URL}
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    yield


@pytest.fixture(scope="session")
async def seeded(migrated_db: None) -> AsyncIterator[dict[str, object]]:
    """The full story seed (frontend parity data) loaded into the test DB."""
    import seed as seed_mod
    from scrum_adapters import registry

    registry.reset()
    await seed_mod.seed(with_temporal=False)
    fri = seed_mod.story_friday()
    yield {
        "org_id": seed_mod.ORG_ID,
        "payments": seed_mod.sid("team-payments"),
        "backend": seed_mod.sid("team-backend"),
        "fri": fri,
        "sid": seed_mod.sid,
    }


@pytest.fixture
async def client(seeded: dict[str, object]) -> AsyncIterator[object]:
    import httpx

    from scrum_api.main import create_app

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c


def as_(persona: str) -> dict[str, str]:
    return {"X-Mock-User": persona}
