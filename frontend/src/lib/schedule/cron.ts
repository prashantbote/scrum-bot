import { addDays } from "date-fns";
import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

/**
 * The schedule editor only produces "minute hour * * days" crons (one time, chosen weekdays).
 * Anything more exotic is rejected so the UI never shows a schedule it can't round-trip.
 */
export const WEEKDAYS = [
  { value: 1, short: "Mon" },
  { value: 2, short: "Tue" },
  { value: 3, short: "Wed" },
  { value: 4, short: "Thu" },
  { value: 5, short: "Fri" },
  { value: 6, short: "Sat" },
  { value: 0, short: "Sun" },
] as const;

export interface SimpleSchedule {
  time: string; // "HH:mm"
  days: number[]; // 0=Sun … 6=Sat
}

export function toCron({ time, days }: SimpleSchedule): string {
  const [h, m] = time.split(":").map(Number);
  if (h === undefined || m === undefined || Number.isNaN(h) || Number.isNaN(m)) throw new Error("Invalid time");
  if (days.length === 0) throw new Error("Pick at least one day");
  return `${m} ${h} * * ${compressDays(days)}`;
}

function compressDays(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  const parts: string[] = [];
  let start = sorted[0]!;
  let prev = start;
  for (let i = 1; i <= sorted.length; i++) {
    const cur = sorted[i];
    if (cur !== undefined && cur === prev + 1) {
      prev = cur;
      continue;
    }
    parts.push(start === prev ? `${start}` : prev === start + 1 ? `${start},${prev}` : `${start}-${prev}`);
    if (cur !== undefined) {
      start = cur;
      prev = cur;
    }
  }
  return parts.join(",");
}

export function fromCron(cron: string): SimpleSchedule {
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) throw new Error(`Unsupported cron: ${cron}`);
  const [min, hour, dom, mon, dow] = fields as [string, string, string, string, string];
  if (dom !== "*" || mon !== "*" || !/^\d+$/.test(min) || !/^\d+$/.test(hour)) {
    throw new Error(`Unsupported cron: ${cron}`);
  }
  const days = new Set<number>();
  for (const part of dow.split(",")) {
    if (part === "*") [0, 1, 2, 3, 4, 5, 6].forEach((d) => days.add(d));
    else if (part.includes("-")) {
      const [a, b] = part.split("-").map(Number);
      if (a === undefined || b === undefined) throw new Error(`Unsupported cron: ${cron}`);
      for (let d = a; d <= b; d++) days.add(d % 7);
    } else days.add(Number(part) % 7);
  }
  return {
    time: `${hour.padStart(2, "0")}:${min.padStart(2, "0")}`,
    days: [...days].sort((a, b) => a - b),
  };
}

export function describe(s: SimpleSchedule): string {
  const sorted = [...s.days].sort((a, b) => a - b);
  const label =
    sorted.join(",") === "1,2,3,4,5"
      ? "Mon–Fri"
      : sorted.length === 7
        ? "Every day"
        : WEEKDAYS.filter((d) => sorted.includes(d.value))
            .map((d) => d.short)
            .join(", ");
  return `${label} at ${s.time}`;
}

/**
 * Next `count` run instants (UTC Date objects) for a simple cron interpreted in `timeZone`,
 * skipping explicit skip dates (YYYY-MM-DD in the team's zone).
 */
export function nextRuns(
  cron: string,
  timeZone: string,
  count: number,
  opts: { from?: Date; skipDates?: string[] } = {},
): Date[] {
  const { time, days } = fromCron(cron);
  const from = opts.from ?? new Date();
  const skip = new Set(opts.skipDates ?? []);
  const runs: Date[] = [];
  // Walk calendar days in the team's zone; 400 days is a safe upper bound.
  for (let i = 0; i < 400 && runs.length < count; i++) {
    const localDay = formatInTimeZone(addDays(from, i), timeZone, "yyyy-MM-dd");
    const dow = Number(formatInTimeZone(fromZonedTime(`${localDay}T12:00:00`, timeZone), timeZone, "i")) % 7;
    if (!days.includes(dow) || skip.has(localDay)) continue;
    const instant = fromZonedTime(`${localDay}T${time}:00`, timeZone);
    if (instant.getTime() <= from.getTime()) continue;
    if (runs.some((r) => r.getTime() === instant.getTime())) continue;
    runs.push(instant);
  }
  return runs;
}

export const COMMON_TIMEZONES = [
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Dubai",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Australia/Sydney",
  "UTC",
] as const;
