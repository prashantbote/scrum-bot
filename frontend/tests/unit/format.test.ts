import { describe, expect, it } from "vitest";
import { duration, initials, offset, pct, plural, relativeDays, signed } from "@/lib/format";

describe("formatters", () => {
  it("formats percentages and signed deltas", () => {
    expect(pct(0.96)).toBe("96%");
    expect(signed(2)).toBe("+2");
    expect(signed(-0.4, 1)).toBe("−0.4");
    expect(signed(0.01, 1)).toBe("0");
  });

  it("formats durations and transcript offsets", () => {
    expect(duration(754)).toBe("12m 34s");
    expect(duration(3725)).toBe("1h 2m");
    expect(duration(42)).toBe("42s");
    expect(duration(null)).toBe("—");
    expect(offset(65_400)).toBe("01:05");
  });

  it("formats names and counts", () => {
    expect(initials("Neha Kapoor")).toBe("NK");
    expect(initials("Scrum Bot Helper")).toBe("SB");
    expect(plural(1, "day")).toBe("1 day");
    expect(plural(3, "day")).toBe("3 days");
  });

  it("describes relative days", () => {
    const now = new Date("2026-11-13T12:00:00+05:30");
    expect(relativeDays("2026-11-13T09:00:00+05:30", now)).toBe("today");
    expect(relativeDays("2026-11-12T09:00:00+05:30", now)).toBe("yesterday");
    expect(relativeDays("2026-11-09T09:00:00+05:30", now)).toBe("4 days ago");
  });
});
