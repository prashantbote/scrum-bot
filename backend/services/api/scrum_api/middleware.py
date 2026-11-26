"""Rate limiting (per caller, Redis when configured) and POST Idempotency-Key replay (plan §6.2, §12)."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from scrum_core.settings import get_settings


class _Store:
    """Tiny KV with TTL: Redis if configured, otherwise in-process (single API replica / tests)."""

    def __init__(self) -> None:
        url = get_settings().redis_url
        self._redis = Redis.from_url(url) if url else None
        self._mem: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def incr(self, key: str, ttl: int) -> int:
        if self._redis is not None:
            n = int(await self._redis.incr(key))
            if n == 1:
                await self._redis.expire(key, ttl)
            return n
        exp, val = self._mem.get(key, (time.time() + ttl, 0))
        if exp < time.time():
            exp, val = time.time() + ttl, 0
        self._mem[key] = (exp, val + 1)
        self._trim()
        return int(val) + 1

    async def get(self, key: str) -> Any:
        if self._redis is not None:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        item = self._mem.get(key)
        return item[1] if item and item[0] > time.time() else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if self._redis is not None:
            await self._redis.set(key, json.dumps(value), ex=ttl)
            return
        self._mem[key] = (time.time() + ttl, value)
        self._trim()

    def _trim(self) -> None:
        while len(self._mem) > 20_000:
            self._mem.popitem(last=False)


_store: _Store | None = None


def store() -> _Store:
    global _store
    if _store is None:
        _store = _Store()
    return _store


def _caller(request: Request) -> str:
    ident = (
        request.headers.get("Authorization")
        or request.headers.get("X-Mock-User")
        or (request.client.host if request.client else "anon")
    )
    return hashlib.sha256(ident.encode()).hexdigest()[:24]


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limit = get_settings().rate_limit_per_minute
        if limit > 0 and request.url.path.startswith("/api/"):
            n = await store().incr(f"rl:{_caller(request)}:{int(time.time() // 60)}", 70)
            if n > limit:
                return JSONResponse(
                    {"title": "Too many requests", "status": 429, "detail": "Slow down and try again in a minute."},
                    status_code=429,
                    media_type="application/problem+json",
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Replays the stored response for a repeated POST with the same Idempotency-Key (24 h)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = request.headers.get("Idempotency-Key")
        if request.method != "POST" or not key:
            return await call_next(request)
        cache_key = f"idem:{_caller(request)}:{request.url.path}:{key[:100]}"
        cached = await store().get(cache_key)
        if cached:
            return Response(
                content=cached["body"].encode(),
                status_code=cached["status"],
                media_type=cached["type"],
                headers={"Idempotent-Replayed": "true"},
            )
        response = await call_next(request)
        if response.status_code < 500:
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            await store().set(
                cache_key,
                {
                    "body": body.decode(),
                    "status": response.status_code,
                    "type": response.media_type or response.headers.get("content-type"),
                },
                86_400,
            )
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers))
        return response
