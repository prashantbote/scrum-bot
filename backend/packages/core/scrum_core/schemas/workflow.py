"""Temporal workflow/activity payloads (pydantic data converter). Shared so services never import each other."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel

# Task queues (plan §7.3)
DEFAULT_QUEUE = "standups"
VOICE_QUEUE = "voice-agents"
INTELLIGENCE_QUEUE = "intelligence"
DELIVERY_QUEUE = "delivery"

WORKFLOW_NAME = "DailyStandupWorkflow"
RESEND_DIGEST_WORKFLOW = "ResendDigestWorkflow"
BLOCKER_ALERTS_WORKFLOW = "BlockerAlertsWorkflow"


def schedule_id(team_id: UUID | str) -> str:
    return f"standup-{team_id}"


def workflow_id(team_id: UUID | str, run_date: date | str, *, manual: bool = False) -> str:
    return f"standup-{team_id}-{run_date}" + ("-manual" if manual else "")


class StandupInput(BaseModel):
    org_id: UUID
    team_id: UUID
    # None → "today in the team's time zone", resolved by load_context (Temporal schedules can't template args).
    run_date: date | None = None
    manual: bool = False


class TicketRef(BaseModel):
    key: str
    summary: str
    status: str


class StaleBlocker(BaseModel):
    id: UUID
    description: str


class MemberCtx(BaseModel):
    user_id: UUID
    display_name: str
    first_name: str
    email: str
    aliases: list[str] = []
    department: str | None = None
    pm_account_id: str | None = None
    open_tickets: list[TicketRef] = []
    # Acknowledged blockers not mentioned for 2+ sessions: the bot asks "Is that resolved now?" (plan §9.3)
    stale_blockers: list[StaleBlocker] = []


class QuestionCtx(BaseModel):
    id: UUID
    position: int
    text: str
    type: str
    required: bool
    followup_policy: str
    max_followups: int


class StandupContext(BaseModel):
    org_id: UUID
    team_id: UUID
    team_name: str
    timezone: str
    run_date: date
    session_id: UUID
    skip_today: bool = False
    skip_reason: str | None = None
    lead_user_id: UUID
    lead_email: str
    lead_name: str
    members: list[MemberCtx]
    template_id: UUID | None
    questions: list[QuestionCtx]
    consent_text: str
    async_window_minutes: int
    join_url: str | None
    vocabulary: list[str] = []
    escalation_days: int = 3
    pm_writeback_enabled: bool = False


class VoiceResult(BaseModel):
    session_id: UUID
    attended_user_ids: list[UUID]
    segment_count: int
    duration_seconds: int
    resolved_blocker_ids: list[UUID] = []


class AsyncCheckinSignal(BaseModel):
    user_id: UUID


class AsyncRequest(BaseModel):
    org_id: UUID
    session_id: UUID
    user_ids: list[UUID]
    window_minutes: int


class SessionRef(BaseModel):
    org_id: UUID
    session_id: UUID
    team_id: UUID


class ExtractResult(BaseModel):
    org_id: UUID
    session_id: UUID
    team_id: UUID
    member_ids: list[UUID]


class BlockerRefs(BaseModel):
    org_id: UUID
    session_id: UUID
    team_id: UUID
    new_blocker_ids: list[UUID]
    matched_blocker_ids: list[UUID]


class SendResult(BaseModel):
    sent: int
    skipped: int


class ResendDigestInput(BaseModel):
    org_id: UUID
    session_id: UUID
    nonce: str


class BlockerAlertsInput(BaseModel):
    org_id: UUID
    team_id: UUID
    session_id: UUID | None = None
    blocker_ids: list[UUID]
