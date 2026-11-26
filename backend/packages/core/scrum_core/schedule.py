"""Cron + time-zone helpers shared by the API (next run preview) and the orchestrator (skip logic)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import holidays
from croniter import croniter


class ScheduleError(ValueError):
    pass


def validate_timezone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f"Unknown time zone {tz!r}") from exc


def validate_cron(expr: str) -> str:
    parts = expr.split()
    if len(parts) != 5 or not croniter.is_valid(expr):
        raise ScheduleError("Use a 5-field cron expression, e.g. '30 10 * * 1-5'")
    return " ".join(parts)


@lru_cache(maxsize=64)
def _holiday_calendar(country: str, year: int) -> holidays.HolidayBase:
    return holidays.country_holidays(country, years=year)


def is_holiday(day: date, country: str | None) -> str | None:
    if not country:
        return None
    try:
        cal = _holiday_calendar(country.upper(), day.year)
    except NotImplementedError:
        return None
    name = cal.get(day)
    return str(name) if name else None


def skip_reason(day: date, skip_dates: Iterable[date], holiday_calendar: str | None) -> str | None:
    if day in set(skip_dates):
        return "Skipped by the team (skip date)"
    if name := is_holiday(day, holiday_calendar):
        return f"Public holiday: {name}"
    return None


def next_runs(
    cron: str,
    tz: str,
    count: int = 5,
    *,
    after: datetime | None = None,
    skip_dates: Iterable[date] = (),
    holiday_calendar: str | None = None,
) -> list[datetime]:
    """Next ``count`` run instants (UTC-aware), honoring skip dates and public holidays."""
    zone = validate_timezone(tz)
    start = (after or datetime.now(UTC)).astimezone(zone)
    it = croniter(validate_cron(cron), start)
    skips = set(skip_dates)
    out: list[datetime] = []
    for _ in range(count * 20):
        local: datetime = it.get_next(datetime)
        if skip_reason(local.date(), skips, holiday_calendar) is None:
            out.append(local.astimezone(UTC))
            if len(out) == count:
                break
    return out


def shift_cron_earlier(cron: str, minutes: int) -> str:
    """Temporal fires ``lead_minutes`` before the meeting so context can be preloaded (plan §7.1).

    Supports the fixed minute/hour crons the UI builds ("M H * * DOW"). Day-of-week wraps are
    rejected rather than silently shifted, which only matters for meetings just after midnight.
    """
    m, h, dom, mon, dow = validate_cron(cron).split()
    if not (m.isdigit() and h.isdigit()) or minutes == 0:
        return cron
    total = int(h) * 60 + int(m) - minutes
    if total < 0:
        raise ScheduleError("Meeting is too close to midnight for the configured lead time")
    return f"{total % 60} {total // 60} {dom} {mon} {dow}"


def today_in(tz: str, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(validate_timezone(tz)).date()


def local_dt(day: date, hhmm: str, tz: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=validate_timezone(tz))


def weekdays_between(start: date, end: date) -> int:
    """Weekdays strictly after ``start`` up to and including ``end`` (standup days elapsed)."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
