import { apiFetch } from "./client";
import type * as T from "./types";

/** One function per backend endpoint (docs/BACKEND_IMPLEMENTATION_PLAN.md §6.2). */
export const api = {
  /* auth / org */
  me: () => apiFetch<T.Me>("/me"),
  onboardOrg: (body: { name: string }) => apiFetch<T.Me>("/orgs/onboard", { method: "POST", body }),
  orgSettings: () => apiFetch<T.OrgSettings>("/org/settings"),
  updateOrgSettings: (body: Partial<T.OrgSettings>) =>
    apiFetch<T.OrgSettings>("/org/settings", { method: "PATCH", body }),

  /* users */
  users: (q?: { search?: string }) => apiFetch<T.Paginated<T.User>>("/users", { query: q }),
  syncUsers: () => apiFetch<{ added: number; updated: number }>("/users/sync", { method: "POST" }),
  updateUser: (id: string, body: Partial<Pick<T.User, "role" | "aliases">>) =>
    apiFetch<T.User>(`/users/${id}`, { method: "PATCH", body }),
  eraseUser: (id: string) => apiFetch<void>(`/users/${id}/erase`, { method: "POST" }),

  /* teams */
  teams: () => apiFetch<T.Paginated<T.Team>>("/teams"),
  team: (id: string) => apiFetch<T.Team>(`/teams/${id}`),
  createTeam: (body: T.TeamCreate) => apiFetch<T.Team>("/teams", { method: "POST", body }),
  updateTeam: (id: string, body: Partial<T.TeamCreate & { active: boolean }>) =>
    apiFetch<T.Team>(`/teams/${id}`, { method: "PATCH", body }),
  members: (teamId: string) => apiFetch<T.TeamMember[]>(`/teams/${teamId}/members`),
  setMembers: (teamId: string, body: T.TeamMemberInput[]) =>
    apiFetch<T.TeamMember[]>(`/teams/${teamId}/members`, { method: "PUT", body }),

  /* templates */
  templates: (teamId: string) => apiFetch<T.QuestionTemplate[]>(`/teams/${teamId}/templates`),
  createTemplate: (teamId: string, body: { questions: T.QuestionInput[] }) =>
    apiFetch<T.QuestionTemplate>(`/teams/${teamId}/templates`, { method: "POST", body }),
  activateTemplate: (templateId: string) =>
    apiFetch<T.QuestionTemplate>(`/templates/${templateId}/activate`, { method: "POST" }),

  /* schedule */
  schedule: (teamId: string) => apiFetch<T.Schedule>(`/teams/${teamId}/schedule`),
  saveSchedule: (teamId: string, body: T.ScheduleInput) =>
    apiFetch<T.Schedule>(`/teams/${teamId}/schedule`, { method: "PUT", body }),
  triggerNow: (teamId: string) =>
    apiFetch<{ workflow_id: string }>(`/teams/${teamId}/schedule/trigger-now`, { method: "POST" }),
  pauseSchedule: (teamId: string, paused: boolean) =>
    apiFetch<T.Schedule>(`/teams/${teamId}/schedule/pause`, { method: "POST", body: { paused } }),

  /* integrations */
  integrations: () => apiFetch<T.Integration[]>("/integrations"),
  connectIntegration: (kind: T.IntegrationKind) =>
    apiFetch<{ authorize_url: string; integration: T.Integration }>(`/integrations/${kind}/connect`, {
      method: "POST",
    }),
  testIntegration: (id: string) =>
    apiFetch<T.Integration>(`/integrations/${id}/test`, { method: "POST" }),
  deleteIntegration: (id: string) => apiFetch<void>(`/integrations/${id}`, { method: "DELETE" }),

  /* sessions */
  sessions: (teamId: string) => apiFetch<T.Paginated<T.SessionSummary>>(`/teams/${teamId}/sessions`),
  session: (id: string) => apiFetch<T.Session>(`/sessions/${id}`),
  attendance: (id: string) => apiFetch<T.Attendance[]>(`/sessions/${id}/attendance`),
  transcript: (id: string) => apiFetch<T.TranscriptSegment[]>(`/sessions/${id}/transcript`),
  updates: (id: string) => apiFetch<T.MemberUpdate[]>(`/sessions/${id}/updates`),
  report: (id: string) => apiFetch<T.Report>(`/sessions/${id}/report`),
  resendDigest: (id: string) =>
    apiFetch<{ queued: number }>(`/sessions/${id}/resend-digest`, { method: "POST" }),

  /* blockers */
  blockers: (q: { team?: string; status?: T.BlockerStatus }) =>
    apiFetch<T.Paginated<T.Blocker>>("/blockers", { query: q }),
  blocker: (id: string) => apiFetch<T.BlockerDetail>(`/blockers/${id}`),
  patchBlocker: (id: string, body: T.BlockerPatch) =>
    apiFetch<T.Blocker>(`/blockers/${id}`, { method: "PATCH", body }),

  /* public signed links */
  actionPreview: (token: string) =>
    apiFetch<T.ActionPreview>(`/actions/${encodeURIComponent(token)}`, { anonymous: true }),
  performAction: (token: string, action: T.BlockerAction) =>
    apiFetch<T.ActionResult>(`/actions/${encodeURIComponent(token)}`, {
      method: "POST",
      body: { action },
      anonymous: true,
    }),
  submitCheckin: (token: string, answers: Record<string, string>) =>
    apiFetch<T.ActionResult>(`/async-checkins/${encodeURIComponent(token)}`, {
      method: "POST",
      body: { answers },
      anonymous: true,
    }),

  /* review queue */
  reviewItems: (q?: { kind?: T.ReviewKind; status?: string }) =>
    apiFetch<T.Paginated<T.ReviewItem>>("/review-items", { query: q }),
  approveReview: (id: string, candidateId: string) =>
    apiFetch<T.ReviewItem>(`/review-items/${id}/approve`, { method: "POST", body: { candidate_id: candidateId } }),
  rejectReview: (id: string) => apiFetch<T.ReviewItem>(`/review-items/${id}/reject`, { method: "POST" }),

  /* metrics */
  participation: (q: T.MetricsQuery) => apiFetch<T.ParticipationMetrics>("/metrics/participation", { query: { ...q } }),
  blockerMetrics: (q: T.MetricsQuery) => apiFetch<T.BlockerMetrics>("/metrics/blockers", { query: { ...q } }),
  carryOver: (q: T.MetricsQuery) => apiFetch<T.CarryOverMetrics>("/metrics/carry-over", { query: { ...q } }),
  mismatches: (q: T.MetricsQuery) => apiFetch<T.Mismatch[]>("/metrics/mismatches", { query: { ...q } }),
  dependencies: (q: T.MetricsQuery) => apiFetch<T.DependencyGraph>("/metrics/dependencies", { query: { ...q } }),
  themes: (q: T.MetricsQuery) => apiFetch<T.BlockerTheme[]>("/metrics/themes", { query: { ...q } }),
  burndown: (q: T.MetricsQuery) => apiFetch<T.Burndown>("/metrics/burndown", { query: { ...q } }),

  /* audit */
  auditLog: (q?: { entity?: string; actor?: string }) =>
    apiFetch<T.Paginated<T.AuditEntry>>("/audit-log", { query: q }),
};
