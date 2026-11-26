"""API against the seeded story (the same assertions as frontend/tests/integration/story.test.ts)."""

from datetime import timedelta

import pytest
from conftest import as_

from scrum_adapters import registry
from scrum_core.security.tokens import blocker_token, checkin_token

pytestmark = pytest.mark.db
NEHA, DEEPA, RAHUL, VIKRAM = as_("u-neha"), as_("u-deepa"), as_("u-rahul"), as_("u-vikram")


def week(seeded) -> dict[str, str]:
    fri = seeded["fri"]
    return {"team": str(seeded["payments"]), "from": str(fri - timedelta(days=6)), "to": str(fri)}


async def test_me_and_auth_errors_are_problem_json(client):
    r = await client.get("/me", headers=NEHA)
    assert r.status_code == 200 and r.json()["role"] == "scrum_lead" and r.json()["onboarded"] is True
    r = await client.get("/me")
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Unauthorized"


async def test_story_dashboard_numbers(client, seeded):
    q = week(seeded)
    part = (await client.get("/metrics/participation", params=q, headers=NEHA)).json()
    assert round(part["rate"], 2) == 0.96 and len(part["series"]) == 5
    assert part["series"][1]["async"] == 1  # Karan answered Tuesday's check-in
    blk = (await client.get("/metrics/blockers", params=q, headers=NEHA)).json()
    assert (blk["raised"], blk["resolved"], blk["open"]) == (4, 3, 1)
    assert round(blk["avg_resolve_days"], 1) == 1.2
    mism = (await client.get("/metrics/mismatches", params=q, headers=NEHA)).json()
    assert [(m["member_name"], m["ticket_key"], m["pm_status"]) for m in mism] == [
        ("Sneha Joshi", "PROJ-155", "In Progress")
    ]
    deps = (await client.get("/metrics/dependencies", params=q, headers=NEHA)).json()
    top = max(deps["edges"], key=lambda e: e["weight"])
    assert top["target"] == "ext:Backend Platform"
    themes = (await client.get("/metrics/themes", params=q, headers=NEHA)).json()
    assert themes[0] == {"label": "Code review latency", "count": 5, "trend": "up"}
    burndown = (await client.get("/metrics/burndown", params=q, headers=NEHA)).json()
    assert burndown["sprint_name"] == "Sprint 24" and burndown["points"]


async def test_role_scoping(client, seeded):
    sessions = (await client.get(f"/teams/{seeded['payments']}/sessions", headers=NEHA)).json()["items"]
    tue = next(s for s in sessions if s["run_date"] == str(seeded["fri"] - timedelta(days=3)))
    assert tue["blocker_count"] == 3 and tue["attendance_pct"] == 1.0

    full = (await client.get(f"/sessions/{tue['id']}/transcript", headers=NEHA)).json()
    own = (await client.get(f"/sessions/{tue['id']}/transcript", headers=RAHUL)).json()
    assert len(full) > len(own) > 0 and {s["speaker_label"] for s in own} == {"Rahul Verma"}
    assert (await client.get(f"/sessions/{tue['id']}/transcript", headers=VIKRAM)).status_code == 403

    q = week(seeded)
    assert [m["member_name"] for m in (await client.get("/metrics/mismatches", params=q, headers=VIKRAM)).json()] == [
        "—"
    ]
    assert (await client.get("/metrics/mismatches", params=q, headers=RAHUL)).json() == []  # not his row
    assert (await client.get("/audit-log", headers=NEHA)).status_code == 403
    assert (await client.get("/integrations", headers=DEEPA)).status_code == 200
    r = await client.post("/integrations/teams/connect", headers=NEHA)
    assert r.status_code == 403
    r = await client.get("/review-items", headers=RAHUL)
    assert r.status_code == 403


async def test_blocker_email_link_flow(client, seeded):
    org, sid = seeded["org_id"], seeded["sid"]
    blk = sid("blk-priya-review")
    token = blocker_token(org_id=org, blocker_id=blk, recipient="arjun.patel@acme.example")
    preview = (await client.get(f"/actions/{token}")).json()
    assert preview["kind"] == "blocker" and preview["allowed_actions"] == ["acknowledge", "resolve"]
    assert preview["blocker"]["days_open"] == 4 and preview["blocker"]["reporter_name"] == "Priya Nair"

    assert (await client.post(f"/actions/{token}", json={"action": "acknowledge"})).json() == {"status": "acknowledged"}
    again = (await client.get(f"/actions/{token}")).json()
    assert again["allowed_actions"] == ["resolve"]  # single use per action
    assert (await client.post(f"/actions/{token}", json={"action": "resolve"})).json() == {"status": "resolved"}
    detail = (await client.get(f"/blockers/{blk}", headers=NEHA)).json()
    assert detail["status"] == "resolved" and detail["events"][-1]["actor_name"] == "Arjun Patel"
    assert detail["evidence"] and detail["evidence"][0]["speaker_label"] == "Priya Nair"

    expired = blocker_token(org_id=org, blocker_id=blk, recipient="arjun.patel@acme.example", ttl_seconds=-1)
    assert (await client.get(f"/actions/{expired}")).json()["expired"] is True
    assert (await client.post(f"/actions/{expired}", json={"action": "resolve"})).status_code == 410
    assert (await client.get("/actions/not-a-token")).status_code == 404


