"""Runtime configuration (pydantic-settings). Every variable is prefixed with ``SCRUM_``.

Defaults target the local open-source stack in ``infra/docker-compose.yml``:
PostgreSQL+pgvector, Temporal dev server, Mailpit (SMTP), MinIO, Redis and Ollama.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Development-only secrets. Production refuses to start with these (see ``_check_prod``).
_DEV_ACTION_SECRET = "dev-action-token-secret-change-me-0123456789"  # noqa: S105 (dev only; prod refuses it)
_DEV_KEK = "ZGV2LWtlay0zMi1ieXRlcy1jaGFuZ2UtbWUtcGxlYXNlISE="  # base64 of 32 bytes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCRUM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # --- data -----------------------------------------------------------------------------
    # Application role: NOT the table owner, no BYPASSRLS (plan §4.2).
    database_url: str = "postgresql+asyncpg://scrum_app:scrum_app@localhost:55432/scrum"
    # Owner role: migrations and seeding only.
    database_owner_url: str = "postgresql+asyncpg://scrum:scrum@localhost:55432/scrum"
    redis_url: str | None = None

    # --- workflows ------------------------------------------------------------------------
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    # When false the API stores schedules but does not talk to Temporal (handy for UI-only work).
    temporal_enabled: bool = True

    # --- auth -----------------------------------------------------------------------------
    # dev: trust the X-Mock-User header (persona sign-in in the frontend). Never in prod.
    # oidc: validate bearer JWTs from any OIDC provider (Keycloak, Entra ID, Authentik, Zitadel…).
    auth_mode: Literal["dev", "oidc"] = "dev"
    oidc_issuer: str | None = None  # e.g. http://localhost:8180/realms/scrum-bot
    oidc_audience: str = "scrum-bot-api"
    oidc_jwks_url: str | None = None  # defaults to <issuer>/.well-known/openid-configuration → jwks_uri
    oidc_role_claim: str = "scrum_role"  # optional claim used for the first sign-in of a user

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3100"]
    public_app_url: str = "http://localhost:3000"  # frontend base for links in emails (/a/<token>)
    public_api_url: str = "http://localhost:8800/api/v1"  # API base for signed file links
    rate_limit_per_minute: int = 600

    # --- secrets --------------------------------------------------------------------------
    action_token_secret: SecretStr = SecretStr(_DEV_ACTION_SECRET)
    action_token_ttl_days: int = 7
    # Key-encryption key for envelope encryption of integration tokens (base64, 32 bytes).
    # In production mount it from OpenBao/Vault (CSI driver) instead of an env file.
    kek_base64: SecretStr = SecretStr(_DEV_KEK)
    kek_id: str = "local-kek-1"

    # --- providers (each has a fake for tests and demo mode) ------------------------------
    fake_providers: bool = False  # SCRUM_FAKE_PROVIDERS=1 forces every adapter to its fake
    meeting_provider: Literal["fake", "livekit"] = "fake"
    stt_provider: Literal["fake", "whisper"] = "fake"
    tts_provider: Literal["fake", "piper"] = "fake"
    pm_provider: Literal["fake", "jira"] = "fake"
    mail_provider: Literal["memory", "smtp"] = "smtp"
    blob_backend: Literal["local", "s3"] = "local"

    # LLM: any OpenAI-compatible server (Ollama, vLLM, llama.cpp server, LocalAI).
    # "heuristic" runs the deterministic rule engine only (no model server needed; used in CI).
    llm_provider: Literal["openai_compat", "heuristic"] = "openai_compat"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr = SecretStr("ollama")
    llm_fast_model: str = "llama3.2:3b"  # live conversation turns
    llm_strong_model: str = "qwen2.5:7b-instruct-q4_K_M"  # extraction
    llm_timeout_seconds: float = 120.0
    # Hard cap for one live conversation turn decision; slower answers fall back to heuristics.
    llm_turn_timeout_seconds: float = 4.0
    embed_provider: Literal["openai_compat", "hashing"] = "openai_compat"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768

    # Meetings: LiveKit (open-source WebRTC SFU).
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: SecretStr = SecretStr("secret")
    # Human join link for the room; the open-source LiveKit Meet app serves /rooms/<room>.
    meeting_join_url_template: str = "http://localhost:3001/rooms/{room}"
    bot_display_name: str = "Scrum Bot"

    # Speech.
    whisper_model: str = "base.en"
    whisper_device: str = "cpu"
    piper_voice: str = "en_US-lessac-medium"
    piper_voice_dir: str = ".data/piper"

    # Jira Cloud (OAuth 2.0 3LO).
    jira_client_id: str | None = None
    jira_client_secret: SecretStr | None = None
    jira_site_url: str | None = None  # https://acme.atlassian.net (resolved after OAuth)

    # Mail (SMTP; Mailpit locally on :1025, UI on :8025).
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    mail_from: str = "Scrum Bot <standup-bot@scrumbot.local>"

    # Blob storage (local disk or any S3 API: SeaweedFS, Garage, Ceph RGW, MinIO).
    blob_dir: str = ".data/blobs"
    s3_endpoint: str = "localhost:8333"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "scrum-bot"
    s3_secure: bool = False

    # --- product defaults -----------------------------------------------------------------
    standup_budget_seconds: int = 15 * 60
    per_person_min_seconds: int = 60
    per_person_max_seconds: int = 180
    person_auto_threshold: float = 0.85
    person_review_threshold: float = 0.60
    blocker_same_with_ticket: float = 0.80
    blocker_same_without_ticket: float = 0.90
    org_ids_for_jobs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_prod(self) -> Settings:
        if self.env == "prod":
            if self.auth_mode != "oidc":
                raise ValueError("SCRUM_AUTH_MODE must be 'oidc' in production")
            if self.action_token_secret.get_secret_value() == _DEV_ACTION_SECRET:
                raise ValueError("Set SCRUM_ACTION_TOKEN_SECRET in production")
            if self.kek_base64.get_secret_value() == _DEV_KEK:
                raise ValueError("Set SCRUM_KEK_BASE64 in production")
        if self.fake_providers:
            self.meeting_provider = "fake"
            self.stt_provider = "fake"
            self.tts_provider = "fake"
            self.pm_provider = "fake"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
