"""Open-source LLM access through any OpenAI-compatible server (Ollama, vLLM, llama.cpp, LocalAI).

``structured()`` is a small, dependency-free equivalent of ``instructor``: it sends the Pydantic
JSON schema as ``response_format`` (constrained decoding on Ollama/vLLM/llama.cpp), validates the
reply with Pydantic and retries with the validation error appended (plan §9.1, ``max_retries=2``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

Message = dict[str, str]


class LLMUnavailable(RuntimeError):
    """The model server could not be reached (callers may fall back to heuristics)."""


class LLMClient(Protocol):
    name: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str: ...


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, default_model: str, timeout: float = 120.0) -> None:
        self.name = f"openai-compat:{default_model}"
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = default_model
        self._timeout = timeout

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("title", "output"), "schema": json_schema, "strict": False},
            }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                r = await http.post(
                    f"{self._base}/chat/completions", json=body, headers={"Authorization": f"Bearer {self._key}"}
                )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"{exc.__class__.__name__}: {exc}") from exc
        if r.status_code >= 500 or r.status_code == 404:
            raise LLMUnavailable(f"{r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"] or "")


class FakeLLM:
    """Deterministic stand-in: a function from the message list to the reply text."""

    name = "fake-llm"

    def __init__(self, responder: Callable[[Sequence[Message]], str]) -> None:
        self._responder = responder
        self.calls: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], **_: Any) -> str:
        self.calls.append(messages)
        return self._responder(messages)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def _parse_json(text: str) -> Any:
    text = _FENCE.sub("", text.strip())
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


async def structured[M: BaseModel](
    llm: LLMClient,
    messages: Sequence[Message],
    schema: type[M],
    *,
    model: str | None = None,
    max_retries: int = 2,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> M:
    json_schema = schema.model_json_schema()
    convo = list(messages)
    last: Exception | None = None
    for attempt in range(max_retries + 1):
        raw = await llm.complete(
            convo, model=model, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens
        )
        try:
            return schema.model_validate(_parse_json(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last = exc
            log.info("structured output retry %s for %s: %s", attempt + 1, schema.__name__, str(exc)[:200])
            convo = [
                *convo,
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": f"That JSON was invalid: {str(exc)[:800]}. Reply with corrected JSON only.",
                },
            ]
    raise ValueError(f"LLM did not produce a valid {schema.__name__}: {last}")


# ------------------------------------------------------------------------------------------
# Embeddings
# ------------------------------------------------------------------------------------------


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class OpenAICompatEmbedder:
    """``/v1/embeddings`` on Ollama (nomic-embed-text, 768-d), vLLM, llama.cpp or TEI."""

    def __init__(self, base_url: str, api_key: str, model: str, dim: int, timeout: float = 60.0) -> None:
        self.name = f"openai-compat:{model}"
        self.dim = dim
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                r = await http.post(
                    f"{self._base}/embeddings",
                    json={"model": self._model, "input": list(texts)},
                    headers={"Authorization": f"Bearer {self._key}"},
                )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"{exc.__class__.__name__}: {exc}") from exc
        if r.status_code >= 400:
            raise LLMUnavailable(f"embeddings {r.status_code}: {r.text[:300]}")
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        out = [_normalize([float(x) for x in d["embedding"]]) for d in data]
        if out and len(out[0]) != self.dim:
            raise ValueError(f"Embedding model returned {len(out[0])} dims, expected {self.dim}")
        return out


_WORD = re.compile(r"[a-z0-9]+(?:-[0-9]+)?")
_STOP = frozenset("a an the to for of on in and or but is are was be i we my our it this that with from".split())


class HashingEmbedder:
    """Deterministic offline embedder (feature hashing of unigrams + bigrams). Used in tests/CI.

    Not semantic like a neural model, but stable and dependency-free; similarity reflects word overlap.
    """

    name = "hashing-v1"

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        words = [w for w in _WORD.findall(text.lower()) if w not in _STOP]
        feats = words + [f"{a}_{b}" for a, b in pairwise(words)]
        v = [0.0] * self.dim
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return _normalize(v)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False)) / (
        (math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(y * y for y in b)) or 1)
    )