async def test_async_checkin_flow(client, seeded):
    import time

    org, sid, fri = seeded["org_id"], seeded["sid"], seeded["fri"]
    ses = sid(f"ses-payments-{fri}")
    tok = checkin_token(org_id=org, session_id=ses, user_id=sid("u-karan"), expires_at=int(time.time()) + 600)
    preview = (await client.get(f"/actions/{tok}")).json()
    assert preview["kind"] == "checkin" and len(preview["checkin"]["questions"]) == 3
    qids = [q["id"] for q in preview["checkin"]["questions"]]
    r = await client.post(f"/async-checkins/{tok}", json={"answers": {qids[0]: "Payout dashboard PROJ-158"}})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == set(qids[1:])
    r = await client.post(
        f"/async-checkins/{tok}", json={"answers": dict(zip(qids, ["Done", "More", "None"], strict=True))}
    )
    assert r.json() == {"status": "submitted"}
    assert (await client.post(f"/async-checkins/{tok}", json={"answers": {}})).status_code == 409
    att = (await client.get(f"/sessions/{ses}/attendance", headers=NEHA)).json()
    assert next(a for a in att if a["display_name"] == "Karan Mehta")["status"] in ("present", "async")


async def test_review_queue_person_match_learns_alias(client, seeded):
    sid = seeded["sid"]
    items = (await client.get("/review-items", headers=NEHA)).json()["items"]
    person = next(i for i in items if i["kind"] == "person_match")
    assert [c["label"] for c in person["candidates"]] == ["Amit Sharma", "Amit Singh"]
    r = await client.post(f"/review-items/{person['id']}/approve", json={"candidate_id": "nope"}, headers=NEHA)
    assert r.status_code == 422
    r = await client.post(
        f"/review-items/{person['id']}/approve", json={"candidate_id": str(sid("u-amit"))}, headers=NEHA
    )
    assert r.json()["status"] == "approved"
    assert (await client.post(f"/review-items/{person['id']}/reject", headers=NEHA)).status_code == 409
    amit = next(u for u in (await client.get("/users", params={"search": "amit sharma"}, headers=NEHA)).json()["items"])
    assert "Amit" in amit["aliases"]

    pm = next(i for i in items if i["kind"] == "pm_writeback")
    await client.post(f"/review-items/{pm['id']}/approve", json={"candidate_id": "transition-done"}, headers=NEHA)
    assert (await registry.fake_pm().get_ticket("PROJ-142")).status == "Done"


async def test_team_config_versioning_schedule_and_idempotency(client, seeded):
    team = seeded["payments"]
    tpls = (await client.get(f"/teams/{team}/templates", headers=NEHA)).json()
    assert [t["version"] for t in tpls] == [2, 1] and tpls[0]["is_active"]
    body = {
        "questions": [
            {"text": "What did you ship?", "type": "ticket_list"},
            {"text": "Anything blocking you?", "followup_policy": "none", "max_followups": 2},
        ]
    }
    new = (await client.post(f"/teams/{team}/templates", json=body, headers=NEHA)).json()
    assert new["version"] == 3 and new["is_active"] and new["questions"][1]["max_followups"] == 0
    back = (await client.post(f"/templates/{tpls[0]['id']}/activate", headers=NEHA)).json()
    assert back["version"] == 2 and back["is_active"]

    bad = await client.put(
        f"/teams/{team}/schedule", json={"cron": "every morning", "timezone": "Asia/Kolkata"}, headers=NEHA
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "cron"
    ok = await client.put(
        f"/teams/{team}/schedule",
        headers=NEHA,
        json={
            "cron": "45 9 * * 1-5",
            "timezone": "Asia/Kolkata",
            "holiday_calendar": "IN",
            "skip_dates": [],
            "async_window_minutes": 90,
            "lead_minutes": 5,
            "paused": False,
        },
    )
    assert ok.status_code == 200 and ok.json()["join_url"].endswith(f"standup-{team}")
    t = (await client.get(f"/teams/{team}", headers=NEHA)).json()
    assert t["next_run_at"] and t["next_run_at"].endswith(("04:15:00Z", "04:15:00+00:00"))

    other = seeded["backend"]
    # Not her team: hidden entirely (404, no existence leak) rather than 403.
    assert (await client.put(f"/teams/{other}/members", json=[], headers=NEHA)).status_code == 404

    key = {"Idempotency-Key": "create-team-1", **NEHA}
    first = await client.post("/teams", json={"name": "Checkout", "timezone": "Asia/Kolkata"}, headers=key)
    second = await client.post("/teams", json={"name": "Checkout", "timezone": "Asia/Kolkata"}, headers=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"] and second.headers.get("idempotent-replayed") == "true"
    dup = await client.post("/teams", json={"name": "checkout"}, headers=NEHA)
    assert dup.status_code == 422 and dup.json()["errors"][0]["field"] == "name"


async def test_erase_and_export(client, seeded):
    sid = seeded["sid"]
    exp = (await client.get(f"/users/{sid('u-sneha')}/export", headers=DEEPA)).json()
    assert exp["user"]["display_name"] == "Sneha Joshi" and exp["transcript_segments"]
    assert (await client.get(f"/users/{sid('u-sneha')}/export", headers=RAHUL)).status_code == 403
    assert (await client.post(f"/users/{sid('u-sneha')}/erase", headers=DEEPA)).status_code == 204
    ses = sid(f"ses-payments-{seeded['fri']}")
    segs = (await client.get(f"/sessions/{ses}/transcript", headers=NEHA)).json()
    assert not any(s["speaker_label"] == "Sneha Joshi" for s in segs)
    assert any(s["text"] == "[redacted on erasure request]" for s in segs)
    audit = (await client.get("/audit-log", params={"entity": "user"}, headers=DEEPA)).json()["items"]
    assert audit[0]["action"] == "user.erased"
