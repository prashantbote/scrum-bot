"""Project-management adapters (plan §5): Jira Cloud REST + an in-memory fake catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

import httpx


@dataclass
class Ticket:
    key: str
    summary: str
    status: str
    assignee_account_id: str | None = None
    url: str | None = None


@dataclass
class TicketChange:
    transition_to: str | None = None
    comment: str | None = None


@dataclass
class BurndownPoint:
    date: date
    ideal: float
    remaining: float


@dataclass
class Burndown:
    sprint_name: str
    points: list[BurndownPoint] = field(default_factory=list)


class PMAdapter(Protocol):
    name: str

    async def open_items_for(self, account_ids: list[str]) -> dict[str, list[Ticket]]: ...
    async def get_ticket(self, key: str) -> Ticket | None: ...
    async def propose_update(self, key: str, change: TicketChange) -> None: ...  # approval-gated by callers
    async def sprint_burndown(self, board_id: str) -> Burndown: ...


# ------------------------------------------------------------------------------------------


_FAKE_TICKETS: list[tuple[str, str, str, str | None]] = [
    ("PROJ-131", "Card tokenization", "Done", "jira-rahul"),
    ("PROJ-134", "UPI retry flow", "In Progress", "jira-karan"),
    ("PROJ-136", "Fraud rules engine", "To Do", None),
    ("PROJ-138", "Webhook signature validation", "Done", "jira-amit"),
    ("PROJ-142", "Refund API", "In Review", "jira-rahul"),
    ("PROJ-147", "Invoice PDF", "In Progress", "jira-priya"),
    ("PROJ-150", "Payment UI", "In Review", "jira-priya"),
    ("PROJ-152", "Merchant onboarding form", "In Progress", "jira-sneha"),
    ("PROJ-155", "Settlement report export", "In Progress", "jira-sneha"),
    ("PROJ-158", "Payout reconciliation", "In Progress", "jira-karan"),
    ("PROJ-160", "Payouts v2 API integration", "In Progress", "jira-karan"),
    ("BE-210", "Sandbox credential rotation", "Done", "jira-amit"),
    ("BE-214", "Rate limiter", "Done", "jira-amit"),
    ("BE-219", "Ledger service migration", "In Progress", "jira-meera"),
    ("BE-223", "Kafka consumer lag alerts", "To Do", "jira-amits"),
    ("BE-227", "API contract v2", "Done", "jira-arjun"),
    ("BE-230", "Postgres connection pooling", "In Progress", "jira-meera"),
]


class FakePMAdapter:
    name = "fake-pm"

    def __init__(
        self, tickets: list[tuple[str, str, str, str | None]] | None = None, *, sprint_start: date | None = None
    ) -> None:
        self.tickets = {k: Ticket(k, s, st, a) for k, s, st, a in (tickets or _FAKE_TICKETS)}
        self.changes: list[tuple[str, TicketChange]] = []
        self._sprint_start = sprint_start

    async def open_items_for(self, account_ids: list[str]) -> dict[str, list[Ticket]]:
        out: dict[str, list[Ticket]] = {a: [] for a in account_ids}
        for t in self.tickets.values():
            if t.assignee_account_id in out and t.status != "Done":
                out[t.assignee_account_id].append(t)
        return out

    async def get_ticket(self, key: str) -> Ticket | None:
        return self.tickets.get(key.upper())

    async def propose_update(self, key: str, change: TicketChange) -> None:
        self.changes.append((key, change))
        if change.transition_to and key in self.tickets:
            self.tickets[key].status = change.transition_to

    async def sprint_burndown(self, board_id: str) -> Burndown:
        start = self._sprint_start or (date.today() - timedelta(days=11))
        while start.weekday() != 0:
            start -= timedelta(days=1)
        total, remaining = 48, [48, 46, 43, 41, 38, 33, 30, 26, 22, 19]
        days = [start + timedelta(days=i) for i in range(14) if (start + timedelta(days=i)).weekday() < 5]
        pts = [
            BurndownPoint(d, round(total - total / 9 * i, 1), remaining[i])
            for i, d in enumerate(days[:10])
            if d <= date.today()
        ]
        return Burndown(sprint_name="Sprint 24", points=pts)


# ------------------------------------------------------------------------------------------


class JiraCloudAdapter:
    """Jira Cloud REST v3 + Agile API using an OAuth 2.0 (3LO) access token.

    ``base_url`` is ``https://api.atlassian.com/ex/jira/<cloud_id>`` for OAuth apps, or the site URL
    with an API token (basic auth) for self-managed setups.
    """

    name = "jira"

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        story_points_field: str = "customfield_10016",
        site_url: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._sp = story_points_field
        self._site = (site_url or base_url).rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, headers=self._headers, timeout=30)

    def _ticket(self, issue: dict[str, Any]) -> Ticket:
        f = issue.get("fields", {})
        return Ticket(
            key=issue["key"],
            summary=f.get("summary", ""),
            status=(f.get("status") or {}).get("name", "Unknown"),
            assignee_account_id=(f.get("assignee") or {}).get("accountId"),
            url=f"{self._site}/browse/{issue['key']}",
        )

    async def open_items_for(self, account_ids: list[str]) -> dict[str, list[Ticket]]:
        out: dict[str, list[Ticket]] = {a: [] for a in account_ids}
        if not account_ids:
            return out
        ids = ",".join(f'"{a}"' for a in account_ids)
        jql = f"assignee in ({ids}) AND statusCategory != Done ORDER BY updated DESC"
        async with self._client() as http:
            r = await http.post(
                "/rest/api/3/search/jql",
                json={"jql": jql, "fields": ["summary", "status", "assignee"], "maxResults": 100},
            )
            r.raise_for_status()
        for issue in r.json().get("issues", []):
            t = self._ticket(issue)
            if t.assignee_account_id in out:
                out[t.assignee_account_id].append(t)
        return out

    async def get_ticket(self, key: str) -> Ticket | None:
        async with self._client() as http:
            r = await http.get(f"/rest/api/3/issue/{key}", params={"fields": "summary,status,assignee"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return self._ticket(r.json())

    async def propose_update(self, key: str, change: TicketChange) -> None:
        async with self._client() as http:
            if change.transition_to:
                tr = await http.get(f"/rest/api/3/issue/{key}/transitions")
                tr.raise_for_status()
                match = next(
                    (t for t in tr.json()["transitions"] if t["to"]["name"].lower() == change.transition_to.lower()),
                    None,
                )
                if match is None:
                    raise ValueError(f"No transition to {change.transition_to!r} for {key}")
                (
                    await http.post(f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": match["id"]}})
                ).raise_for_status()
            if change.comment:
                body = {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": change.comment}]}],
                }
                (await http.post(f"/rest/api/3/issue/{key}/comment", json={"body": body})).raise_for_status()

    async def sprint_burndown(self, board_id: str) -> Burndown:
        async with self._client() as http:
            sp = await http.get(f"/rest/agile/1.0/board/{board_id}/sprint", params={"state": "active"})
            sp.raise_for_status()
            sprints = sp.json().get("values", [])
            if not sprints:
                return Burndown(sprint_name="No active sprint")
            sprint = sprints[0]
            issues = await http.get(
                f"/rest/agile/1.0/sprint/{sprint['id']}/issue",
                params={"fields": f"resolutiondate,{self._sp}", "maxResults": 500},
            )
            issues.raise_for_status()
        start = date.fromisoformat(sprint["startDate"][:10])
        end = date.fromisoformat(sprint["endDate"][:10])
        items = [
            (float(i["fields"].get(self._sp) or 0), i["fields"].get("resolutiondate"))
            for i in issues.json().get("issues", [])
        ]
        total = sum(p for p, _ in items)
        days = [
            start + timedelta(days=n)
            for n in range((end - start).days + 1)
            if (start + timedelta(days=n)).weekday() < 5
        ]
        points: list[BurndownPoint] = []
        for i, d in enumerate(days):
            if d > date.today():
                break
            done = sum(p for p, res in items if res and date.fromisoformat(res[:10]) <= d)
            ideal = total - total * i / max(1, len(days) - 1)
            points.append(BurndownPoint(d, round(ideal, 1), total - done))
        return Burndown(sprint_name=sprint.get("name", "Sprint"), points=points)
