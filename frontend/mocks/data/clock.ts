import { addDays, format, isWeekend, parseISO, previousFriday, isFriday } from "date-fns";
import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

export const TZ = "Asia/Kolkata";

/**
 * The mock world is anchored to the most recent Friday on or before today, so the story week
 * (Mon–Fri) is always "the last 7 days" when you open the dashboard on or after that Friday.
 */
export function storyFriday(today: Date = new Date()): string {
  const local = parseISO(formatInTimeZone(today, TZ, "yyyy-MM-dd"));
  const fri = isFriday(local) ? local : previousFriday(local);
  return format(fri, "yyyy-MM-dd");
}

export function shiftDate(date: string, days: number): string {
  return format(addDays(parseISO(date), days), "yyyy-MM-dd");
}

/** Weekdays (Mon–Fri) from `start` to `end` inclusive. */
export function weekdaysBetween(start: string, end: string): string[] {
  const out: string[] = [];
  for (let d = parseISO(start); format(d, "yyyy-MM-dd") <= end; d = addDays(d, 1)) {
    if (!isWeekend(d)) out.push(format(d, "yyyy-MM-dd"));
  }
  return out;
}

/** Local wall-clock time on `date` in the team zone → ISO with offset. */
export function at(date: string, time: string, plusMs = 0): string {
  const instant = new Date(fromZonedTime(`${date}T${time}:00`, TZ).getTime() + plusMs);
  return formatInTimeZone(instant, TZ, "yyyy-MM-dd'T'HH:mm:ssXXX");
}

export function nowIso(): string {
  return formatInTimeZone(new Date(), TZ, "yyyy-MM-dd'T'HH:mm:ssXXX");
}
