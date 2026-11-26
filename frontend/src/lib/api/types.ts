/**
 * API types mirroring docs/BACKEND_IMPLEMENTATION_PLAN.md §4–§6.
 *
 * Hand-written until the backend publishes backend/openapi.json. Once it does, run
 * `npm run gen:api` to produce ./schema.d.ts and re-export the generated component types here,
 * so the rest of the app keeps importing from "@/lib/api/types".
 */

export type UUID = string;
export type ISODate = string; // "2026-11-10"
export type ISODateTime = string; // "2026-11-10T10:30:00+05:30"

export type Role = "org_admin" | "scrum_lead" | "member" | "viewer";

export interface Me {
  id: UUID;
  org_id: UUID;
  org_name: string;
  display_name: string;
  email: string;
  role: Role;
  /** Teams this user leads (scrum_lead) or belongs to (member). */
  lead_team_ids: UUID[];
  member_team_ids: UUID[];
  onboarded: boolean;
}

export interface User {
  id: UUID;
  display_name: string;
  email: string;
  role: Role;
  department: string | null;
  aliases: string[];
}

export interface Paginated<T> {
  items: T[];
  next_cursor: string | null;
}

/* ---------- Org ---------- */
export interface OrgSettings {
  name: string;
  consent_text: string;
  retention_days_audio: number;
  retention_days_transcript: number;
  escalation_days: number;
}

/* ---------- Teams ---------- */
export type MeetingProviderKind = "livekit" | "fake" | "recall_teams" | "graph_bridge" | "recall_zoom" | "recall_meet";

export interface Team {
  id: UUID;
  name: string;
  lead_user_id: UUID;
  lead_name: string;
  timezone: string;
  member_count: number;
  meeting_provider: MeetingProviderKind;
  active: boolean;
  next_run_at: ISODateTime | null;
  active_template_version: number | null;
}

export interface TeamCreate {
  name: string;
  lead_user_id: UUID;
  timezone: string;
}

export interface TeamMember {
  user_id: UUID;
  display_name: string;
  email: string;
  department: string | null;
  speaking_order: number;
  pm_account_id: string | null;
  aliases: string[];
}

export interface TeamMemberInput {
  user_id: UUID;
  speaking_order: number;
  pm_account_id: string | null;
}

/* ---------- Question templates ---------- */
export type QuestionType = "text" | "yes_no" | "ticket_list";
export type FollowupPolicy = "none" | "if_vague" | "always";

export interface Question {
  id: UUID;
  position: number;
  text: string;
  type: QuestionType;
  required: boolean;
  followup_policy: FollowupPolicy;
  max_followups: number;
}

export type QuestionInput = Omit<Question, "id">;

export interface QuestionTemplate {
  id: UUID;
  team_id: UUID;
  version: number;
  is_active: boolean;
  created_by_name: string;
  created_at: ISODateTime;
  questions: Question[];
}

/* ---------- Schedule ---------- */
export interface Schedule {
  team_id: UUID;
  cron: string; // "30 10 * * 1-5"
  timezone: string;
  holiday_calendar: string | null; // e.g. "IN" public holidays
  skip_dates: ISODate[];
  async_window_minutes: number;
  lead_minutes: number;
  paused: boolean;
  join_url: string | null;
}

export type ScheduleInput = Omit<Schedule, "team_id" | "join_url">;

/* ---------- Integrations ---------- */
export type IntegrationKind = "teams" | "jira" | "mail" | "ado";
export type IntegrationStatus = "connected" | "error" | "expiring" | "disconnected";

export interface Integration {
  id: UUID;
  kind: IntegrationKind;
  status: IntegrationStatus;
  display_name: string;
  detail: string;
  last_checked_at: ISODateTime | null;
}

/* ---------- Sessions ---------- */
export type SessionStatus = "scheduled" | "running" | "extracting" | "delivered" | "skipped" | "failed";
export type AttendanceStatus = "present" | "absent" | "async";

export interface SessionSummary {
  id: UUID;
  team_id: UUID;
  team_name: string;
  run_date: ISODate;
  status: SessionStatus;
  attendance_pct: number;
  blocker_count: number;
  duration_seconds: number | null;
}

export interface Session extends SessionSummary {
  template_version: number;
  started_at: ISODateTime | null;
  ended_at: ISODateTime | null;
}

export interface Attendance {
  user_id: UUID;
  display_name: string;
  status: AttendanceStatus;
  joined_at: ISODateTime | null;
}

export interface TranscriptSegment {
  id: UUID;
  speaker_user_id: UUID | null;
  speaker_label: string; // "Scrum Bot" | member name
  question_id: UUID | null;
  question_text: string | null;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number;
}

export type WorkStatus = "done" | "in_progress" | "planned";

export interface WorkItem {
  summary: string;
  ticket_keys: string[];
  status: WorkStatus;
  evidence_segment_ids: UUID[];
}

export type Severity = "low" | "medium" | "high";

export interface ExtractedBlocker {
  description: string;
  blocked_on_raw: string | null;
  blocked_on_member_id: UUID | null;
  ticket_keys: string[];
  severity: Severity;
  confidence: number;
  evidence_segment_ids: UUID[];
}

