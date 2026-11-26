import { delay, http, HttpResponse, type PathParams } from "msw";
import type * as T from "@/lib/api/types";
import { fromCron, nextRuns } from "@/lib/schedule/cron";
import { getDb, persist } from "./db";
import { nowIso, shiftDate } from "./data/clock";
import { userById } from "./data/people";
import type { MockDb, TeamRow } from "./data/seed";

/** Matches the API on any origin, so the same handlers serve the browser worker and Vitest. */
const p = (path: string) => `*/api/v1${path}`;

const problem = (status: number, title: string, detail?: string, errors?: T.ProblemDetails["errors"]): Response =>
  HttpResponse.json<T.ProblemDetails>({ title, status, detail, errors }, {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });

const latency = () => delay(process.env.NODE_ENV === "test" ? 0 : 120 + Math.random() * 220);

/* ---------------- identity ---------------- */

function meFor(db: MockDb, userId: string): T.Me | null {
  const u = db.users.find((x) => x.id === userId);
  if (!u) return null;
  return {
    id: u.id,
    org_id: db.org.id,
    org_name: db.org.name,
    display_name: u.display_name,
    email: u.email,
    role: u.role,
    lead_team_ids: db.teams.filter((t) => t.lead_user_id === u.id).map((t) => t.id),
    member_team_ids: Object.entries(db.members)
      .filter(([, ms]) => ms.some((m) => m.user_id === u.id))
      .map(([id]) => id),
    onboarded: db.org.onboarded,
  };
}

function currentUser(request: Request): T.Me | null {
  const id = request.headers.get("X-Mock-User");
  return id ? meFor(getDb(), id) : null;
}

type Ctx = { me: T.Me; db: MockDb; request: Request; params: PathParams };
type Handler = (ctx: Ctx) => Response | Promise<Response>;

/** Authenticated handler with optional role gate (mirrors backend RBAC). */
function authed(roles: T.Role[] | "any", fn: Handler) {
  return async ({ request, params }: { request: Request; params: PathParams }) => {
    await latency();
    const me = currentUser(request);
    if (!me) return problem(401, "Unauthorized", "Sign in to continue.");
    if (roles !== "any" && !roles.includes(me.role)) return problem(403, "Forbidden", "Your role can't do this.");
    return fn({ me, db: getDb(), request, params });
  };
}

function visibleTeamIds(me: T.Me, db: MockDb): string[] {
  if (me.role === "org_admin" || me.role === "viewer") return db.teams.map((t) => t.id);
  return [...new Set([...me.lead_team_ids, ...me.member_team_ids])];
}

function canConfigure(me: T.Me, teamId: string) {
  return me.role === "org_admin" || (me.role === "scrum_lead" && me.lead_team_ids.includes(teamId));
}

