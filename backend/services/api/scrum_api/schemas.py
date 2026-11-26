"""API DTOs. Field-for-field mirror of frontend/src/lib/api/types.ts (published as openapi.json)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from scrum_core.models.base import (
    AttendanceStatus,
    BlockerEventKind,
    BlockerStatus,
    FollowupPolicy,
    IntegrationKind,
    IntegrationStatus,
    MeetingProviderKind,
    QuestionType,
    ReviewKind,
    ReviewStatus,
    Role,
    SessionStatus,
    Severity,
)


class Model(BaseModel):
    # Response schemas mark defaulted fields as required: the API always sends them.
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class Paginated[T](Model):
    items: list[T]
    next_cursor: str | None = None


class ProblemError(Model):
    field: str
    message: str


class ProblemDetails(Model):
    type: str | None = None
    title: str
    status: int
    detail: str | None = None
    errors: list[ProblemError] | None = None


# ---------------------------------------------------------------- identity / org


class Me(Model):
    id: UUID
    org_id: UUID
    org_name: str
    display_name: str
    email: str
    role: Role
    lead_team_ids: list[UUID]
    member_team_ids: list[UUID]
    onboarded: bool


class OnboardIn(Model):
    name: str = Field(min_length=1, max_length=200)


class OrgSettings(Model):
    name: str
    consent_text: str
    retention_days_audio: int
    retention_days_transcript: int
    escalation_days: int


class OrgSettingsPatch(Model):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    consent_text: str | None = Field(default=None, min_length=1, max_length=1000)
    retention_days_audio: int | None = Field(default=None, ge=0, le=3650)
    retention_days_transcript: int | None = Field(default=None, ge=1, le=3650)
    escalation_days: int | None = Field(default=None, ge=1, le=30)


class UserOut(Model):
    id: UUID
    display_name: str
    email: str
    role: Role
    department: str | None
    aliases: list[str]


class UserPatch(Model):
    role: Role | None = None
    aliases: list[str] | None = None

    @field_validator("aliases")
    @classmethod
    def _clean(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else list(dict.fromkeys(a.strip() for a in v if a.strip()))


class SyncResult(Model):
    added: int
    updated: int


# ---------------------------------------------------------------- teams


class TeamOut(Model):
    id: UUID
    name: str
    lead_user_id: UUID
    lead_name: str
    timezone: str
    member_count: int
    meeting_provider: MeetingProviderKind
    active: bool
    next_run_at: datetime | None
    active_template_version: int | None


class TeamCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    lead_user_id: UUID | None = None
    timezone: str = "Asia/Kolkata"


class TeamPatch(Model):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    lead_user_id: UUID | None = None
    timezone: str | None = None
    active: bool | None = None


class TeamMemberOut(Model):
    user_id: UUID
    display_name: str
    email: str
    department: str | None
    speaking_order: int
    pm_account_id: str | None
    aliases: list[str]


class TeamMemberIn(Model):
    user_id: UUID
    speaking_order: int = 0
    pm_account_id: str | None = None


# ---------------------------------------------------------------- templates


class QuestionIn(Model):
    position: int = 0
    text: str = Field(min_length=3, max_length=300)
    type: QuestionType = QuestionType.text
    required: bool = True
    followup_policy: FollowupPolicy = FollowupPolicy.if_vague
    max_followups: int = Field(default=2, ge=0, le=3)


class QuestionOut(QuestionIn):
    id: UUID


class TemplateIn(Model):
    questions: list[QuestionIn] = Field(min_length=1, max_length=10)


class TemplateOut(Model):
    id: UUID
    team_id: UUID
    version: int
    is_active: bool
    created_by_name: str
    created_at: datetime
    questions: list[QuestionOut]


# ---------------------------------------------------------------- schedule


class ScheduleIn(Model):
    cron: str
    timezone: str
    holiday_calendar: str | None = None
    skip_dates: list[date] = []
    async_window_minutes: int = Field(default=120, ge=0, le=480)
    lead_minutes: int = Field(default=5, ge=0, le=60)
    paused: bool = False


class ScheduleOut(ScheduleIn):
    team_id: UUID
    join_url: str | None


class PauseIn(Model):
    paused: bool


class TriggerOut(Model):
    workflow_id: str


# ---------------------------------------------------------------- integrations


class IntegrationOut(Model):
    id: UUID
    kind: IntegrationKind
    status: IntegrationStatus
    display_name: str
    detail: str
    last_checked_at: datetime | None


class ConnectOut(Model):
    authorize_url: str | None
    integration: IntegrationOut


# ---------------------------------------------------------------- sessions


class SessionSummary(Model):
    id: UUID
    team_id: UUID
    team_name: str
    run_date: date
    status: SessionStatus
    attendance_pct: float
    blocker_count: int
    duration_seconds: int | None


class SessionOut(SessionSummary):
    template_version: int
    started_at: datetime | None
    ended_at: datetime | None


class AttendanceOut(Model):
    user_id: UUID
    display_name: str
    status: AttendanceStatus
    joined_at: datetime | None


class TranscriptSegmentOut(Model):
    id: UUID
    speaker_user_id: UUID | None
    speaker_label: str
    question_id: UUID | None
    question_text: str | None
    start_ms: int
    end_ms: int
    text: str
    confidence: float


class WorkItemOut(Model):
    summary: str
    ticket_keys: list[str]
    status: Literal["done", "in_progress", "planned"]
    evidence_segment_ids: list[UUID]


class ExtractedBlockerOut(Model):
    description: str
    blocked_on_raw: str | None
    blocked_on_member_id: UUID | None
    ticket_keys: list[str]
    severity: Severity
    confidence: float
    evidence_segment_ids: list[UUID]


class DependencyOut(Model):
    description: str
    on_raw: str
    on_member_id: UUID | None
    on_team_id: UUID | None
    ticket_keys: list[str]
    evidence_segment_ids: list[UUID]


class MemberUpdateOut(Model):
    member_id: UUID
    display_name: str
    attendance: AttendanceStatus
    source: Literal["voice", "async"]
    completed: list[WorkItemOut]
    planned: list[WorkItemOut]
    blockers: list[ExtractedBlockerOut]
    dependencies: list[DependencyOut]
    challenges: list[str]


class ReportOut(Model):
    session_id: UUID
    html: str
    pdf_url: str | None
    recipients: list[str]
    sent_at: datetime | None


class QueuedOut(Model):
    queued: int


# ---------------------------------------------------------------- blockers


class BlockerOut(Model):
    id: UUID
    team_id: UUID
    team_name: str
    description: str
    reporter_user_id: UUID
    reporter_name: str
    blocked_on_user_id: UUID | None
    blocked_on_name: str | None
    blocked_on_raw: str | None
    ticket_keys: list[str]
    severity: Severity
    status: BlockerStatus
    days_open: int
    escalated: bool
    first_seen_at: datetime
    resolved_at: datetime | None


class BlockerEventOut(Model):
    at: datetime
    kind: BlockerEventKind
    actor_name: str | None
    note: str | None
    session_id: UUID | None


class BlockerEvidenceOut(Model):
    segment_id: UUID
    session_id: UUID
    speaker_label: str
    text: str
    start_ms: int


class BlockerDetailOut(BlockerOut):
    events: list[BlockerEventOut]
    evidence: list[BlockerEvidenceOut]


class BlockerPatch(Model):
    status: BlockerStatus | None = None
    blocked_on_user_id: UUID | None = None
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- public actions


class ActionBlocker(Model):
    description: str
    ticket_keys: list[str]
    reporter_name: str
    team_name: str
    status: BlockerStatus
    days_open: int


class ActionQuestion(Model):
    id: UUID
    text: str
    required: bool


class ActionCheckin(Model):
    member_name: str
    team_name: str
    run_date: date
    questions: list[ActionQuestion]


class ActionPreview(Model):
    kind: Literal["blocker", "checkin"]
    expired: bool
    already_done: bool
    allowed_actions: list[Literal["acknowledge", "resolve"]]
    blocker: ActionBlocker | None = None
    checkin: ActionCheckin | None = None


class ActionIn(Model):
    action: Literal["acknowledge", "resolve"]


class CheckinIn(Model):
    answers: dict[str, str]


class ActionResult(Model):
    status: Literal["open", "acknowledged", "resolved", "needs_review", "submitted"]


class DemoLink(Model):
    label: str
    href: str


# ---------------------------------------------------------------- review queue


class ReviewCandidate(Model):
    id: str
    label: str
    sublabel: str | None
    confidence: float


class ReviewItemOut(Model):
    id: UUID
    kind: ReviewKind
    status: ReviewStatus
    team_name: str
    raw_phrase: str
    evidence_quote: str
    evidence_speaker: str
    session_id: UUID | None
    candidates: list[ReviewCandidate]
    created_at: datetime


class ApproveIn(Model):
    candidate_id: str


# ---------------------------------------------------------------- metrics


class ParticipationPoint(Model):
    date: date
    rate: float
    present: int
    async_: int = Field(serialization_alias="async", validation_alias="async")
    absent: int
    model_config = ConfigDict(populate_by_name=True)


class ParticipationMetrics(Model):
    rate: float
    delta: float
    series: list[ParticipationPoint]


class AgeBucket(Model):
    bucket: str
    count: int


class WeeklyBlockers(Model):
    week: str
    raised: int
    resolved: int


class BlockerMetrics(Model):
    raised: int
    resolved: int
    open: int
    avg_resolve_days: float
    avg_resolve_delta: float
    age_buckets: list[AgeBucket]
    weekly: list[WeeklyBlockers]


class RatePoint(Model):
    date: date
    rate: float


class CarryOverMetrics(Model):
    rate: float
    delta: float
    series: list[RatePoint]


class Mismatch(Model):
    member_name: str
    ticket_key: str
    said: str
    pm_status: str
    session_id: UUID
    date: date


class GraphNode(Model):
    id: str
    label: str
    kind: Literal["team", "member"]
    is_self: bool


class GraphEdge(Model):
    source: str
    target: str
    weight: int


class DependencyGraph(Model):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class BlockerTheme(Model):
    label: str
    count: int
    trend: Literal["up", "down", "flat"]


class BurndownPointOut(Model):
    date: date
    ideal: float
    remaining: float


class BurndownOut(Model):
    sprint_name: str
    points: list[BurndownPointOut]


# ---------------------------------------------------------------- audit


class AuditEntryOut(Model):
    id: UUID
    at: datetime
    actor_name: str
    action: str
    entity_type: str
    entity_id: str
    diff: dict[str, Any]


class UserExport(Model):
    user: UserOut
    teams: list[str]
    transcript_segments: list[dict[str, Any]]
    updates: list[dict[str, Any]]
    blockers_reported: list[dict[str, Any]]
    exported_at: datetime


class Health(Model):
    status: str
    checks: dict[str, str] = {}


class EmailIn(Model):
    email: EmailStr
