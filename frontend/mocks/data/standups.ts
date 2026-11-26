import type {
  Attendance,
  AttendanceStatus,
  Dependency,
  ExtractedBlocker,
  MemberUpdate,
  Question,
  Severity,
  TranscriptSegment,
  WorkItem,
} from "@/lib/api/types";
import { at } from "./clock";
import { firstName, userById } from "./people";

/* ------------------------------------------------------------------ */
/* Specs used to describe one member's standup on one day              */
/* ------------------------------------------------------------------ */

export interface ItemSpec {
  text: string;
  tickets?: string[];
}

export interface BlockerSpec {
  text: string;
  /** What the member says out loud. */
  say: string;
  onRaw: string | null;
  onUser: string | null;
  tickets: string[];
  severity: Severity;
  confidence: number;
}

export interface DepSpec {
  text: string;
  onRaw: string;
  onUser: string | null;
  onTeam: string | null;
  tickets: string[];
}

/** q = question index the line answers (0 yesterday, 1 today, 2 blockers); -1 = confirmation. */
export type Line = { who: "bot" | "member"; text: string; q: number };

export interface MemberDay {
  user: string;
  status: AttendanceStatus;
  done: ItemSpec[];
  today: ItemSpec[];
  blockers?: BlockerSpec[];
  deps?: DepSpec[];
  challenges?: string[];
  /** Custom conversation; otherwise a standard Q&A is generated. */
  script?: Line[];
}

export interface BuiltSession {
  segments: TranscriptSegment[];
  attendance: Attendance[];
  updates: MemberUpdate[];
  startedAt: string;
  endedAt: string;
  durationSeconds: number;
  /** Segment ids per member per question index — used to ground blockers. */
  evidence: Record<string, Record<number, string[]>>;
}

const join = (items: ItemSpec[]) => items.map((i) => i.text.charAt(0).toLowerCase() + i.text.slice(1)).join(", and ");

function defaultScript(day: MemberDay): Line[] {
  const name = firstName(day.user);
  const lastTicket = day.done[0]?.tickets?.[0];
  const opener = lastTicket
    ? `${name}, you had ${lastTicket} in progress. How did yesterday go?`
    : `${name}, what did you complete yesterday?`;
  const blockerAnswer = day.blockers?.length
    ? day.blockers.map((b) => b.say).join(" ")
    : day.deps?.length
      ? `No blockers, but I depend on ${day.deps[0]!.onRaw} for ${day.deps[0]!.text.toLowerCase()}.`
      : "No blockers today.";
  const summaryBits = [
    day.done.length ? `${day.done.map((d) => d.tickets?.[0] ?? d.text).join(", ")} done` : null,
    day.today.length ? `today ${day.today[0]!.text.toLowerCase()}` : null,
    day.blockers?.length ? `blocked on ${day.blockers[0]!.onRaw ?? "an external dependency"}` : "no blockers",
  ].filter(Boolean);
  return [
    { who: "bot", text: opener, q: 0 },
    { who: "member", text: day.done.length ? `I finished ${join(day.done)}.` : "Mostly reviews and meetings yesterday.", q: 0 },
    { who: "bot", text: "What will you work on today?", q: 1 },
    { who: "member", text: `Today I'll ${join(day.today)}.`, q: 1 },
    { who: "bot", text: "Any blockers or dependencies?", q: 2 },
    { who: "member", text: blockerAnswer, q: 2 },
    { who: "bot", text: `So: ${summaryBits.join("; ")}. Correct?`, q: -1 },
    { who: "member", text: "Yes, that's right.", q: -1 },
  ];
}

/** Rough speech duration for a line. */
const speechMs = (text: string) => Math.min(9000, Math.max(1600, text.length * 62));

