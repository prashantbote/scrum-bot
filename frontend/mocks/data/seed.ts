import type {
  AuditEntry,
  BlockerAction,
  BlockerDetail,
  Integration,
  MemberUpdate,
  Attendance,
  OrgSettings,
  Question,
  QuestionTemplate,
  ReviewItem,
  Schedule,
  Session,
  Team,
  TranscriptSegment,
} from "@/lib/api/types";
import { at, shiftDate, storyFriday, weekdaysBetween } from "./clock";
import { TEAM_DEFS, USERS, firstName, userById, type SeedUser } from "./people";
import { buildStandup, type MemberDay } from "./standups";
import { renderDigestHtml } from "./report";

export type TeamRow = Omit<Team, "lead_name" | "member_count" | "next_run_at" | "active_template_version">;

export type ActionToken =
  | { kind: "blocker"; blocker_id: string; recipient_id: string; used: BlockerAction[]; expired: boolean }
  | { kind: "checkin"; session_id: string; user_id: string; used: boolean; expired: boolean };

export interface MockDb {
  version: number;
  storyFriday: string;
  org: OrgSettings & { id: string; onboarded: boolean };
  users: SeedUser[];
  teams: TeamRow[];
  members: Record<string, { user_id: string; speaking_order: number; pm_account_id: string | null }[]>;
  templates: QuestionTemplate[];
  schedules: Record<string, Omit<Schedule, "team_id">>;
  integrations: Integration[];
  sessions: Session[];
  attendance: Record<string, Attendance[]>;
  segments: Record<string, TranscriptSegment[]>;
  updates: Record<string, MemberUpdate[]>;
  reports: Record<string, string>;
  blockers: BlockerDetail[];
  reviewItems: ReviewItem[];
  actionTokens: Record<string, ActionToken>;
  audit: AuditEntry[];
  pmStatus: Record<string, string>;
}

export const DB_VERSION = 3;

/* ------------------------------------------------------------------ */

const PAY_TICKETS: [string, string][] = [
  ["PROJ-131", "Card tokenization"],
  ["PROJ-134", "UPI retry flow"],
  ["PROJ-136", "Fraud rules engine"],
  ["PROJ-138", "Webhook signature validation"],
  ["PROJ-142", "Refund API"],
  ["PROJ-147", "Invoice PDF"],
  ["PROJ-150", "Payment UI"],
  ["PROJ-152", "Merchant onboarding form"],
  ["PROJ-155", "Settlement report export"],
  ["PROJ-158", "Payout reconciliation"],
];
const BE_TICKETS: [string, string][] = [
  ["BE-210", "Sandbox credential rotation"],
  ["BE-214", "Rate limiter"],
  ["BE-219", "Ledger service migration"],
  ["BE-223", "Kafka consumer lag alerts"],
  ["BE-227", "API contract v2"],
  ["BE-230", "Postgres connection pooling"],
];

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function genericDay(user: string, date: string, teamId: string): MemberDay {
  const pool = teamId === "team-payments" ? PAY_TICKETS : BE_TICKETS;
  const h = hash(`${user}-${date}`);
  const a = pool[h % pool.length]!;
  const b = pool[(h >>> 3) % pool.length]!;
  const status = h % 29 === 0 ? "absent" : h % 13 === 0 ? "async" : "present";
  const verbs = ["Implemented", "Wrapped up", "Fixed edge cases in", "Wrote tests for", "Reviewed PRs for"];
  const plans = ["Continue", "Start on", "Pair on", "Polish", "Ship"];
  return {
    user,
    status,
    done: [{ text: `${verbs[h % verbs.length]} ${a[1]}`, tickets: [a[0]] }],
    today: [{ text: `${plans[(h >>> 5) % plans.length]} ${b[1]}`, tickets: [b[0]] }],
  };
}