export interface Dependency {
  description: string;
  on_raw: string;
  on_member_id: UUID | null;
  on_team_id: UUID | null;
  ticket_keys: string[];
  evidence_segment_ids: UUID[];
}

export interface MemberUpdate {
  member_id: UUID;
  display_name: string;
  attendance: AttendanceStatus;
  source: "voice" | "async";
  completed: WorkItem[];
  planned: WorkItem[];
  blockers: ExtractedBlocker[];
  dependencies: Dependency[];
  challenges: string[];
}

export interface Report {
  session_id: UUID;
  html: string;
  pdf_url: string | null; // short-lived signed link
  recipients: string[];
  sent_at: ISODateTime | null;
}

/* ---------- Blockers ---------- */
export type BlockerStatus = "open" | "acknowledged" | "resolved" | "needs_review";

export interface BlockerEvent {
  at: ISODateTime;
  kind: "raised" | "mentioned" | "alert_sent" | "acknowledged" | "escalated" | "resolved" | "reopened";
  actor_name: string | null;
  note: string | null;
  session_id: UUID | null;
}

export interface Blocker {
  id: UUID;
  team_id: UUID;
  team_name: string;
  description: string;
  reporter_user_id: UUID;
  reporter_name: string;
  blocked_on_user_id: UUID | null;
  blocked_on_name: string | null;
  blocked_on_raw: string | null;
  ticket_keys: string[];
  severity: Severity;
  status: BlockerStatus;
  days_open: number;
  escalated: boolean;
  first_seen_at: ISODateTime;
  resolved_at: ISODateTime | null;
}

export interface BlockerEvidence {
  segment_id: UUID;
  session_id: UUID;
  speaker_label: string;
  text: string;
  start_ms: number;
}

export interface BlockerDetail extends Blocker {
  events: BlockerEvent[];
  evidence: BlockerEvidence[];
}

export interface BlockerPatch {
  status?: BlockerStatus;
  blocked_on_user_id?: UUID | null;
}

/* ---------- Public actions ---------- */
export type BlockerAction = "acknowledge" | "resolve";

export interface ActionPreview {
  kind: "blocker" | "checkin";
  expired: boolean;
  already_done: boolean;
  allowed_actions: BlockerAction[];
  blocker?: Pick<Blocker, "description" | "ticket_keys" | "reporter_name" | "team_name" | "status" | "days_open"> | null;
  checkin?: {
    member_name: string;
    team_name: string;
    run_date: ISODate;
    questions: Pick<Question, "id" | "text" | "required">[];
  } | null;
}

export interface ActionResult {
  status: BlockerStatus | "submitted";
}

/* ---------- Review queue ---------- */
export type ReviewKind = "person_match" | "blocker_match" | "pm_writeback";

export interface ReviewCandidate {
  id: UUID;
  label: string;
  sublabel: string | null;
  confidence: number;
}

export interface ReviewItem {
  id: UUID;
  kind: ReviewKind;
  status: "pending" | "approved" | "rejected";
  team_name: string;
  raw_phrase: string;
  evidence_quote: string;
  evidence_speaker: string;
  session_id: UUID | null;
  candidates: ReviewCandidate[];
  created_at: ISODateTime;
}

/* ---------- Metrics ---------- */
export interface MetricsQuery {
  team: UUID;
  from: ISODate;
  to: ISODate;
}

export interface ParticipationPoint {
  date: ISODate;
  rate: number; // 0..1
  present: number;
  async: number;
  absent: number;
}

export interface ParticipationMetrics {
  rate: number;
  delta: number; // vs previous period, percentage points
  series: ParticipationPoint[];
}

export interface BlockerMetrics {
  raised: number;
  resolved: number;
  open: number;
  avg_resolve_days: number;
  avg_resolve_delta: number;
  age_buckets: { bucket: string; count: number }[];
  weekly: { week: string; raised: number; resolved: number }[];
}

export interface CarryOverMetrics {
  rate: number;
  delta: number;
  series: { date: ISODate; rate: number }[];
}

export interface Mismatch {
  member_name: string;
  ticket_key: string;
  said: string;
  pm_status: string;
  session_id: UUID;
  date: ISODate;
}

export interface DependencyGraph {
  nodes: { id: string; label: string; kind: "team" | "member"; is_self: boolean }[];
  edges: { source: string; target: string; weight: number }[];
}

export interface BlockerTheme {
  label: string;
  count: number;
  trend: "up" | "down" | "flat";
}

export interface Burndown {
  sprint_name: string;
  points: { date: ISODate; ideal: number; remaining: number }[];
}

/* ---------- Audit ---------- */
export interface AuditEntry {
  id: UUID;
  at: ISODateTime;
  actor_name: string;
  action: string;
  entity_type: string;
  entity_id: string;
  diff: Record<string, unknown>;
}

/* ---------- Errors ---------- */
export interface ProblemDetails {
  type?: string;
  title: string;
  status: number;
  detail?: string;
  errors?: { field: string; message: string }[];
}
