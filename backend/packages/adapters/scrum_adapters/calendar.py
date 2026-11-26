"""Recurring standup meeting (plan §5 CalendarAdapter).

Open-source build: the meeting is a LiveKit room (``standup-<team>``); people join through any
LiveKit client, e.g. the open-source LiveKit Meet app. Members receive an iCalendar invite
(RFC 5545, RRULE derived from the cron) by email so the meeting lands in any calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from scrum_adapters.mail import Attachment, MailAdapter, OutboundMail

_DOW = {"0": "SU", "1": "MO", "2": "TU", "3": "WE", "4": "TH", "5": "FR", "6": "SA", "7": "SU"}


@dataclass
class MeetingRef:
    id: str
    join_url: str


@dataclass
class TeamConfig:
    team_id: str
    team_name: str
    attendee_emails: list[str]
    organizer_email: str


@dataclass
class ScheduleConfig:
    cron: str
    timezone: str
    duration_minutes: int = 15


class CalendarAdapter(Protocol):
    async def create_recurring_meeting(self, team: TeamConfig, sched: ScheduleConfig) -> MeetingRef: ...
    async def update_recurring_meeting(self, ref: MeetingRef, team: TeamConfig, sched: ScheduleConfig) -> None: ...


def cron_to_rrule(cron: str) -> tuple[int, int, str]:
    """``"30 10 * * 1-5"`` → (10, 30, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")."""
    m, h, _dom, _mon, dow = cron.split()
    days: list[str] = []
    for part in ("1-5" if dow == "*" else dow).split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            days += [_DOW[str(d)] for d in range(a, b + 1)]
        else:
            days.append(_DOW[part])
    return int(h), int(m), "FREQ=WEEKLY;BYDAY=" + ",".join(dict.fromkeys(days))


def build_ics(*, uid: str, team: TeamConfig, sched: ScheduleConfig, join_url: str, sequence: int = 0) -> str:
    h, m, rrule = cron_to_rrule(sched.cron)
    start = datetime.now(UTC).date() + timedelta(days=1)
    dtstart = f"{start:%Y%m%d}T{h:02d}{m:02d}00"
    end_total = h * 60 + m + sched.duration_minutes
    dtend = f"{start:%Y%m%d}T{end_total // 60:02d}{end_total % 60:02d}00"
    attendees = "\r\n".join(f"ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{e}" for e in team.attendee_emails)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Scrum Bot//EN",
            "METHOD:REQUEST",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SEQUENCE:{sequence}",
            f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            f"DTSTART;TZID={sched.timezone}:{dtstart}",
            f"DTEND;TZID={sched.timezone}:{dtend}",
            f"RRULE:{rrule}",
            f"SUMMARY:{team.team_name} daily standup (Scrum Bot)",
            f"LOCATION:{join_url}",
            f"DESCRIPTION:Join: {join_url}",
            f"ORGANIZER:mailto:{team.organizer_email}",
            attendees,
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


class LiveKitRoomCalendar:
    def __init__(self, join_url_template: str, mail: MailAdapter | None = None) -> None:
        self._template = join_url_template
        self._mail = mail

    def _url(self, room: str) -> str:
        return self._template.format(room=room) if "{room}" in self._template else f"{self._template}{room}"

    async def _invite(self, ref: MeetingRef, team: TeamConfig, sched: ScheduleConfig, sequence: int) -> None:
        if not self._mail or not team.attendee_emails:
            return
        ics = build_ics(uid=f"{ref.id}@scrumbot", team=team, sched=sched, join_url=ref.join_url, sequence=sequence)
        await self._mail.send(
            OutboundMail(
                to=team.attendee_emails,
                subject=f"Invitation: {team.team_name} daily standup",
                html=f"<p>Scrum Bot will run the {team.team_name} standup here: <a href='{ref.join_url}'>"
                f"{ref.join_url}</a></p>",
                text=f"Join: {ref.join_url}",
                attachments=[Attachment("invite.ics", ics.encode(), "text/calendar")],
            ),
            idempotency_key=f"invite:{ref.id}:{sequence}:{sched.cron}:{sched.timezone}",
        )

    async def create_recurring_meeting(self, team: TeamConfig, sched: ScheduleConfig) -> MeetingRef:
        room = f"standup-{team.team_id}"
        ref = MeetingRef(id=room, join_url=self._url(room))
        await self._invite(ref, team, sched, 0)
        return ref

    async def update_recurring_meeting(self, ref: MeetingRef, team: TeamConfig, sched: ScheduleConfig) -> None:
        await self._invite(ref, team, sched, int(datetime.now(UTC).timestamp()) // 60)