function questionsFor(teamId: string, version: number, followup: Question["followup_policy"]): Question[] {
  const texts: [string, Question["type"]][] = [
    ["What did you complete yesterday?", "ticket_list"],
    ["What will you work on today?", "ticket_list"],
    ["Any blockers or dependencies?", "text"],
  ];
  return texts.map(([text, type], i) => ({
    id: `q-${teamId}-v${version}-${i + 1}`,
    position: i + 1,
    text,
    type,
    required: true,
    followup_policy: i === 2 ? "if_vague" : followup,
    max_followups: followup === "none" && i !== 2 ? 0 : 2,
  }));
}

/* ------------------------------------------------------------------ */
/* Story week (Payments) — mirrors the "A day with Scrum Bot" narrative */
/* ------------------------------------------------------------------ */

function storyWeek(fri: string): Record<string, MemberDay[]> {
  const mon = shiftDate(fri, -4);
  const tue = shiftDate(fri, -3);
  const wed = shiftDate(fri, -2);
  const thu = shiftDate(fri, -1);

  const priyaReview = {
    text: "Waiting on code review for the Payment UI",
    say: "Still waiting for a code review on PROJ-150. Arjun said he'd look at it.",
    onRaw: "Arjun",
    onUser: "u-arjun",
    tickets: ["PROJ-150"],
    severity: "medium" as const,
    confidence: 0.93,
  };

  return {
    [mon]: [
      { user: "u-rahul", status: "present", done: [{ text: "Refund API request validation", tickets: ["PROJ-142"] }], today: [{ text: "Refund API main logic", tickets: ["PROJ-142"] }] },
      {
        user: "u-amit",
        status: "present",
        done: [{ text: "Webhook signature validation", tickets: ["PROJ-138"] }],
        today: [{ text: "Deploy webhook validation to staging", tickets: ["PROJ-138"] }],
        blockers: [
          {
            text: "Staging DB migrations failing, blocks deploy",
            say: "Staging migrations are failing, so I can't deploy PROJ-138. DevOps is looking at it.",
            onRaw: "DevOps",
            onUser: null,
            tickets: ["PROJ-138"],
            severity: "high",
            confidence: 0.9,
          },
        ],
      },
      { user: "u-priya", status: "present", done: [{ text: "Payment UI responsive layout", tickets: ["PROJ-150"] }], today: [{ text: "Address design feedback on Payment UI", tickets: ["PROJ-150"] }], blockers: [priyaReview] },
      { user: "u-karan", status: "present", done: [{ text: "Payout reconciliation job skeleton", tickets: ["PROJ-158"] }], today: [{ text: "Payout reconciliation matching rules", tickets: ["PROJ-158"] }] },
      { user: "u-sneha", status: "present", done: [{ text: "Settlement report query", tickets: ["PROJ-155"] }], today: [{ text: "Settlement report CSV export", tickets: ["PROJ-155"] }] },
    ],
    [tue]: [
      {
        user: "u-rahul",
        status: "present",
        done: [{ text: "Refund API main logic", tickets: ["PROJ-142"] }],
        today: [{ text: "Finish refund API tests once credentials arrive", tickets: ["PROJ-142"] }],
        blockers: [
          {
            text: "Needs sandbox credentials to test the refund API",
            say: "I need the sandbox credentials from Amit, so I'm stuck.",
            onRaw: "Amit from backend",
            onUser: "u-amit",
            tickets: ["PROJ-142"],
            severity: "high",
            confidence: 0.95,
          },
        ],
        script: [
          { who: "bot", text: "Rahul, yesterday you were working on PROJ-142, the refund API. How did that go?", q: 0 },
          { who: "member", text: "I finished the main logic, but the testing isn't done.", q: 0 },
          { who: "bot", text: "Got it. Will testing finish today, or is anything stopping it?", q: 2 },
          { who: "member", text: "I need the sandbox credentials from Amit, so I'm stuck.", q: 2 },
          { who: "bot", text: "What's your plan for today?", q: 1 },
          { who: "member", text: "Finish the refund API tests as soon as I have the credentials.", q: 1 },
          { who: "bot", text: "So: refund logic done, testing pending, blocked on sandbox credentials from Amit. Correct?", q: -1 },
          { who: "member", text: "Yes.", q: -1 },
        ],
      },
      { user: "u-amit", status: "present", done: [{ text: "Fixed staging migration ordering", tickets: ["PROJ-138"] }], today: [{ text: "Rotate sandbox credentials", tickets: ["BE-210"] }] },
      { user: "u-priya", status: "present", done: [{ text: "Payment UI design feedback", tickets: ["PROJ-150"] }], today: [{ text: "Payment UI error states", tickets: ["PROJ-150"] }], blockers: [{ ...priyaReview, say: "PROJ-150 is still waiting on review." }] },
      {
        user: "u-karan",
        status: "async",
        done: [{ text: "Payout reconciliation matching rules", tickets: ["PROJ-158"] }],
        today: [{ text: "Integrate payouts with the v2 API", tickets: ["PROJ-160"] }],
        blockers: [
          {
            text: "Waiting on the v2 API contract from Backend Platform",
            say: "Waiting on the API contract from the backend team for PROJ-160.",
            onRaw: "Backend team",
            onUser: "u-arjun",
            tickets: ["PROJ-160"],
            severity: "medium",
            confidence: 0.88,
          },
        ],
      },
      { user: "u-sneha", status: "present", done: [{ text: "Settlement report CSV export", tickets: ["PROJ-155"] }], today: [{ text: "Settlement report filters", tickets: ["PROJ-155"] }], deps: [{ text: "Settlement schema sign-off", onRaw: "Meera", onUser: "u-meera", onTeam: "team-backend", tickets: ["PROJ-155"] }] },
    ],
    [wed]: [
      { user: "u-rahul", status: "present", done: [{ text: "Refund API tests", tickets: ["PROJ-142"] }], today: [{ text: "Refund API docs and handoff", tickets: ["PROJ-142"] }] },
      { user: "u-amit", status: "present", done: [{ text: "Sandbox credential rotation", tickets: ["BE-210"] }], today: [{ text: "Webhook retry configuration", tickets: ["PROJ-138"] }] },
      { user: "u-priya", status: "present", done: [{ text: "Payment UI error states", tickets: ["PROJ-150"] }], today: [{ text: "Payment UI accessibility pass", tickets: ["PROJ-150"] }], blockers: [{ ...priyaReview, say: "Still no review on PROJ-150." }] },
      { user: "u-karan", status: "present", done: [{ text: "Payout API client stub", tickets: ["PROJ-160"] }], today: [{ text: "Payout integration against the v2 contract", tickets: ["PROJ-160"] }] },
      { user: "u-sneha", status: "absent", done: [], today: [] },
    ],
    [thu]: [
      {
        user: "u-rahul",
        status: "present",
        done: [{ text: "Refund API docs", tickets: ["PROJ-142"] }],
        today: [{ text: "Webhook retry integration", tickets: ["PROJ-138"] }],
        deps: [{ text: "Webhook retry config", onRaw: "Amit", onUser: null, onTeam: null, tickets: ["PROJ-138"] }],
      },
      { user: "u-amit", status: "present", done: [{ text: "Webhook retry configuration", tickets: ["PROJ-138"] }], today: [{ text: "Rate limiter rollout", tickets: ["BE-214"] }] },
      { user: "u-priya", status: "present", done: [{ text: "Payment UI accessibility pass", tickets: ["PROJ-150"] }], today: [{ text: "Start Invoice PDF", tickets: ["PROJ-147"] }], blockers: [{ ...priyaReview, say: "I'm still waiting for the code review on PROJ-150." }] },
      { user: "u-karan", status: "present", done: [{ text: "Payout integration", tickets: ["PROJ-160"] }], today: [{ text: "Payout reconciliation tests", tickets: ["PROJ-158"] }] },
      { user: "u-sneha", status: "present", done: [{ text: "Settlement report export", tickets: ["PROJ-155"] }], today: [{ text: "Merchant onboarding form validation", tickets: ["PROJ-152"] }] },
    ],
    [fri]: [
      { user: "u-rahul", status: "present", done: [{ text: "Webhook retry integration", tickets: ["PROJ-138"] }], today: [{ text: "Refund API load test", tickets: ["PROJ-142"] }] },
      { user: "u-amit", status: "present", done: [{ text: "Rate limiter rollout", tickets: ["BE-214"] }], today: [{ text: "Ledger migration dry run", tickets: ["BE-219"] }] },
      { user: "u-priya", status: "present", done: [{ text: "Invoice PDF layout", tickets: ["PROJ-147"] }], today: [{ text: "Invoice PDF totals", tickets: ["PROJ-147"] }], blockers: [{ ...priyaReview, say: "PROJ-150 review is still pending." }] },
      { user: "u-karan", status: "present", done: [{ text: "Payout reconciliation tests", tickets: ["PROJ-158"] }], today: [{ text: "Payout dashboard", tickets: ["PROJ-158"] }] },
      { user: "u-sneha", status: "present", done: [{ text: "Merchant onboarding form validation", tickets: ["PROJ-152"] }], today: [{ text: "Merchant onboarding API wiring", tickets: ["PROJ-152"] }] },
    ],
  };
}

