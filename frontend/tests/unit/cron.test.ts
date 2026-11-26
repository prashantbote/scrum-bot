import { describe as suite, expect, it } from "vitest";
import { describe, fromCron, nextRuns, toCron } from "@/lib/schedule/cron";

suite("cron helpers", () => {
  it("builds compact cron strings", () => {
    expect(toCron({ time: "10:30", days: [1, 2, 3, 4, 5] })).toBe("30 10 * * 1-5");
    expect(toCron({ time: "09:05", days: [1, 3, 5] })).toBe("5 9 * * 1,3,5");
    expect(toCron({ time: "09:00", days: [1, 2] })).toBe("0 9 * * 1,2");
    expect(toCron({ time: "09:00", days: [0, 1, 2, 3, 6] })).toBe("0 9 * * 0-3,6");
  });

  it("round-trips through fromCron", () => {
    for (const s of [
      { time: "10:30", days: [1, 2, 3, 4, 5] },
      { time: "08:15", days: [0, 6] },
      { time: "23:45", days: [2, 4] },
    ]) {
      expect(fromCron(toCron(s))).toEqual(s);
    }
  });

  it("rejects crons the editor can't represent", () => {
    expect(() => fromCron("*/5 * * * *")).toThrow();
    expect(() => fromCron("0 9 1 * *")).toThrow();
    expect(() => toCron({ time: "10:00", days: [] })).toThrow();
  });

  it("describes schedules in words", () => {
    expect(describe({ time: "10:30", days: [1, 2, 3, 4, 5] })).toBe("Mon–Fri at 10:30");
    expect(describe({ time: "09:00", days: [1, 3] })).toBe("Mon, Wed at 09:00");
  });

  it("computes next runs in the team's time zone, skipping weekends and skip dates", () => {
    // Friday 2026-11-13 12:00 IST — today's 10:30 run has already happened.
    const from = new Date("2026-11-13T06:30:00Z");
    const runs = nextRuns("30 10 * * 1-5", "Asia/Kolkata", 3, { from, skipDates: ["2026-11-17"] });
    expect(runs.map((d) => d.toISOString())).toEqual([
      "2026-11-16T05:00:00.000Z", // Mon 10:30 IST
      "2026-11-18T05:00:00.000Z", // Wed (Tue skipped)
      "2026-11-19T05:00:00.000Z",
    ]);
  });

  it("handles zones with DST", () => {
    const from = new Date("2026-03-06T00:00:00Z");
    const runs = nextRuns("0 9 * * 1-5", "America/New_York", 6, { from });
    // DST starts Sun 2026-03-08: 9:00 EST = 14:00Z before, 9:00 EDT = 13:00Z after.
    expect(runs[0]!.toISOString()).toBe("2026-03-06T14:00:00.000Z");
    expect(runs[1]!.toISOString()).toBe("2026-03-09T13:00:00.000Z");
  });
});