export function buildStandup(opts: {
  sessionId: string;
  date: string;
  startTime: string;
  questions: Question[];
  days: MemberDay[];
}): BuiltSession {
  const { sessionId, date, startTime, questions, days } = opts;
  const segments: TranscriptSegment[] = [];
  const evidence: BuiltSession["evidence"] = {};
  let t = 4000; // bot joins and announces after a few seconds
  let n = 0;

  const push = (speaker: string | null, label: string, text: string, q: number) => {
    const dur = speechMs(text);
    const question = q >= 0 ? questions[q] : undefined;
    const seg: TranscriptSegment = {
      id: `seg-${sessionId}-${++n}`,
      speaker_user_id: speaker,
      speaker_label: label,
      question_id: question?.id ?? null,
      question_text: question?.text ?? null,
      start_ms: t,
      end_ms: t + dur,
      text,
      confidence: speaker ? 0.86 + ((n * 7) % 12) / 100 : 1,
    };
    segments.push(seg);
    t += dur + 700;
    return seg.id;
  };

  const present = days.filter((d) => d.status === "present");
  const absent = days.filter((d) => d.status !== "present").map((d) => firstName(d.user));

  push(
    null,
    "Scrum Bot",
    `Good morning, everyone! This standup is being recorded for notes. ${
      present[0] ? `Let's start with ${firstName(present[0].user)}.` : ""
    }`,
    -1,
  );

  present.forEach((day, i) => {
    evidence[day.user] = {};
    for (const line of day.script ?? defaultScript(day)) {
      const isMember = line.who === "member";
      const id = push(
        isMember ? day.user : null,
        isMember ? userById(day.user).display_name : "Scrum Bot",
        line.text,
        line.q,
      );
      if (isMember) (evidence[day.user]![line.q] ??= []).push(id);
    }
    const next = present[i + 1];
    if (next) push(null, "Scrum Bot", `Thanks, ${firstName(day.user)}. ${firstName(next.user)}, your turn.`, -1);
  });

  push(
    null,
    "Scrum Bot",
    `Thanks, everyone. ${absent.length ? `I'll send ${absent.join(" and ")} a quick check-in card. ` : ""}Have a productive day!`,
    -1,
  );

  const startedAt = at(date, startTime);
  const endedAt = at(date, startTime, t);

  const attendance: Attendance[] = days.map((d) => ({
    user_id: d.user,
    display_name: userById(d.user).display_name,
    status: d.status,
    joined_at: d.status === "present" ? at(date, startTime, 1000 * ((d.user.length * 13) % 50)) : null,
  }));

  const updates: MemberUpdate[] = days
    .filter((d) => d.status !== "absent")
    .map((d) => {
      const ev = evidence[d.user] ?? {};
      const item = (s: ItemSpec, status: WorkItem["status"], q: number): WorkItem => ({
        summary: s.text,
        ticket_keys: s.tickets ?? [],
        status,
        evidence_segment_ids: ev[q] ?? [],
      });
      const blockers: ExtractedBlocker[] = (d.blockers ?? []).map((b) => ({
        description: b.text,
        blocked_on_raw: b.onRaw,
        blocked_on_member_id: b.onUser,
        ticket_keys: b.tickets,
        severity: b.severity,
        confidence: b.confidence,
        evidence_segment_ids: ev[2] ?? [],
      }));
      const dependencies: Dependency[] = (d.deps ?? []).map((x) => ({
        description: x.text,
        on_raw: x.onRaw,
        on_member_id: x.onUser,
        on_team_id: x.onTeam,
        ticket_keys: x.tickets,
        evidence_segment_ids: ev[2] ?? [],
      }));
      return {
        member_id: d.user,
        display_name: userById(d.user).display_name,
        attendance: d.status,
        source: d.status === "async" ? "async" : "voice",
        completed: d.done.map((s) => item(s, "done", 0)),
        planned: d.today.map((s) => item(s, "planned", 1)),
        blockers,
        dependencies,
        challenges: d.challenges ?? [],
      };
    });

  return {
    segments,
    attendance,
    updates,
    startedAt,
    endedAt,
    durationSeconds: Math.round(t / 1000),
    evidence,
  };
}