/* ------------------------------------------------------------------ */

export function createSeed(today: Date = new Date()): MockDb {
  const fri = storyFriday(today);
  const mon = shiftDate(fri, -4);
  const tue = shiftDate(fri, -3);
  const wed = shiftDate(fri, -2);
  const thu = shiftDate(fri, -1);
  const story = storyWeek(fri);

  const db: MockDb = {
    version: DB_VERSION,
    storyFriday: fri,
    org: {
      id: "org-acme",
      name: "Acme Payments Pvt Ltd",
      onboarded: true,
      consent_text: "This standup is being recorded for notes.",
      retention_days_audio: 0,
      retention_days_transcript: 90,
      escalation_days: 3,
    },
    users: USERS.map((x) => ({ ...x, aliases: [...x.aliases] })),
    teams: TEAM_DEFS.map((t) => ({
      id: t.id,
      name: t.name,
      lead_user_id: t.lead,
      timezone: t.timezone,
      meeting_provider: "recall_teams",
      active: true,
    })),
    members: Object.fromEntries(
      TEAM_DEFS.map((t) => [
        t.id,
        t.members.map((user_id, i) => ({ user_id, speaking_order: i + 1, pm_account_id: userById(user_id).pm_account_id })),
      ]),
    ),
    templates: [],
    schedules: {},
    integrations: [
      { id: "int-teams", kind: "teams", status: "connected", display_name: "Microsoft Teams", detail: "acme.onmicrosoft.com · Recall.ai bot", last_checked_at: at(fri, "09:00") },
      { id: "int-jira", kind: "jira", status: "connected", display_name: "Jira Cloud", detail: "acme.atlassian.net · PROJ, BE", last_checked_at: at(fri, "09:00") },
      { id: "int-mail", kind: "mail", status: "expiring", display_name: "Email (Microsoft Graph)", detail: "standup-bot@acme.example · token expires in 6 days", last_checked_at: at(fri, "09:00") },
      { id: "int-ado", kind: "ado", status: "disconnected", display_name: "Azure DevOps", detail: "Not connected", last_checked_at: null },
    ],
    sessions: [],
    attendance: {},
    segments: {},
    updates: {},
    reports: {},
    blockers: [],
    reviewItems: [],
    actionTokens: {},
    audit: [],
    pmStatus: { "PROJ-142": "Done", "PROJ-150": "In Review", "PROJ-155": "In Progress", "PROJ-138": "Done" },
  };

  /* templates + schedules */
  for (const t of TEAM_DEFS) {
    const v1: QuestionTemplate = {
      id: `tpl-${t.id}-v1`,
      team_id: t.id,
      version: 1,
      is_active: t.id !== "team-payments",
      created_by_name: userById(t.lead).display_name,
      created_at: at(shiftDate(fri, -40), "10:00"),
      questions: questionsFor(t.id, 1, "none"),
    };
    db.templates.push(v1);
    if (t.id === "team-payments") {
      db.templates.push({
        id: `tpl-${t.id}-v2`,
        team_id: t.id,
        version: 2,
        is_active: true,
        created_by_name: "Neha Kapoor",
        created_at: at(shiftDate(fri, -30), "16:20"),
        questions: questionsFor(t.id, 2, "if_vague"),
      });
    }
    db.schedules[t.id] = {
      cron: t.cron,
      timezone: t.timezone,
      holiday_calendar: "IN",
      skip_dates: [shiftDate(fri, 13)],
      async_window_minutes: 120,
      lead_minutes: 5,
      paused: false,
      join_url: `https://teams.microsoft.com/l/meetup-join/${t.id}`,
    };
  }

  /* sessions: four weeks of weekdays */
  const dates = weekdaysBetween(shiftDate(fri, -25), fri);
  for (const t of TEAM_DEFS) {
    const tpl = db.templates.find((x) => x.team_id === t.id && x.is_active)!;
    const startTime = t.cron.startsWith("30 10") ? "10:30" : "10:00";
    for (const date of dates) {
      const days: MemberDay[] =
        t.id === "team-payments" && story[date] ? story[date]! : t.members.map((m) => genericDay(m, date, t.id));
      const id = `ses-${t.id.replace("team-", "")}-${date}`;
      const built = buildStandup({ sessionId: id, date, startTime, questions: tpl.questions, days });
      const attended = built.attendance.filter((a) => a.status !== "absent").length;
      db.sessions.push({
        id,
        team_id: t.id,
        team_name: t.name,
        run_date: date,
        status: "delivered",
        attendance_pct: attended / built.attendance.length,
        blocker_count: built.updates.reduce((n, u) => n + u.blockers.length, 0),
        duration_seconds: built.durationSeconds,
        template_version: tpl.version,
        started_at: built.startedAt,
        ended_at: built.endedAt,
      });
      db.attendance[id] = built.attendance;
      db.segments[id] = built.segments;
      db.updates[id] = built.updates;
      db.reports[id] = renderDigestHtml({ teamName: t.name, date, attendance: built.attendance, updates: built.updates });
    }
  }

  /* blockers (lifecycle state as of Friday) */
  const ev = (sessionDate: string, team = "payments", userId?: string) => {
    const sid = `ses-${team}-${sessionDate}`;
    const segs = db.segments[sid] ?? [];
    const own = segs.filter((s) => s.speaker_user_id === userId && s.question_id?.endsWith("-3"));
    return own.map((s) => ({ segment_id: s.id, session_id: sid, speaker_label: s.speaker_label, text: s.text, start_ms: s.start_ms }));
  };

  const blocker = (b: Omit<BlockerDetail, "team_name" | "reporter_name" | "blocked_on_name">): BlockerDetail => ({
    ...b,
    team_name: db.teams.find((t) => t.id === b.team_id)!.name,
    reporter_name: userById(b.reporter_user_id).display_name,
    blocked_on_name: b.blocked_on_user_id ? userById(b.blocked_on_user_id).display_name : null,
  });

  db.blockers.push(
    blocker({
      id: "blk-rahul-sandbox",
      team_id: "team-payments",
      description: "Needs sandbox credentials to test the refund API",
      reporter_user_id: "u-rahul",
      blocked_on_user_id: "u-amit",
      blocked_on_raw: "Amit from backend",
      ticket_keys: ["PROJ-142"],
      severity: "high",
      status: "resolved",
      days_open: 0,
      escalated: false,
      first_seen_at: at(tue, "10:33"),
      resolved_at: at(tue, "15:20"),
      events: [
        { at: at(tue, "10:33"), kind: "raised", actor_name: "Rahul Verma", note: "Raised in standup", session_id: `ses-payments-${tue}` },
        { at: at(tue, "10:50"), kind: "alert_sent", actor_name: "Scrum Bot", note: "Alert emailed to Amit Sharma (cc Rahul, Neha)", session_id: `ses-payments-${tue}` },
        { at: at(tue, "15:20"), kind: "resolved", actor_name: "Amit Sharma", note: "Marked resolved from email link", session_id: null },
      ],
      evidence: ev(tue, "payments", "u-rahul"),
    }),
    blocker({
      id: "blk-priya-review",
      team_id: "team-payments",
      description: "Waiting on code review for the Payment UI",
      reporter_user_id: "u-priya",
      blocked_on_user_id: "u-arjun",
      blocked_on_raw: "Arjun",
      ticket_keys: ["PROJ-150"],
      severity: "medium",
      status: "open",
      days_open: 4,
      escalated: true,
      first_seen_at: at(mon, "10:36"),
      resolved_at: null,
      events: [
        { at: at(mon, "10:36"), kind: "raised", actor_name: "Priya Nair", note: "Raised in standup", session_id: `ses-payments-${mon}` },
        { at: at(mon, "10:52"), kind: "alert_sent", actor_name: "Scrum Bot", note: "Alert emailed to Arjun Patel (cc Priya, Neha)", session_id: `ses-payments-${mon}` },
        { at: at(tue, "10:37"), kind: "mentioned", actor_name: "Priya Nair", note: "Matched to existing blocker (PROJ-150, 0.94)", session_id: `ses-payments-${tue}` },
        { at: at(wed, "10:37"), kind: "mentioned", actor_name: "Priya Nair", note: "Matched to existing blocker (PROJ-150, 0.92)", session_id: `ses-payments-${wed}` },
        { at: at(thu, "10:38"), kind: "mentioned", actor_name: "Priya Nair", note: "Matched to existing blocker — no repeat alert", session_id: `ses-payments-${thu}` },
        { at: at(thu, "10:51"), kind: "escalated", actor_name: "Scrum Bot", note: "Open for 3 days — escalated to Neha Kapoor", session_id: `ses-payments-${thu}` },
        { at: at(fri, "10:38"), kind: "mentioned", actor_name: "Priya Nair", note: "Matched to existing blocker", session_id: `ses-payments-${fri}` },
      ],
      evidence: [...ev(mon, "payments", "u-priya"), ...ev(thu, "payments", "u-priya")],
    }),
    blocker({
      id: "blk-karan-contract",
      team_id: "team-payments",
      description: "Waiting on the v2 API contract from Backend Platform",
      reporter_user_id: "u-karan",
      blocked_on_user_id: "u-arjun",
      blocked_on_raw: "Backend team",
      ticket_keys: ["PROJ-160"],
      severity: "medium",
      status: "resolved",
      days_open: 0,
      escalated: false,
      first_seen_at: at(tue, "11:15"),
      resolved_at: at(wed, "13:40"),
      events: [
        { at: at(tue, "11:15"), kind: "raised", actor_name: "Karan Mehta", note: "Raised via async check-in card", session_id: `ses-payments-${tue}` },
        { at: at(tue, "11:20"), kind: "alert_sent", actor_name: "Scrum Bot", note: "Alert emailed to Arjun Patel", session_id: `ses-payments-${tue}` },
        { at: at(tue, "14:05"), kind: "acknowledged", actor_name: "Arjun Patel", note: null, session_id: null },
        { at: at(wed, "13:40"), kind: "resolved", actor_name: "Arjun Patel", note: "Contract published (BE-227)", session_id: null },
      ],
      evidence: [],
    }),
    blocker({
      id: "blk-amit-staging",
      team_id: "team-payments",
      description: "Staging DB migrations failing, blocks deploy",
      reporter_user_id: "u-amit",
      blocked_on_user_id: null,
      blocked_on_raw: "DevOps",
      ticket_keys: ["PROJ-138"],
      severity: "high",
      status: "resolved",
      days_open: 0,
      escalated: false,
      first_seen_at: at(mon, "10:34"),
      resolved_at: at(wed, "17:50"),
      events: [
        { at: at(mon, "10:34"), kind: "raised", actor_name: "Amit Sharma", note: "Raised in standup", session_id: `ses-payments-${mon}` },
        { at: at(wed, "17:50"), kind: "resolved", actor_name: "Neha Kapoor", note: "Resolved from blockers board", session_id: null },
      ],
      evidence: ev(mon, "payments", "u-amit"),
    }),
  );

  // Previous-week history (for deltas and the age chart)
  const prevDur = [1.2, 1.8, 1.8];
  ["Merchant KYC API timeouts", "Waiting on design for invoice PDF", "Flaky payment gateway sandbox"].forEach((text, i) => {
    const start = shiftDate(fri, -11 + i); // Mon–Wed of the previous week
    const startIso = at(start, "10:40");
    const end = new Date(new Date(startIso).getTime() + prevDur[i]! * 86_400_000).toISOString();
    db.blockers.push(
      blocker({
        id: `blk-hist-${i}`,
        team_id: "team-payments",
        description: text,
        reporter_user_id: ["u-sneha", "u-priya", "u-rahul"][i]!,
        blocked_on_user_id: null,
        blocked_on_raw: ["Partner team", "Design", "Gateway vendor"][i]!,
        ticket_keys: [["PROJ-152"], ["PROJ-147"], ["PROJ-131"]][i]!,
        severity: "low",
        status: "resolved",
        days_open: 0,
        escalated: false,
        first_seen_at: startIso,
        resolved_at: end,
        events: [{ at: startIso, kind: "raised", actor_name: null, note: null, session_id: `ses-payments-${start}` }],
        evidence: [],
      }),
    );
  });

  db.blockers.push(
    blocker({
      id: "blk-meera-ledger",
      team_id: "team-backend",
      description: "Ledger migration needs a DBA maintenance window",
      reporter_user_id: "u-meera",
      blocked_on_user_id: null,
      blocked_on_raw: "DBA team",
      ticket_keys: ["BE-219"],
      severity: "medium",
      status: "acknowledged",
      days_open: 2,
      escalated: false,
      first_seen_at: at(wed, "10:06"),
      resolved_at: null,
      events: [
        { at: at(wed, "10:06"), kind: "raised", actor_name: "Meera Das", note: "Raised in standup", session_id: `ses-backend-${wed}` },
        { at: at(wed, "12:00"), kind: "acknowledged", actor_name: "Arjun Patel", note: null, session_id: null },
      ],
      evidence: [],
    }),
  );

  /* review queue */
  const thuRahulDep = (db.segments[`ses-payments-${thu}`] ?? []).find(
    (s) => s.speaker_user_id === "u-rahul" && s.text.includes("Amit"),
  );
  db.reviewItems.push(
    {
      id: "rev-person-amit",
      kind: "person_match",
      status: "pending",
      team_name: "Payments",
      raw_phrase: "Amit",
      evidence_quote: thuRahulDep?.text ?? "No blockers, but I depend on Amit for webhook retry config.",
      evidence_speaker: "Rahul Verma",
      session_id: `ses-payments-${thu}`,
      candidates: [
        { id: "u-amit", label: "Amit Sharma", sublabel: "Backend · works on PROJ-138", confidence: 0.74 },
        { id: "u-amits", label: "Amit Singh", sublabel: "QA", confidence: 0.61 },
      ],
      created_at: at(thu, "10:46"),
    },
    {
      id: "rev-blocker-staging",
      kind: "blocker_match",
      status: "pending",
      team_name: "Backend Platform",
      raw_phrase: "staging is flaky again",
      evidence_quote: "Staging has been flaky again since this morning's deploy.",
      evidence_speaker: "Meera Das",
      session_id: `ses-backend-${fri}`,
      candidates: [
        { id: "blk-amit-staging", label: "Staging DB migrations failing, blocks deploy", sublabel: "Payments · resolved Wed", confidence: 0.84 },
        { id: "new", label: "Create as a new blocker", sublabel: null, confidence: 0.16 },
      ],
      created_at: at(fri, "10:16"),
    },
    {
      id: "rev-pm-142",
      kind: "pm_writeback",
      status: "pending",
      team_name: "Payments",
      raw_phrase: "Refund API tests done",
      evidence_quote: "I finished refund API tests.",
      evidence_speaker: "Rahul Verma",
      session_id: `ses-payments-${wed}`,
      candidates: [{ id: "transition-done", label: "Transition PROJ-142 → Done", sublabel: "Jira currently: In Review", confidence: 0.9 }],
      created_at: at(wed, "10:47"),
    },
  );

  /* signed action links (see login page / README for the demo URLs) */
  db.actionTokens = {
    "demo-priya-review": { kind: "blocker", blocker_id: "blk-priya-review", recipient_id: "u-arjun", used: [], expired: false },
    "demo-rahul-sandbox": { kind: "blocker", blocker_id: "blk-rahul-sandbox", recipient_id: "u-amit", used: ["resolve"], expired: false },
    "demo-expired": { kind: "blocker", blocker_id: "blk-meera-ledger", recipient_id: "u-arjun", used: [], expired: true },
    "demo-checkin-karan": { kind: "checkin", session_id: `ses-payments-${fri}`, user_id: "u-karan", used: false, expired: false },
  };

  /* audit */
  const audit = (when: string, actor: string, action: string, entity_type: string, entity_id: string, diff: Record<string, unknown>) =>
    db.audit.push({ id: `aud-${db.audit.length + 1}`, at: when, actor_name: actor, action, entity_type, entity_id, diff });
  audit(at(shiftDate(fri, -40), "09:58"), "Deepa Iyer", "integration.connected", "integration", "int-teams", { kind: "teams", tenant: "acme.onmicrosoft.com" });
  audit(at(shiftDate(fri, -40), "10:02"), "Deepa Iyer", "integration.connected", "integration", "int-jira", { kind: "jira", site: "acme.atlassian.net" });
  audit(at(shiftDate(fri, -40), "10:05"), "Neha Kapoor", "team.created", "team", "team-payments", { name: "Payments", timezone: "Asia/Kolkata" });
  audit(at(shiftDate(fri, -40), "10:08"), "Neha Kapoor", "schedule.updated", "schedule", "team-payments", { cron: [null, "30 10 * * 1-5"] });
  audit(at(shiftDate(fri, -30), "16:20"), "Neha Kapoor", "template.created", "question_template", "tpl-team-payments-v2", { version: 2, followup_policy: ["none", "if_vague"] });
  audit(at(tue, "10:50"), "Scrum Bot", "mail.sent", "notification", `ses-payments-${tue}`, { type: "digest", recipients: 2 });
  audit(at(tue, "10:50"), "Scrum Bot", "mail.sent", "notification", "blk-rahul-sandbox", { type: "blocker_alert", to: "amit.sharma@acme.example" });
  audit(at(tue, "15:20"), "Amit Sharma", "blocker.resolved", "blocker", "blk-rahul-sandbox", { status: ["open", "resolved"], via: "email_link" });
  audit(at(thu, "10:51"), "Scrum Bot", "mail.sent", "notification", "blk-priya-review", { type: "escalation", to: "neha.kapoor@acme.example" });
  audit(at(fri, "10:50"), "Scrum Bot", "mail.sent", "notification", `ses-payments-${fri}`, { type: "digest", recipients: 2 });
  db.audit.reverse();

  return db;
}

export { firstName };
