/**
 * The "A day with Scrum Bot" narrative, checked through the real API client against the MSW mock
 * backend. These are the numbers Neha sees on Friday (docs/README.md §1).
 */
import { describe, expect, it } from "vitest";
import { api } from "@/lib/api/endpoints";
import { ApiError, setExtraHeaders } from "@/lib/api/client";
import { shiftDate, storyFriday } from "@mocks/data/clock";

const as = (userId: string) => setExtraHeaders(() => ({ "X-Mock-User": userId }));
const fri = storyFriday();
const week = { team: "team-payments", from: shiftDate(fri, -6), to: fri };

describe("Neha's week (Payments)", () => {
  it("shows 96% attendance with Karan counted as async on Tuesday", async () => {
    as("u-neha");
    const p = await api.participation(week);
    expect(p.series).toHaveLength(5);
    expect(Math.round(p.rate * 100)).toBe(96);
    const tue = p.series.find((s) => s.date === shiftDate(fri, -3))!;
    expect(tue).toMatchObject({ present: 4, async: 1, absent: 0 });
  });

  it("shows 4 blockers raised, 3 resolved, 1.2 days average to resolve", async () => {
    as("u-neha");
    const b = await api.blockerMetrics(week);
    expect(b.raised).toBe(4);
    expect(b.resolved).toBe(3);
    expect(b.avg_resolve_days).toBeCloseTo(1.2, 1);
    expect(b.avg_resolve_delta).toBeLessThan(0); // faster than the week before
  });

  it("flags Sneha's PROJ-155 as said-done but still In Progress in Jira", async () => {
    as("u-neha");
    const m = await api.mismatches(week);
    expect(m).toEqual([expect.objectContaining({ member_name: "Sneha Joshi", ticket_key: "PROJ-155", pm_status: "In Progress" })]);
  });

  it("shows Payments waits on Backend most often", async () => {
    as("u-neha");
    const g = await api.dependencies(week);
    const top = [...g.edges].sort((a, b) => b.weight - a.weight)[0]!;
    expect(g.nodes.find((n) => n.id === top.target)?.label).toBe("Backend");
  });

  it("grounds Rahul's Tuesday blocker in the transcript and resolves 'Amit' to Amit Sharma", async () => {
    as("u-neha");
    const sid = `ses-payments-${shiftDate(fri, -3)}`;
    const updates = await api.updates(sid);
    const rahul = updates.find((u) => u.member_id === "u-rahul")!;
    const blocker = rahul.blockers[0]!;
    expect(blocker).toMatchObject({ blocked_on_member_id: "u-amit", ticket_keys: ["PROJ-142"] });
    expect(blocker.confidence).toBeGreaterThanOrEqual(0.85);

    const transcript = await api.transcript(sid);
    const evidence = transcript.filter((s) => blocker.evidence_segment_ids.includes(s.id));
    expect(evidence.length).toBeGreaterThan(0);
    expect(evidence.some((s) => s.text.includes("sandbox credentials from Amit"))).toBe(true);
    expect(evidence.every((s) => s.speaker_user_id === "u-rahul")).toBe(true);
  });

  it("matched Priya's repeat blocker and escalated it instead of re-alerting", async () => {
    as("u-neha");
    const b = await api.blocker("blk-priya-review");
    expect(b.escalated).toBe(true);
    expect(b.events.filter((e) => e.kind === "alert_sent")).toHaveLength(1);
    expect(b.events.filter((e) => e.kind === "mentioned").length).toBeGreaterThanOrEqual(3);
  });
});

describe("signed email links", () => {
  it("lets the blocking person acknowledge then resolve without signing in", async () => {
    setExtraHeaders(() => ({}));
    const preview = await api.actionPreview("demo-priya-review");
    expect(preview.allowed_actions).toEqual(["acknowledge", "resolve"]);
    expect(await api.performAction("demo-priya-review", "acknowledge")).toEqual({ status: "acknowledged" });
    expect((await api.actionPreview("demo-priya-review")).allowed_actions).toEqual(["resolve"]);
    expect(await api.performAction("demo-priya-review", "resolve")).toEqual({ status: "resolved" });

    as("u-neha");
    const b = await api.blocker("blk-priya-review");
    expect(b.status).toBe("resolved");
    expect(b.events.at(-1)).toMatchObject({ kind: "resolved", actor_name: "Arjun Patel" });
  });

  it("reports expired links with 410", async () => {
    await expect(api.performAction("demo-expired", "resolve")).rejects.toMatchObject({ status: 410 });
  });

  it("validates async check-in answers", async () => {
    const err = await api.submitCheckin("demo-checkin-karan", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(Object.keys((err as ApiError).fieldErrors())).toHaveLength(3);
  });
});

describe("role enforcement in the API", () => {
  it("hides individual names from viewers and transcripts from them entirely", async () => {
    as("u-vikram");
    const m = await api.mismatches(week);
    expect(m[0]?.member_name).toBe("—");
    await expect(api.transcript(`ses-payments-${fri}`)).rejects.toMatchObject({ status: 403 });
    await expect(api.reviewItems()).rejects.toMatchObject({ status: 403 });
  });

  it("shows members only their own transcript segments", async () => {
    as("u-rahul");
    const segs = await api.transcript(`ses-payments-${shiftDate(fri, -3)}`);
    expect(segs.length).toBeGreaterThan(0);
    expect(segs.every((s) => s.speaker_user_id === "u-rahul")).toBe(true);
  });

  it("rejects unauthenticated requests", async () => {
    setExtraHeaders(() => ({}));
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
  });

  it("writes an audit entry for configuration changes", async () => {
    as("u-neha");
    await api.saveSchedule("team-payments", {
      cron: "0 11 * * 1-5",
      timezone: "Asia/Kolkata",
      holiday_calendar: "IN",
      skip_dates: [],
      async_window_minutes: 60,
      lead_minutes: 5,
      paused: false,
    });
    as("u-deepa");
    const log = await api.auditLog({ entity: "schedule" });
    expect(log.items[0]).toMatchObject({ actor_name: "Neha Kapoor", action: "schedule.updated" });
  });
});
