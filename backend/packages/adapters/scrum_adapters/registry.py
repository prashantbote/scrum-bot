"""Builds adapters from settings. Tests call ``override()`` to inject fakes."""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrum_adapters.blob import BlobStore, LocalBlobStore, S3BlobStore
from scrum_adapters.calendar import CalendarAdapter, LiveKitRoomCalendar
from scrum_adapters.llm import Embedder, HashingEmbedder, LLMClient, OpenAICompatEmbedder, OpenAICompatLLM
from scrum_adapters.mail import MailAdapter, MemoryMailAdapter, SmtpMailAdapter
from scrum_adapters.meeting.base import MeetingProvider
from scrum_adapters.meeting.fake import FakeMeetingProvider
from scrum_adapters.pm import FakePMAdapter, JiraCloudAdapter, PMAdapter
from scrum_adapters.stt import FakeSTT, STTProvider, WhisperSTT
from scrum_adapters.tts import FakeTTS, PiperTTS, TTSProvider
from scrum_core.models import Integration
from scrum_core.models.base import IntegrationKind, IntegrationStatus
from scrum_core.security.crypto import Sealed, unseal
from scrum_core.settings import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T")

_instances: dict[str, Any] = {}


def override(name: str, value: Any) -> None:
    _instances[name] = value


def reset() -> None:
    _instances.clear()


def _get(name: str, build: Any) -> Any:
    if name not in _instances:
        _instances[name] = build()
    return _instances[name]


def llm(kind: str = "strong") -> LLMClient | None:
    """None means "use the heuristic engine"."""
    s = get_settings()
    if s.llm_provider == "heuristic":
        return _instances.get(f"llm:{kind}")
    model = s.llm_strong_model if kind == "strong" else s.llm_fast_model
    return _get(  # type: ignore[no-any-return]
        f"llm:{kind}",
        lambda: OpenAICompatLLM(s.llm_base_url, s.llm_api_key.get_secret_value(), model, s.llm_timeout_seconds),
    )


def embedder() -> Embedder:
    s = get_settings()
    if s.embed_provider == "hashing":
        return _get("embedder", lambda: HashingEmbedder(s.embed_dim))  # type: ignore[no-any-return]
    return _get(  # type: ignore[no-any-return]
        "embedder",
        lambda: OpenAICompatEmbedder(s.llm_base_url, s.llm_api_key.get_secret_value(), s.embed_model, s.embed_dim),
    )


def mail() -> MailAdapter:
    s = get_settings()
    if s.mail_provider == "memory":
        return _get("mail", MemoryMailAdapter)  # type: ignore[no-any-return]
    return _get(  # type: ignore[no-any-return]
        "mail",
        lambda: SmtpMailAdapter(
            s.smtp_host,
            s.smtp_port,
            s.mail_from,
            username=s.smtp_username,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None,
            starttls=s.smtp_starttls,
        ),
    )


def meeting() -> MeetingProvider:
    s = get_settings()
    if s.meeting_provider == "livekit":
        from scrum_adapters.meeting.livekit import LiveKitMeetingProvider

        return _get(  # type: ignore[no-any-return]
            "meeting",
            lambda: LiveKitMeetingProvider(s.livekit_url, s.livekit_api_key, s.livekit_api_secret.get_secret_value()),
        )
    return _get("meeting", FakeMeetingProvider)  # type: ignore[no-any-return]


def stt() -> STTProvider:
    s = get_settings()
    if s.stt_provider == "whisper":
        return _get("stt", lambda: WhisperSTT(s.whisper_model, s.whisper_device))  # type: ignore[no-any-return]
    return _get("stt", FakeSTT)  # type: ignore[no-any-return]


def tts() -> TTSProvider:
    s = get_settings()
    if s.tts_provider == "piper":
        return _get("tts", lambda: PiperTTS(s.piper_voice, s.piper_voice_dir))  # type: ignore[no-any-return]
    return _get("tts", FakeTTS)  # type: ignore[no-any-return]


def blob() -> BlobStore:
    s = get_settings()
    if s.blob_backend == "s3":
        return _get(  # type: ignore[no-any-return]
            "blob",
            lambda: S3BlobStore(
                s.s3_endpoint, s.s3_access_key, s.s3_secret_key.get_secret_value(), s.s3_bucket, s.s3_secure
            ),
        )
    return _get("blob", lambda: LocalBlobStore(s.blob_dir))  # type: ignore[no-any-return]


def calendar() -> CalendarAdapter:
    s = get_settings()
    return _get("calendar", lambda: LiveKitRoomCalendar(s.meeting_join_url_template, mail()))  # type: ignore[no-any-return]


def fake_pm() -> FakePMAdapter:
    return _get("pm:fake", FakePMAdapter)  # type: ignore[no-any-return]


async def pm_for_org(session: AsyncSession, org_id: UUID) -> PMAdapter | None:
    """The org's connected PM tool, or None. In fake mode a shared in-memory catalog is used."""
    if "pm" in _instances:
        return _instances["pm"]  # type: ignore[no-any-return]
    s = get_settings()
    if s.pm_provider == "fake":
        return fake_pm()
    row = (
        await session.execute(
            select(Integration).where(Integration.org_id == org_id, Integration.kind == IntegrationKind.jira)
        )
    ).scalar_one_or_none()
    if not row or row.status == IntegrationStatus.disconnected or not row.encrypted_token or not row.wrapped_dek:
        return None
    secret = unseal(Sealed(row.encrypted_token, row.wrapped_dek, row.key_id or ""), aad=f"integration:{org_id}:jira")
    token = json.loads(secret)["access_token"] if secret.startswith("{") else secret
    cfg = row.config or {}
    return JiraCloudAdapter(
        cfg["api_base_url"],
        token,
        site_url=cfg.get("site_url"),
        story_points_field=cfg.get("story_points_field", "customfield_10016"),
    )
