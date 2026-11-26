import { formatInTimeZone } from "date-fns-tz";
import { differenceInCalendarDays, format, parseISO } from "date-fns";

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed delta for KPI chips: "+2", "−0.4". Uses a true minus sign for typographic alignment. */
export function signed(value: number, digits = 0): string {
  const abs = Math.abs(value).toFixed(digits);
  if (Number(abs) === 0) return "0";
  return value > 0 ? `+${abs}` : `−${abs}`;
}

export function days(value: number, digits = 1): string {
  return `${value.toFixed(digits)} d`;
}

/** 754 → "12m 34s"; 3725 → "1h 2m". */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.round(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

/** Transcript offset in ms → "mm:ss". */
export function offset(ms: number): string {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)
    .toString()
    .padStart(2, "0")}:${(total % 60).toString().padStart(2, "0")}`;
}

export function shortDate(iso: string): string {
  return format(parseISO(iso), "EEE d MMM");
}

export function longDate(iso: string): string {
  return format(parseISO(iso), "EEEE, d MMMM yyyy");
}

export function dateTimeInZone(iso: string, timeZone: string, pattern = "EEE d MMM, HH:mm"): string {
  return formatInTimeZone(parseISO(iso), timeZone, pattern);
}

export function relativeDays(iso: string, now: Date = new Date()): string {
  const d = differenceInCalendarDays(now, parseISO(iso));
  if (d <= 0) return "today";
  if (d === 1) return "yesterday";
  return `${d} days ago`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

export function plural(n: number, word: string, pluralWord = `${word}s`): string {
  return `${n} ${n === 1 ? word : pluralWord}`;
}
