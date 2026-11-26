/**
 * Compile-time contract check: every backend response schema (generated from backend/openapi.json by
 * `npm run gen:api`) must be assignable to the hand-written type the UI uses. `tsc` fails on drift.
 */
import type { components } from "./schema";
import type * as T from "./types";

type S = components["schemas"];
type Assert<A extends B, B> = [A, B];

export type ApiContract = [
  Assert<S["Me"], T.Me>,
  Assert<S["UserOut"], T.User>,
  Assert<S["OrgSettings"], T.OrgSettings>,
  Assert<S["TeamOut"], T.Team>,
  Assert<S["TeamMemberOut"], T.TeamMember>,
  Assert<S["TemplateOut"], T.QuestionTemplate>,
  Assert<S["ScheduleOut"], T.Schedule>,
  Assert<S["IntegrationOut"], T.Integration>,
  Assert<S["SessionSummary"], T.SessionSummary>,
  Assert<S["SessionOut"], T.Session>,
  Assert<S["AttendanceOut"], T.Attendance>,
  Assert<S["TranscriptSegmentOut"], T.TranscriptSegment>,
  Assert<S["MemberUpdateOut"], T.MemberUpdate>,
  Assert<S["ReportOut"], T.Report>,
  Assert<S["BlockerOut"], T.Blocker>,
  Assert<S["BlockerDetailOut"], T.BlockerDetail>,
  Assert<S["ActionPreview"], T.ActionPreview>,
  Assert<S["ActionResult"], T.ActionResult>,
  Assert<S["ReviewItemOut"], T.ReviewItem>,
  Assert<S["ParticipationMetrics"], T.ParticipationMetrics>,
  Assert<S["BlockerMetrics"], T.BlockerMetrics>,
  Assert<S["CarryOverMetrics"], T.CarryOverMetrics>,
  Assert<S["Mismatch"], T.Mismatch>,
  Assert<S["DependencyGraph"], T.DependencyGraph>,
  Assert<S["BlockerTheme"], T.BlockerTheme>,
  Assert<S["BurndownOut"], T.Burndown>,
  Assert<S["AuditEntryOut"], T.AuditEntry>,
];
