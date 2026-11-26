from datetime import UTC, date, datetime

import pytest

from scrum_adapters.calendar import ScheduleConfig, TeamConfig, build_ics, cron_to_rrule
from scrum_core.schedule import (
    ScheduleError,
    next_runs,
    shift_cron_earlier,
    skip_reason,
    validate_cron,
    validate_timezone,
    weekdays_between,
)


def test_validate_cron():
    assert validate_cron("30  10 * * 1-5") == "30 10 * * 1-5"
    for bad in ["30 10 * *", "61 10 * * *", "every day", "30 10 * * 1-5 2026"]:
        with pytest.raises(ScheduleError):
            validate_cron(bad)


def test_unknown_timezone():
    with pytest.raises(ScheduleError):
        validate_timezone("Mars/Olympus")


def test_next_runs_in_team_timezone_and_skips_holidays():
    # Friday 2026-11-13 12:00 IST → next weekday runs at 10:30 IST (05:00 UTC), skipping a skip date.
    after = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
    runs = next_runs("30 10 * * 1-5", "Asia/Kolkata", 3, after=after, skip_dates=[date(2026, 11, 17)])
    assert [r.isoformat() for r in runs] == [
        "2026-11-16T05:00:00+00:00",
        "2026-11-18T05:00:00+00:00",
        "2026-11-19T05:00:00+00:00",
    ]
    assert skip_reason(date(2026, 1, 26), [], "IN") and "Republic" in skip_reason(date(2026, 1, 26), [], "IN")
    assert skip_reason(date(2026, 1, 27), [], "IN") is None


def test_dst_aware_next_runs():
    # Europe/London switches to BST on Sun 2026-03-29: 09:00 local is 09:00 UTC on Sat, 08:00 UTC from Sun.
    runs = next_runs("0 9 * * *", "Europe/London", 3, after=datetime(2026, 3, 27, 12, tzinfo=UTC))
    assert [(r.day, r.hour) for r in runs] == [(28, 9), (29, 8), (30, 8)]


def test_lead_minutes_shift():
    assert shift_cron_earlier("30 10 * * 1-5", 5) == "25 10 * * 1-5"
    assert shift_cron_earlier("0 10 * * 1-5", 5) == "55 9 * * 1-5"
    with pytest.raises(ScheduleError):
        shift_cron_earlier("2 0 * * 1-5", 5)


def test_weekdays_between_counts_standup_days():
    assert weekdays_between(date(2026, 11, 9), date(2026, 11, 12)) == 3  # Mon → Thu
    assert weekdays_between(date(2026, 11, 13), date(2026, 11, 16)) == 1  # Fri → Mon


def test_ics_invite():
    assert cron_to_rrule("30 10 * * 1-5") == (10, 30, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")
    ics = build_ics(
        uid="x",
        team=TeamConfig("t", "Payments", ["a@x.io"], "lead@x.io"),
        sched=ScheduleConfig("30 10 * * 1-5", "Asia/Kolkata"),
        join_url="http://meet/rooms/standup-t",
    )
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" in ics and "TZID=Asia/Kolkata" in ics and "a@x.io" in ics