function audit(db: MockDb, me: T.Me | string, action: string, entity_type: string, entity_id: string, diff: Record<string, unknown>) {
  db.audit.unshift({
    id: `aud-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
    at: nowIso(),
    actor_name: typeof me === "string" ? me : me.display_name,
    action,
    entity_type,
    entity_id,
    diff,
  });
}

/* ---------------- projections ---------------- */

function toTeam(db: MockDb, row: TeamRow): T.Team {
  const sched = db.schedules[row.id];
  let next: string | null = null;
  if (sched && !sched.paused) {
    const run = nextRuns(sched.cron, sched.timezone, 1, { skipDates: sched.skip_dates })[0];
    next = run ? run.toISOString() : null;
  }
  return {
    ...row,
    lead_name: userById(row.lead_user_id).display_name,
    member_count: db.members[row.id]?.length ?? 0,
    next_run_at: next,
    active_template_version: db.templates.find((t) => t.team_id === row.id && t.is_active)?.version ?? null,
  };
}

function toMembers(db: MockDb, teamId: string): T.TeamMember[] {
  return (db.members[teamId] ?? [])
    .slice()
    .sort((a, b) => a.speaking_order - b.speaking_order)
    .map((m) => {
      const u = db.users.find((x) => x.id === m.user_id)!;
      return {
        user_id: u.id,
        display_name: u.display_name,
        email: u.email,
        department: u.department,
        speaking_order: m.speaking_order,
        pm_account_id: m.pm_account_id,
        aliases: u.aliases,
      };
    });
}

const summary = (s: T.Session): T.SessionSummary => ({
  id: s.id,
  team_id: s.team_id,
  team_name: s.team_name,
  run_date: s.run_date,
  status: s.status,
  attendance_pct: s.attendance_pct,
  blocker_count: s.blocker_count,
  duration_seconds: s.duration_seconds,
});

const strip = (b: T.BlockerDetail): T.Blocker => {
  const { events: _e, evidence: _v, ...rest } = b;
  return rest;
};

function findSession(db: MockDb, me: T.Me, id: string) {
  const s = db.sessions.find((x) => x.id === id);
  if (!s || !visibleTeamIds(me, db).includes(s.team_id)) return null;
  return s;
}

/* ---------------- metrics ---------------- */

const day = (iso: string) => iso.slice(0, 10);
const inRange = (d: string, from: string, to: string) => d >= from && d <= to;
const spanDays = (from: string, to: string) =>
  Math.round((new Date(to).getTime() - new Date(from).getTime()) / 86_400_000) + 1;

function metricsQuery(request: Request): T.MetricsQuery {
  const url = new URL(request.url);
  return {
    team: url.searchParams.get("team") ?? "",
    from: url.searchParams.get("from") ?? "",
    to: url.searchParams.get("to") ?? "",
  };
}

function previous(q: T.MetricsQuery): T.MetricsQuery {
  const n = spanDays(q.from, q.to);
  return { team: q.team, from: shiftDate(q.from, -n), to: shiftDate(q.from, -1) };
}

function participation(db: MockDb, q: T.MetricsQuery) {
  const sessions = db.sessions
    .filter((s) => s.team_id === q.team && inRange(s.run_date, q.from, q.to))
    .sort((a, b) => a.run_date.localeCompare(b.run_date));
  const series: T.ParticipationPoint[] = sessions.map((s) => {
    const att = db.attendance[s.id] ?? [];
    const present = att.filter((a) => a.status === "present").length;
    const asyncN = att.filter((a) => a.status === "async").length;
    return {
      date: s.run_date,
      present,
      async: asyncN,
      absent: att.length - present - asyncN,
      rate: att.length ? (present + asyncN) / att.length : 0,
    };
  });
  const tot = series.reduce((a, s) => a + s.present + s.async + s.absent, 0);
  const ok = series.reduce((a, s) => a + s.present + s.async, 0);
  return { rate: tot ? ok / tot : 0, series };
}

function blockerStats(db: MockDb, q: T.MetricsQuery) {
  const team = db.blockers.filter((b) => b.team_id === q.team);
  const raised = team.filter((b) => inRange(day(b.first_seen_at), q.from, q.to));
  const resolved = team.filter((b) => b.resolved_at && inRange(day(b.resolved_at), q.from, q.to));
  const durations = resolved.map(
    (b) => (new Date(b.resolved_at!).getTime() - new Date(b.first_seen_at).getTime()) / 86_400_000,
  );
  const avg = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
  return { team, raised, resolved, avg };
}

/* ---------------- handlers ---------------- */

export const handlers = [
  /* identity & org */
  http.get(p("/me"), authed("any", ({ me }) => HttpResponse.json(me))),

  http.post(
    p("/orgs/onboard"),
    authed(["org_admin"], async ({ me, db, request }) => {
      const body = (await request.json()) as { name: string };
      if (!body.name?.trim()) return problem(422, "Validation failed", undefined, [{ field: "name", message: "Organization name is required" }]);
      db.org.name = body.name.trim();
      db.org.onboarded = true;
      audit(db, me, "org.onboarded", "organization", db.org.id, { name: db.org.name });
      persist();
      return HttpResponse.json(meFor(db, me.id));
    }),
  ),

  http.get(
    p("/org/settings"),
    authed("any", ({ db }) => {
      const { id: _id, onboarded: _o, ...settings } = db.org;
      return HttpResponse.json<T.OrgSettings>(settings);
    }),
  ),

  http.patch(
    p("/org/settings"),
    authed(["org_admin"], async ({ me, db, request }) => {
      const body = (await request.json()) as Partial<T.OrgSettings>;
      if (body.retention_days_transcript !== undefined && body.retention_days_transcript < 1)
        return problem(422, "Validation failed", undefined, [{ field: "retention_days_transcript", message: "Must be at least 1 day" }]);
      const before = { ...db.org };
      Object.assign(db.org, body);
      audit(db, me, "org.settings_updated", "organization", db.org.id, Object.fromEntries(Object.keys(body).map((k) => [k, [before[k as keyof typeof before], body[k as keyof typeof body]]])));
      persist();
      const { id: _id, onboarded: _o, ...settings } = db.org;
      return HttpResponse.json(settings);
    }),
  ),

  /* users */
  http.get(
    p("/users"),
    authed("any", ({ db, request }) => {
      const search = (new URL(request.url).searchParams.get("search") ?? "").toLowerCase();
      const items = db.users
        .filter((u) => !search || u.display_name.toLowerCase().includes(search) || u.email.includes(search))
        .map(({ pm_account_id: _pm, ...u }) => u);
      return HttpResponse.json<T.Paginated<T.User>>({ items, next_cursor: null });
    }),
  ),

  http.post(
    p("/users/sync"),
    authed(["org_admin"], ({ me, db }) => {
      audit(db, me, "users.synced", "organization", db.org.id, { source: "entra_id", added: 0, updated: db.users.length });
      persist();
      return HttpResponse.json({ added: 0, updated: db.users.length });
    }),
  ),

  http.patch(
    p("/users/:id"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const u = db.users.find((x) => x.id === params.id);
      if (!u) return problem(404, "Not found");
      const body = (await request.json()) as Partial<Pick<T.User, "role" | "aliases">>;
      if (body.role && me.role !== "org_admin") return problem(403, "Forbidden", "Only org admins can change roles.");
      if (body.role && u.id === me.id) return problem(422, "Validation failed", "You can't change your own role.");
      const diff: Record<string, unknown> = {};
      if (body.role) {
        diff.role = [u.role, body.role];
        u.role = body.role;
      }
      if (body.aliases) {
        diff.aliases = [u.aliases, body.aliases];
        u.aliases = body.aliases;
      }
      audit(db, me, "user.updated", "user", u.id, diff);
      persist();
      const { pm_account_id: _pm, ...rest } = u;
      return HttpResponse.json(rest);
    }),
  ),

  http.post(
    p("/users/:id/erase"),
    authed(["org_admin"], ({ me, db, params }) => {
      const u = db.users.find((x) => x.id === params.id);
      if (!u) return problem(404, "Not found");
      for (const segs of Object.values(db.segments)) {
        for (const s of segs) if (s.speaker_user_id === u.id) s.text = "[redacted on erasure request]";
      }
      audit(db, me, "user.erased", "user", u.id, { transcripts: "redacted", updates: "deleted" });
      persist();
      return new HttpResponse(null, { status: 204 });
    }),
  ),

  /* teams */
  http.get(
    p("/teams"),
    authed("any", ({ me, db }) => {
      const ids = visibleTeamIds(me, db);
      return HttpResponse.json<T.Paginated<T.Team>>({
        items: db.teams.filter((t) => ids.includes(t.id)).map((t) => toTeam(db, t)),
        next_cursor: null,
      });
    }),
  ),

  http.post(
    p("/teams"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request }) => {
      const body = (await request.json()) as T.TeamCreate;
      if (!body.name?.trim()) return problem(422, "Validation failed", undefined, [{ field: "name", message: "Team name is required" }]);
      if (db.teams.some((t) => t.name.toLowerCase() === body.name.trim().toLowerCase()))
        return problem(422, "Validation failed", undefined, [{ field: "name", message: "A team with this name already exists" }]);
      const row: TeamRow = {
        id: `team-${body.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now().toString(36)}`,
        name: body.name.trim(),
        lead_user_id: body.lead_user_id || me.id,
        timezone: body.timezone || "Asia/Kolkata",
        meeting_provider: "recall_teams",
        active: true,
      };
      db.teams.push(row);
      db.members[row.id] = [];
      audit(db, me, "team.created", "team", row.id, { name: row.name, timezone: row.timezone });
      persist();
      return HttpResponse.json(toTeam(db, row), { status: 201 });
    }),
  ),

  http.get(
    p("/teams/:id"),
    authed("any", ({ me, db, params }) => {
      const row = db.teams.find((t) => t.id === params.id);
      if (!row || !visibleTeamIds(me, db).includes(row.id)) return problem(404, "Team not found");
      return HttpResponse.json(toTeam(db, row));
    }),
  ),

  http.patch(
    p("/teams/:id"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const row = db.teams.find((t) => t.id === params.id);
      if (!row) return problem(404, "Team not found");
      if (!canConfigure(me, row.id)) return problem(403, "Forbidden");
      const body = (await request.json()) as Partial<TeamRow>;
      Object.assign(row, body);
      audit(db, me, "team.updated", "team", row.id, body as Record<string, unknown>);
      persist();
      return HttpResponse.json(toTeam(db, row));
    }),
  ),

  http.get(p("/teams/:id/members"), authed("any", ({ db, params }) => HttpResponse.json(toMembers(db, String(params.id))))),

  http.put(
    p("/teams/:id/members"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const id = String(params.id);
      if (!canConfigure(me, id)) return problem(403, "Forbidden");
      const body = (await request.json()) as T.TeamMemberInput[];
      const before = (db.members[id] ?? []).map((m) => m.user_id);
      db.members[id] = body.map((m, i) => ({ user_id: m.user_id, speaking_order: i + 1, pm_account_id: m.pm_account_id }));
      audit(db, me, "team.members_updated", "team", id, { members: [before.length, body.length] });
      persist();
      return HttpResponse.json(toMembers(db, id));
    }),
  ),

  /* templates */
  http.get(
    p("/teams/:id/templates"),
    authed("any", ({ db, params }) =>
      HttpResponse.json(db.templates.filter((t) => t.team_id === params.id).sort((a, b) => b.version - a.version)),
    ),
  ),

  http.post(
    p("/teams/:id/templates"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const id = String(params.id);
      if (!canConfigure(me, id)) return problem(403, "Forbidden");
      const body = (await request.json()) as { questions: T.QuestionInput[] };
      if (!body.questions?.length) return problem(422, "Validation failed", "Add at least one question.");
      const version = Math.max(0, ...db.templates.filter((t) => t.team_id === id).map((t) => t.version)) + 1;
      db.templates.forEach((t) => t.team_id === id && (t.is_active = false));
      const tpl: T.QuestionTemplate = {
        id: `tpl-${id}-v${version}`,
        team_id: id,
        version,
        is_active: true,
        created_by_name: me.display_name,
        created_at: nowIso(),
        questions: body.questions.map((q, i) => ({ ...q, id: `q-${id}-v${version}-${i + 1}`, position: i + 1 })),
      };
      db.templates.push(tpl);
      audit(db, me, "template.created", "question_template", tpl.id, { version, questions: tpl.questions.length });
      persist();
      return HttpResponse.json(tpl, { status: 201 });
    }),
  ),

  http.post(
    p("/templates/:id/activate"),
    authed(["org_admin", "scrum_lead"], ({ me, db, params }) => {
      const tpl = db.templates.find((t) => t.id === params.id);
      if (!tpl) return problem(404, "Template not found");
      if (!canConfigure(me, tpl.team_id)) return problem(403, "Forbidden");
      db.templates.forEach((t) => t.team_id === tpl.team_id && (t.is_active = t.id === tpl.id));
      audit(db, me, "template.activated", "question_template", tpl.id, { version: tpl.version });
      persist();
      return HttpResponse.json(tpl);
    }),
  ),

  /* schedule */
  http.get(
    p("/teams/:id/schedule"),
    authed("any", ({ db, params }) => {
      const s = db.schedules[String(params.id)];
      if (!s) return problem(404, "No schedule yet");
      return HttpResponse.json<T.Schedule>({ team_id: String(params.id), ...s });
    }),
  ),

  http.put(
    p("/teams/:id/schedule"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const id = String(params.id);
      if (!canConfigure(me, id)) return problem(403, "Forbidden");
      const body = (await request.json()) as T.ScheduleInput;
      try {
        fromCron(body.cron);
      } catch {
        return problem(422, "Validation failed", undefined, [{ field: "cron", message: "Unsupported schedule" }]);
      }
      if (body.async_window_minutes < 0 || body.async_window_minutes > 480)
        return problem(422, "Validation failed", undefined, [{ field: "async_window_minutes", message: "Must be between 0 and 480 minutes" }]);
      const before = db.schedules[id];
      db.schedules[id] = {
        ...body,
        join_url: before?.join_url ?? `https://teams.microsoft.com/l/meetup-join/${id}`,
      };
      audit(db, me, before ? "schedule.updated" : "schedule.created", "schedule", id, {
        cron: [before?.cron ?? null, body.cron],
        timezone: [before?.timezone ?? null, body.timezone],
        ...(before ? {} : { recurring_meeting: "created" }),
      });
      persist();
      return HttpResponse.json<T.Schedule>({ team_id: id, ...db.schedules[id]! });
    }),
  ),

  http.post(
    p("/teams/:id/schedule/trigger-now"),
    authed(["org_admin", "scrum_lead"], ({ me, db, params }) => {
      const id = String(params.id);
      if (!canConfigure(me, id)) return problem(403, "Forbidden");
      const workflow_id = `standup-${id}-${nowIso().slice(0, 10)}-manual`;
      audit(db, me, "schedule.triggered", "schedule", id, { workflow_id });
      persist();
      return HttpResponse.json({ workflow_id }, { status: 202 });
    }),
  ),

  http.post(
    p("/teams/:id/schedule/pause"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const id = String(params.id);
      if (!canConfigure(me, id)) return problem(403, "Forbidden");
      const { paused } = (await request.json()) as { paused: boolean };
      const s = db.schedules[id];
      if (!s) return problem(404, "No schedule yet");
      s.paused = paused;
      audit(db, me, paused ? "schedule.paused" : "schedule.resumed", "schedule", id, {});
      persist();
      return HttpResponse.json<T.Schedule>({ team_id: id, ...s });
    }),
  ),

  /* integrations */
  http.get(p("/integrations"), authed("any", ({ db }) => HttpResponse.json(db.integrations))),

  http.post(
    p("/integrations/:kind/connect"),
    authed(["org_admin"], ({ me, db, params }) => {
      const kind = params.kind as T.IntegrationKind;
      const integ = db.integrations.find((i) => i.kind === kind);
      if (!integ) return problem(404, "Unknown integration");
      // Mock: the OAuth round-trip succeeds instantly.
      integ.status = "connected";
      integ.last_checked_at = nowIso();
      if (integ.detail === "Not connected") integ.detail = "Connected via OAuth";
      if (kind === "mail") integ.detail = "standup-bot@acme.example · token valid for 90 days";
      audit(db, me, "integration.connected", "integration", integ.id, { kind });
      persist();
      return HttpResponse.json({ authorize_url: "#mock-oauth", integration: integ });
    }),
  ),

  http.post(
    p("/integrations/:id/test"),
    authed(["org_admin"], ({ db, params }) => {
      const integ = db.integrations.find((i) => i.id === params.id);
      if (!integ) return problem(404, "Unknown integration");
      integ.last_checked_at = nowIso();
      persist();
      return HttpResponse.json(integ);
    }),
  ),

  http.delete(
    p("/integrations/:id"),
    authed(["org_admin"], ({ me, db, params }) => {
      const integ = db.integrations.find((i) => i.id === params.id);
      if (!integ) return problem(404, "Unknown integration");
      integ.status = "disconnected";
      integ.detail = "Not connected";
      integ.last_checked_at = null;
      audit(db, me, "integration.disconnected", "integration", integ.id, { kind: integ.kind });
      persist();
      return new HttpResponse(null, { status: 204 });
    }),
  ),

  /* sessions */
  http.get(
    p("/teams/:id/sessions"),
    authed("any", ({ me, db, params }) => {
      if (!visibleTeamIds(me, db).includes(String(params.id))) return problem(404, "Team not found");
      const items = db.sessions
        .filter((s) => s.team_id === params.id)
        .sort((a, b) => b.run_date.localeCompare(a.run_date))
        .map(summary);
      return HttpResponse.json<T.Paginated<T.SessionSummary>>({ items, next_cursor: null });
    }),
  ),

  http.get(
    p("/sessions/:id"),
    authed("any", ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      return s ? HttpResponse.json(s) : problem(404, "Session not found");
    }),
  ),

  http.get(
    p("/sessions/:id/attendance"),
    authed("any", ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      return s ? HttpResponse.json(db.attendance[s.id] ?? []) : problem(404, "Session not found");
    }),
  ),

  http.get(
    p("/sessions/:id/transcript"),
    authed(["org_admin", "scrum_lead", "member"], ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      if (!s) return problem(404, "Session not found");
      if (me.role === "scrum_lead" && !me.lead_team_ids.includes(s.team_id)) return problem(403, "Forbidden");
      let segs = db.segments[s.id] ?? [];
      // Members see only their own segments (plan §6.1).
      if (me.role === "member") segs = segs.filter((x) => x.speaker_user_id === me.id);
      return HttpResponse.json(segs);
    }),
  ),

  http.get(
    p("/sessions/:id/updates"),
    authed("any", ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      return s ? HttpResponse.json(db.updates[s.id] ?? []) : problem(404, "Session not found");
    }),
  ),

  http.get(
    p("/sessions/:id/report"),
    authed("any", ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      if (!s) return problem(404, "Session not found");
      const team = db.teams.find((t) => t.id === s.team_id)!;
      return HttpResponse.json<T.Report>({
        session_id: s.id,
        html: db.reports[s.id] ?? "",
        pdf_url: null,
        recipients: [userById(team.lead_user_id).email, "vikram.rao@acme.example"],
        sent_at: s.ended_at ? new Date(new Date(s.ended_at).getTime() + 8 * 60_000).toISOString() : null,
      });
    }),
  ),

  http.post(
    p("/sessions/:id/resend-digest"),
    authed(["org_admin", "scrum_lead"], ({ me, db, params }) => {
      const s = findSession(db, me, String(params.id));
      if (!s) return problem(404, "Session not found");
      audit(db, me, "mail.resent", "notification", s.id, { type: "digest", recipients: 2 });
      persist();
      return HttpResponse.json({ queued: 2 }, { status: 202 });
    }),
  ),

  /* blockers */
  http.get(
    p("/blockers"),
    authed("any", ({ me, db, request }) => {
      const url = new URL(request.url);
      const team = url.searchParams.get("team");
      const status = url.searchParams.get("status");
      const ids = visibleTeamIds(me, db);
      const items = db.blockers
        .filter((b) => ids.includes(b.team_id) && (!team || b.team_id === team) && (!status || b.status === status))
        .sort((a, b) => b.first_seen_at.localeCompare(a.first_seen_at))
        .map(strip);
      return HttpResponse.json<T.Paginated<T.Blocker>>({ items, next_cursor: null });
    }),
  ),

  http.get(
    p("/blockers/:id"),
    authed("any", ({ me, db, params }) => {
      const b = db.blockers.find((x) => x.id === params.id);
      if (!b || !visibleTeamIds(me, db).includes(b.team_id)) return problem(404, "Blocker not found");
      return HttpResponse.json(b);
    }),
  ),

  http.patch(
    p("/blockers/:id"),
    authed(["org_admin", "scrum_lead", "member"], async ({ me, db, request, params }) => {
      const b = db.blockers.find((x) => x.id === params.id);
      if (!b || !visibleTeamIds(me, db).includes(b.team_id)) return problem(404, "Blocker not found");
      const body = (await request.json()) as T.BlockerPatch;
      if (body.status && body.status !== b.status) {
        const from = b.status;
        b.status = body.status;
        b.resolved_at = body.status === "resolved" ? nowIso() : null;
        if (body.status !== "resolved" && from === "resolved") b.events.push({ at: nowIso(), kind: "reopened", actor_name: me.display_name, note: null, session_id: null });
        if (body.status === "acknowledged" || body.status === "resolved")
          b.events.push({ at: nowIso(), kind: body.status, actor_name: me.display_name, note: "Updated from blockers board", session_id: null });
        audit(db, me, `blocker.${body.status}`, "blocker", b.id, { status: [from, body.status] });
      }
      persist();
      return HttpResponse.json(strip(b));
    }),
  ),

  /* public signed actions (no auth header) */
  http.get(p("/actions/:token"), async ({ params }) => {
    await latency();
    const db = getDb();
    const tok = db.actionTokens[String(params.token)];
    if (!tok) return problem(404, "Link not recognised", "This link is invalid. Check that you copied the full URL.");
    if (tok.kind === "blocker") {
      const b = db.blockers.find((x) => x.id === tok.blocker_id)!;
      const done = b.status === "resolved";
      return HttpResponse.json<T.ActionPreview>({
        kind: "blocker",
        expired: tok.expired,
        already_done: done,
        allowed_actions: done ? [] : b.status === "acknowledged" ? ["resolve"] : ["acknowledge", "resolve"],
        blocker: {
          description: b.description,
          ticket_keys: b.ticket_keys,
          reporter_name: b.reporter_name,
          team_name: b.team_name,
          status: b.status,
          days_open: b.days_open,
        },
      });
    }
    const s = db.sessions.find((x) => x.id === tok.session_id)!;
    const tpl = db.templates.find((t) => t.team_id === s.team_id && t.is_active)!;
    return HttpResponse.json<T.ActionPreview>({
      kind: "checkin",
      expired: tok.expired,
      already_done: tok.used,
      allowed_actions: [],
      checkin: {
        member_name: userById(tok.user_id).display_name,
        team_name: s.team_name,
        run_date: s.run_date,
        questions: tpl.questions.map((q) => ({ id: q.id, text: q.text, required: q.required })),
      },
    });
  }),

  http.post(p("/actions/:token"), async ({ request, params }) => {
    await latency();
    const db = getDb();
    const tok = db.actionTokens[String(params.token)];
    if (!tok || tok.kind !== "blocker") return problem(404, "Link not recognised");
    if (tok.expired) return problem(410, "Link expired", "This link has expired. Open the blocker in Scrum Bot instead.");
    const { action } = (await request.json()) as { action: T.BlockerAction };
    const b = db.blockers.find((x) => x.id === tok.blocker_id)!;
    const actor = userById(tok.recipient_id).display_name;
    if (b.status === "resolved") return HttpResponse.json<T.ActionResult>({ status: "resolved" });
    const next: T.BlockerStatus = action === "resolve" ? "resolved" : "acknowledged";
    const from = b.status;
    b.status = next;
    if (next === "resolved") b.resolved_at = nowIso();
    b.events.push({ at: nowIso(), kind: next, actor_name: actor, note: "From email link", session_id: null });
    tok.used.push(action);
    audit(db, actor, `blocker.${next}`, "blocker", b.id, { status: [from, next], via: "email_link" });
    persist();
    return HttpResponse.json<T.ActionResult>({ status: next });
  }),

  http.post(p("/async-checkins/:token"), async ({ request, params }) => {
    await latency();
    const db = getDb();
    const tok = db.actionTokens[String(params.token)];
    if (!tok || tok.kind !== "checkin") return problem(404, "Link not recognised");
    if (tok.expired) return problem(410, "Check-in closed", "The async window for this standup has closed.");
    if (tok.used) return problem(409, "Already submitted", "You've already sent today's update.");
    const { answers } = (await request.json()) as { answers: Record<string, string> };
    const s = db.sessions.find((x) => x.id === tok.session_id)!;
    const tpl = db.templates.find((t) => t.team_id === s.team_id && t.is_active)!;
    const missing = tpl.questions.filter((q) => q.required && !answers[q.id]?.trim());
    if (missing.length)
      return problem(422, "Validation failed", undefined, missing.map((q) => ({ field: q.id, message: "This answer is required" })));
    tok.used = true;
    const name = userById(tok.user_id).display_name;
    const ans = tpl.questions.map((q) => answers[q.id]?.trim() ?? "");
    const updates = (db.updates[s.id] ??= []);
    const existing = updates.findIndex((u) => u.member_id === tok.user_id);
    const update: T.MemberUpdate = {
      member_id: tok.user_id,
      display_name: name,
      attendance: "async",
      source: "async",
      completed: ans[0] ? [{ summary: ans[0], ticket_keys: ans[0].match(/[A-Z]+-\d+/g) ?? [], status: "done", evidence_segment_ids: [] }] : [],
      planned: ans[1] ? [{ summary: ans[1], ticket_keys: ans[1].match(/[A-Z]+-\d+/g) ?? [], status: "planned", evidence_segment_ids: [] }] : [],
      blockers: [],
      dependencies: [],
      challenges: ans[2] && !/^no(ne)?\b/i.test(ans[2]) ? [ans[2]] : [],
    };
    if (existing >= 0) updates[existing] = update;
    else updates.push(update);
    const att = db.attendance[s.id]?.find((a) => a.user_id === tok.user_id);
    if (att) att.status = "async";
    audit(db, name, "checkin.submitted", "standup_session", s.id, { source: "web_fallback" });
    persist();
    return HttpResponse.json<T.ActionResult>({ status: "submitted" });
  }),

  /* review queue */
  http.get(
    p("/review-items"),
    authed(["org_admin", "scrum_lead"], ({ db, request }) => {
      const url = new URL(request.url);
      const kind = url.searchParams.get("kind");
      const status = url.searchParams.get("status") ?? "pending";
      const items = db.reviewItems.filter((r) => (!kind || r.kind === kind) && (status === "all" || r.status === status));
      return HttpResponse.json<T.Paginated<T.ReviewItem>>({ items, next_cursor: null });
    }),
  ),

  http.post(
    p("/review-items/:id/approve"),
    authed(["org_admin", "scrum_lead"], async ({ me, db, request, params }) => {
      const r = db.reviewItems.find((x) => x.id === params.id);
      if (!r) return problem(404, "Review item not found");
      if (r.status !== "pending") return problem(409, "Already decided");
      const { candidate_id } = (await request.json()) as { candidate_id: string };
      const cand = r.candidates.find((c) => c.id === candidate_id);
      if (!cand) return problem(422, "Validation failed", "Pick one of the candidates.");
      r.status = "approved";
      if (r.kind === "pm_writeback") db.pmStatus["PROJ-142"] = "Done";
      audit(db, me, "review.approved", "review_item", r.id, { kind: r.kind, choice: cand.label });
      persist();
      return HttpResponse.json(r);
    }),
  ),

  http.post(
    p("/review-items/:id/reject"),
    authed(["org_admin", "scrum_lead"], ({ me, db, params }) => {
      const r = db.reviewItems.find((x) => x.id === params.id);
      if (!r) return problem(404, "Review item not found");
      if (r.status !== "pending") return problem(409, "Already decided");
      r.status = "rejected";
      audit(db, me, "review.rejected", "review_item", r.id, { kind: r.kind });
      persist();
      return HttpResponse.json(r);
    }),
  ),

  /* metrics */
  http.get(
    p("/metrics/participation"),
    authed("any", ({ db, request }) => {
      const q = metricsQuery(request);
      const cur = participation(db, q);
      const prev = participation(db, previous(q));
      return HttpResponse.json<T.ParticipationMetrics>({
        rate: cur.rate,
        delta: prev.series.length ? (cur.rate - prev.rate) * 100 : 0,
        series: cur.series,
      });
    }),
  ),

  http.get(
    p("/metrics/blockers"),
    authed("any", ({ db, request }) => {
      const q = metricsQuery(request);
      const cur = blockerStats(db, q);
      const prev = blockerStats(db, previous(q));
      const open = cur.team.filter((b) => b.status !== "resolved");
      const buckets = [
        { bucket: "< 1 day", min: 0, max: 0 },
        { bucket: "1–2 days", min: 1, max: 2 },
        { bucket: "3–5 days", min: 3, max: 5 },
        { bucket: "> 5 days", min: 6, max: Infinity },
      ];
      const weekly = [3, 2, 1, 0].map((w) => {
        const to = shiftDate(q.to, -7 * w);
        const from = shiftDate(to, -6);
        const s = blockerStats(db, { team: q.team, from, to });
        return { week: from.slice(5), raised: s.raised.length, resolved: s.resolved.length };
      });
      return HttpResponse.json<T.BlockerMetrics>({
        raised: cur.raised.length,
        resolved: cur.resolved.length,
        open: open.length,
        avg_resolve_days: cur.avg,
        avg_resolve_delta: prev.resolved.length ? cur.avg - prev.avg : 0,
        age_buckets: buckets.map((b) => ({
          bucket: b.bucket,
          count: open.filter((x) => x.days_open >= b.min && x.days_open <= b.max).length,
        })),
        weekly,
      });
    }),
  ),

  http.get(
    p("/metrics/carry-over"),
    authed("any", ({ db, request }) => {
      const q = metricsQuery(request);
      const series = db.sessions
        .filter((s) => s.team_id === q.team && inRange(s.run_date, q.from, q.to))
        .sort((a, b) => a.run_date.localeCompare(b.run_date))
        .map((s, i) => ({ date: s.run_date, rate: [0.2, 0.16, 0.12, 0.1, 0.08][i % 5]! }));
      const rate = series.length ? series.reduce((a, s) => a + s.rate, 0) / series.length : 0;
      return HttpResponse.json<T.CarryOverMetrics>({ rate, delta: -3, series });
    }),
  ),

  http.get(
    p("/metrics/mismatches"),
    authed("any", ({ me, db, request }) => {
      const q = metricsQuery(request);
      const thu = shiftDate(db.storyFriday, -1);
      let rows: T.Mismatch[] =
        q.team === "team-payments" && inRange(thu, q.from, q.to) && db.pmStatus["PROJ-155"] !== "Done"
          ? [{ member_name: "Sneha Joshi", ticket_key: "PROJ-155", said: "Done — settlement report export", pm_status: db.pmStatus["PROJ-155"]!, session_id: `ses-payments-${thu}`, date: thu }]
          : [];
      if (me.role === "viewer") rows = rows.map((r) => ({ ...r, member_name: "—" }));
      if (me.role === "member") rows = rows.filter((r) => r.member_name === me.display_name);
      return HttpResponse.json(rows);
    }),
  ),

  http.get(
    p("/metrics/dependencies"),
    authed("any", ({ db, request }) => {
      const q = metricsQuery(request);
      const team = db.teams.find((t) => t.id === q.team);
      const nodes = new Map<string, T.DependencyGraph["nodes"][number]>();
      const edges = new Map<string, number>();
      if (team) nodes.set(`team:${team.id}`, { id: `team:${team.id}`, label: team.name, kind: "team", is_self: true });
      const sessions = db.sessions.filter((s) => s.team_id === q.team && inRange(s.run_date, q.from, q.to));
      for (const s of sessions) {
        for (const u of db.updates[s.id] ?? []) {
          const targets = [
            ...u.blockers.map((b) => ({ user: b.blocked_on_member_id, raw: b.blocked_on_raw })),
            ...u.dependencies.map((d) => ({ user: d.on_member_id, raw: d.on_raw })),
          ];
          for (const t of targets) {
            const dept = t.user ? db.users.find((x) => x.id === t.user)?.department : null;
            const label = dept && dept !== team?.name ? dept : t.raw ?? "External";
            const id = `ext:${label}`;
            if (!nodes.has(id)) nodes.set(id, { id, label, kind: "team", is_self: false });
            const src = `team:${q.team}`;
            const key = `${src}|${id}`;
            edges.set(key, (edges.get(key) ?? 0) + 1);
          }
        }
      }
      return HttpResponse.json<T.DependencyGraph>({
        nodes: [...nodes.values()],
        edges: [...edges.entries()].map(([k, weight]) => {
          const [source, target] = k.split("|") as [string, string];
          return { source, target, weight };
        }),
      });
    }),
  ),

  http.get(
    p("/metrics/themes"),
    authed("any", ({ request }) => {
      const q = metricsQuery(request);
      const themes: T.BlockerTheme[] =
        q.team === "team-payments"
          ? [
              { label: "Code review latency", count: 5, trend: "up" },
              { label: "Environment instability", count: 2, trend: "flat" },
              { label: "Credentials & access", count: 1, trend: "down" },
              { label: "API contract changes", count: 1, trend: "flat" },
            ]
          : [
              { label: "Database maintenance windows", count: 2, trend: "up" },
              { label: "Environment instability", count: 1, trend: "flat" },
            ];
      return HttpResponse.json(themes);
    }),
  ),

  http.get(
    p("/metrics/burndown"),
    authed("any", ({ db }) => {
      const start = shiftDate(db.storyFriday, -11);
      const total = 48;
      const remaining = [48, 46, 43, 41, 38, 33, 30, 26, 22, 19];
      const points = remaining.map((r, i) => ({
        date: shiftDate(start, i + (i >= 5 ? 2 : 0)),
        ideal: Math.round(total - (total / 9) * i),
        remaining: r,
      }));
      return HttpResponse.json<T.Burndown>({ sprint_name: "Sprint 24", points });
    }),
  ),

  /* audit */
  http.get(
    p("/audit-log"),
    authed(["org_admin"], ({ db, request }) => {
      const url = new URL(request.url);
      const entity = url.searchParams.get("entity");
      const actor = (url.searchParams.get("actor") ?? "").toLowerCase();
      const items = db.audit.filter(
        (a) => (!entity || a.entity_type === entity) && (!actor || a.actor_name.toLowerCase().includes(actor)),
      );
      return HttpResponse.json<T.Paginated<T.AuditEntry>>({ items, next_cursor: null });
    }),
  ),
];
