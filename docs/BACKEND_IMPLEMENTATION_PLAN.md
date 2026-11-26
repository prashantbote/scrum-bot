# Scrum Bot: Backend Implementation Plan

> Scope: everything under `backend/` and `infra/`. Companion docs: [README](README.md) · [Frontend plan](FRONTEND_IMPLEMENTATION_PLAN.md)
>
> **Implementation note:** the backend is implemented on an open-source stack: Ollama/vLLM (OpenAI-compatible)
> instead of hosted LLMs, LiveKit instead of Recall.ai/Teams, faster-whisper and Piper instead of Deepgram/Azure,
> SMTP instead of Graph, and any OIDC provider instead of Entra-only. The interfaces in §5 are unchanged. See
> [backend/README.md](../backend/README.md) for the substitution table, quick start and known gaps.

---

## 1. Goals and non-goals

**MVP goals**
- Multi-tenant config API (orgs, teams, members, question templates, schedules, integrations) behind Entra ID SSO.
- A daily standup runs as a durable Temporal workflow on a per-team schedule.
- The voice agent joins Teams through **Recall.ai** (MeetingProvider option B) and runs a turn-based standup.
- Structured extraction, people resolution and an email digest.

**v1 goals:** blocker alerts and lifecycle, escalation, Jira context preload, async Adaptive Card fallback, review queue.

**v2 goals:** dashboard analytics, PM write-back with approval, Zoom/Meet providers, the .NET media bridge (option A) for enterprise tenants.

**Non-goals for MVP:** outbound ringing calls, real-time transcript streaming to the UI, self-hosted LLMs, ClickHouse.

---

## 2. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | `uv` workspace, one lockfile |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic | |
| Workflows | Temporal Python SDK | Temporal Cloud in prod, `temporalite`/dev server locally |
| Voice | Pipecat, Silero VAD, Deepgram Nova (STT), Azure Neural TTS / ElevenLabs | STT/TTS behind adapters |
| LLM | LiteLLM gateway + `instructor` | Fast model for live turns, strong model for extraction |
| Data | PostgreSQL 16 + pgvector, Redis 7, Azure Blob / S3 (MinIO locally) | |
| Email/Teams | Microsoft Graph (`sendMail`, Adaptive Cards via Bot Framework) | SendGrid/SES as fallback adapter |
| Rendering | Jinja2, WeasyPrint (PDF), python-docx (optional) | |
| Matching | rapidfuzz, pgvector cosine | |
| Infra | Docker, Kubernetes (separate voice node pool), Helm, KEDA, Terraform | |
| Observability | OpenTelemetry, Prometheus/Grafana, Sentry, Langfuse | |
| Quality | ruff, mypy (strict on `packages/`), pytest, testcontainers, pre-commit | |

---

## 3. Folder structure

```
backend/
├── pyproject.toml                  # uv workspace root
├── Makefile                        # make dev | test | lint | migrate | openapi
├── openapi.json                    # generated, committed, consumed by frontend
├── migrations/                     # Alembic (single DB, all services)
│   └── versions/
├── packages/
│   ├── core/                       # shared, no service imports allowed
│   │   └── scrum_core/
│   │       ├── settings.py         # pydantic-settings, per-env
│   │       ├── db.py               # async engine, session factory, set_org_context()
│   │       ├── models/             # SQLAlchemy ORM models (one file per aggregate)
│   │       ├── schemas/            # Pydantic DTOs shared across services
│   │       ├── security/           # envelope encryption, HMAC action tokens
│   │       ├── audit.py            # write_audit(actor, action, entity, diff)
│   │       └── telemetry.py        # OTel + Sentry bootstrap
│   └── adapters/
│       └── scrum_adapters/
│           ├── meeting/            # base.py, recall.py, graph_bridge.py (v2), fake.py
│           ├── pm/                 # base.py, jira.py, azure_devops.py (v2), fake.py
│           ├── mail/               # base.py, graph_mail.py, sendgrid.py, fake.py
│           ├── stt/  tts/  llm/    # Deepgram/Azure, Azure/ElevenLabs, LiteLLM wrapper
│           └── calendar/           # Graph online meetings + recurring events
├── services/
│   ├── api/                        # FastAPI app: routers/, deps/, rbac.py, main.py
│   ├── orchestrator/               # workflows/, activities/, schedules.py, worker.py
│   ├── voice_agent/                # pipeline.py, controller/, prompts/, worker.py
│   ├── intelligence/               # extraction.py, resolution.py, blocker_match.py, evals/
│   └── delivery/                   # templates/, render.py, mailer.py, cards.py, pm_sync.py
├── tests/
│   ├── unit/  integration/  workflows/  voice/  evals/  e2e/
│   └── fixtures/                   # golden transcripts, audio clips, seed data
└── docker/                         # one Dockerfile per service (multi-stage)
```

**Dependency rule:** `services/*` → `packages/adapters` → `packages/core`. Services never import each other and communicate only through Temporal or the database. `import-linter` enforces this in CI.

---

## 4. Data model

Every tenant-scoped table has `id UUID PK`, `org_id UUID NOT NULL`, `created_at` and `updated_at`.

### 4.1 Tables

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | name, entra_tenant_id (unique), retention_days_audio, retention_days_transcript, settings JSONB | Not RLS'd; access via membership |
| `users` | entra_oid (unique per org), email, display_name, aliases TEXT[], department, role ENUM(org_admin, scrum_lead, member, viewer) | `aliases` feeds STT vocabulary and resolution |
| `teams` | name, lead_user_id, timezone, meeting_provider, active | |
| `team_members` | team_id, user_id, pm_account_id, speaking_order | unique(team_id, user_id) |
| `integrations` | kind ENUM(teams, jira, ado, mail…), status, config JSONB, encrypted_token BYTEA, key_id, expires_at | Envelope-encrypted |
| `question_templates` | team_id, version INT, is_active, created_by | unique(team_id, version); immutable once used |
| `questions` | template_id, position, text, type ENUM(text, yes_no, ticket_list), required, followup_policy ENUM(none, if_vague, always), max_followups | |
| `schedules` | team_id, cron, timezone, holiday_calendar_id, skip_dates DATE[], async_window_minutes, temporal_schedule_id, recurring_meeting_id, join_url | |
| `standup_sessions` | team_id, run_date, template_id, status ENUM(scheduled, running, extracting, delivered, skipped, failed), workflow_id, started_at, ended_at, recording_uri | unique(team_id, run_date) |
| `attendance` | session_id, user_id, status ENUM(present, absent, async), joined_at | |
| `transcript_segments` | session_id, speaker_user_id NULL, speaker_label, question_id NULL, start_ms, end_ms, text, confidence | index(session_id, start_ms) |
| `member_updates` | session_id, user_id, source ENUM(voice, async), payload JSONB (MemberUpdate), extraction_model, version | |
| `blockers` | team_id, reporter_user_id, blocked_on_user_id NULL, blocked_on_raw, description, ticket_keys TEXT[], severity, status ENUM(open, acknowledged, resolved, needs_review), first_seen_session_id, last_seen_session_id, days_open, embedding VECTOR(1536), resolved_at | ivfflat/HNSW on embedding; GIN on ticket_keys |
| `blocker_evidence` | blocker_id, segment_id | grounding links |
| `dependencies` | session_id, from_user_id, to_user_id NULL, to_team_id NULL, description, ticket_keys | dependency graph source |
| `review_items` | kind ENUM(person_match, blocker_match, pm_writeback), payload JSONB, confidence, status ENUM(pending, approved, rejected), decided_by | |
| `reports` | session_id, html_uri, pdf_uri, summary JSONB | |
| `notifications` | session_id, recipient, type ENUM(digest, blocker_alert, escalation, async_checkin), status, provider_message_id, sent_at | **unique(session_id, recipient, type)** → idempotency |
| `audit_log` | actor_user_id, action, entity_type, entity_id, diff JSONB, ip | append-only, no UPDATE/DELETE grants |

### 4.2 Row-level security pattern

```sql
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON teams
  USING (org_id = current_setting('app.org_id')::uuid)
  WITH CHECK (org_id = current_setting('app.org_id')::uuid);
```

- `scrum_core.db.session_for(org_id)` runs `SET LOCAL app.org_id = :org_id` at the start of every transaction. API dependencies and Temporal activities both go through it.
- The application DB role is **not** the table owner and has no `BYPASSRLS`. Migrations run as a separate owner role.
- An Alembic helper `enable_rls(table)` is used in every migration that creates a tenant table, and a CI test asserts that every table with an `org_id` column has a policy.

---

## 5. Adapter interfaces

```python
# packages/adapters/scrum_adapters/meeting/base.py
class MeetingProvider(Protocol):
    async def join(self, join_url: str, display_name: str) -> CallHandle: ...
    async def set_recording_status(self, call: CallHandle, recording: bool) -> None: ...
    def audio_in(self, call: CallHandle) -> AsyncIterator[AudioFrame]: ...      # 16 kHz PCM, speaker hint if available
    async def audio_out(self, call: CallHandle, frame: AudioFrame) -> None: ...
    async def participants(self, call: CallHandle) -> list[Participant]: ...    # name, email/aad_oid, is_speaking
    async def leave(self, call: CallHandle) -> None: ...

class PMAdapter(Protocol):
    async def open_items_for(self, account_ids: list[str]) -> dict[str, list[Ticket]]: ...
    async def get_ticket(self, key: str) -> Ticket | None: ...
    async def propose_update(self, key: str, change: TicketChange) -> None: ...   # v2, approval-gated
    async def sprint_burndown(self, board_id: str) -> Burndown: ...

class MailAdapter(Protocol):
    async def send(self, msg: OutboundMail, idempotency_key: str) -> str: ...     # returns provider id

class CalendarAdapter(Protocol):
    async def create_recurring_meeting(self, team: TeamConfig, sched: ScheduleConfig) -> MeetingRef: ...
    async def update_recurring_meeting(self, ref: MeetingRef, sched: ScheduleConfig) -> None: ...
```

| Interface | MVP implementation | Later |
|---|---|---|
| MeetingProvider | `RecallMeetingProvider` (bot API + real-time audio WebSocket) | `GraphMediaBridgeProvider` (.NET on Windows Server, PCM over WebSocket), Zoom, Meet |
| PMAdapter | Jira Cloud (OAuth 3LO) | Azure DevOps, Linear, ClickUp |
| MailAdapter | Graph `sendMail` (app permission `Mail.Send`, sender = service mailbox) | SendGrid / SES |
| STT / TTS | Deepgram streaming with `keywords` boosting / Azure Neural TTS | Azure Speech phrase lists, ElevenLabs |

- Every adapter has a `fake.py` used in unit tests and local demo mode (`SCRUM_FAKE_PROVIDERS=1`).
- **Token storage:** each token is encrypted with a per-record DEK (AES-256-GCM). The DEK is wrapped by a KEK in Azure Key Vault (or Vault Transit). The table stores `encrypted_token`, `wrapped_dek` and `key_id`, and a background job refreshes OAuth tokens before they expire.

---

## 6. API service (`services/api`)

### 6.1 Auth and RBAC
- Validates Entra ID JWTs against the tenant JWKS (`fastapi-azure-auth` or a custom `python-jose` check) and maps `tid` to `organizations.entra_tenant_id` and `oid` to `users`.
- The first user of a new tenant becomes `org_admin` after admin consent (the Graph permissions are `Calls.JoinGroupCall.All`, `Calls.AccessMedia.All`, `OnlineMeetings.ReadWrite.All`, `Calendars.ReadWrite` and `Mail.Send`).
- The `require_role(*roles)` dependency checks roles. Scrum Leads are additionally scoped to the teams they lead, and Members can see only their own individual data.

| Capability | Org Admin | Scrum Lead | Member | Viewer |
|---|---|---|---|---|
| Manage org, integrations, users | ✔ | – | – | – |
| Configure own teams (members, templates, schedule) | ✔ | ✔ | – | – |
| View team reports and blockers | ✔ | ✔ | ✔ (own team) | ✔ |
| View individual-level metrics | ✔ | ✔ (own team) | self only | – |
| Approve review items / PM write-backs | ✔ | ✔ | – | – |
| View audit log | ✔ | – | – | – |

### 6.2 Endpoints (`/api/v1`)

| Resource | Endpoints |
|---|---|
| Auth/session | `GET /me`, `POST /orgs/onboard` (after admin consent) |
| Org | `GET/PATCH /org`, `GET/PATCH /org/settings` (retention, consent text) |
| Users | `GET /users`, `POST /users/sync` (from Entra), `PATCH /users/{id}` (role, aliases), `POST /users/{id}/erase`, `GET /users/{id}/export` |
| Teams | `GET/POST /teams`, `GET/PATCH/DELETE /teams/{id}` |
| Members | `GET/PUT /teams/{id}/members` (bulk, with order and PM account mapping) |
| Templates | `GET /teams/{id}/templates`, `POST /teams/{id}/templates` (creates a new version), `POST /templates/{id}/activate` |
| Schedule | `GET/PUT /teams/{id}/schedule`, `POST /teams/{id}/schedule/trigger-now`, `POST /teams/{id}/schedule/pause` |
| Integrations | `GET /integrations`, `POST /integrations/{kind}/connect` (returns OAuth URL), `GET /integrations/{kind}/callback`, `DELETE /integrations/{id}`, `POST /integrations/{id}/test` |
| Sessions | `GET /teams/{id}/sessions`, `GET /sessions/{id}`, `GET /sessions/{id}/transcript`, `GET /sessions/{id}/attendance` |
| Updates/Reports | `GET /sessions/{id}/updates`, `GET /sessions/{id}/report` (HTML and PDF links), `POST /sessions/{id}/resend-digest` |
| Async check-in | `POST /async-checkins/{token}` (from Adaptive Card or web fallback) |
| Blockers | `GET /blockers?team=&status=`, `GET /blockers/{id}`, `PATCH /blockers/{id}` (status, assignee) |
| Blocker actions (public) | `GET /actions/{signed_token}` (preview), `POST /actions/{signed_token}` (acknowledge/resolve) |
| Review queue | `GET /review-items`, `POST /review-items/{id}/approve`, `POST /review-items/{id}/reject` |
| Dashboard | `GET /metrics/participation`, `/metrics/blockers`, `/metrics/carry-over`, `/metrics/mismatches`, `/metrics/dependencies`, `/metrics/themes`, `/metrics/burndown` (all `?team=&from=&to=`) |
| Audit | `GET /audit-log?entity=&actor=&from=&to=` |
| Health | `GET /healthz`, `GET /readyz` |

**Conventions**
- Cursor pagination: `?cursor=&limit=` returns `{items, next_cursor}`.
- Errors use RFC 7807 `application/problem+json`.
- `Idempotency-Key` header is honored on POSTs.
- Every mutating route calls `write_audit()`.
- `make openapi` writes `openapi.json`, and CI fails if it is stale.

---

## 7. Orchestrator (`services/orchestrator`)

### 7.1 Schedules
- Saving a schedule upserts a **Temporal Schedule** with ID `standup-{team_id}`, a cron spec, a time zone and `overlap=SKIP`. The action is `DailyStandupWorkflow(team_id, run_date)` with workflow ID `standup-{team_id}-{run_date}`, which deduplicates runs.
- The trigger fires `lead_minutes` (default 5) before the meeting so context can be preloaded.
- On first save, `CalendarAdapter.create_recurring_meeting` creates the recurring Teams meeting and stores `join_url`. Schedule edits update both the meeting and the Temporal Schedule in one API transaction plus a compensating step.

### 7.2 Workflow

```python
@workflow.defn
class DailyStandupWorkflow:
    def __init__(self) -> None:
        self.async_responses: dict[str, AsyncCheckin] = {}

    @workflow.signal
    def submit_async_checkin(self, checkin: AsyncCheckin) -> None:
        self.async_responses[checkin.user_id] = checkin

    @workflow.run
    async def run(self, team_id: str, run_date: str) -> None:
        ctx = await workflow.execute_activity(load_context, team_id, run_date, start_to_close_timeout=timedelta(minutes=2))
        if ctx.skip_today:
            await workflow.execute_activity(mark_session_skipped, ctx, ...)
            return

        session = await workflow.execute_activity(
            run_voice_standup, ctx, task_queue="voice-agents",
            start_to_close_timeout=timedelta(minutes=45), heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2, non_retryable_error_types=["MeetingNotFound"]))

        absentees = ctx.member_ids - session.attended_ids
        if absentees:
            await workflow.execute_activity(send_async_checkin, AsyncRequest(session.id, absentees), ...)
            await workflow.wait_condition(lambda: absentees <= self.async_responses.keys(),
                                          timeout=timedelta(minutes=ctx.async_window_minutes))
            await workflow.execute_activity(store_async_checkins, list(self.async_responses.values()), ...)

        updates  = await workflow.execute_activity(extract_updates, session.id, start_to_close_timeout=timedelta(minutes=5))
        resolved = await workflow.execute_activity(resolve_people_and_tickets, updates, ...)
        blockers = await workflow.execute_activity(match_and_upsert_blockers, resolved, ...)
        report   = await workflow.execute_activity(render_report, session.id, ...)
        await workflow.execute_activity(send_digest, report, ...)
        await workflow.execute_activity(send_blocker_alerts, blockers, ...)
        await workflow.execute_activity(escalate_stale_blockers, ctx.team_id, ...)
        if ctx.pm_writeback_enabled:
            await workflow.execute_activity(propose_pm_updates, resolved, ...)     # review_items, approval-gated
```

> Note: `wait_condition` raises `asyncio.TimeoutError` when the window expires. Catch it and continue with whoever replied.

### 7.3 Activities

| Activity | Queue | Timeout | Retry | Idempotency |
|---|---|---|---|---|
| `load_context` (roster, template version, tz, holidays, Jira open items) | default | 2 min | 3× exp | read-only |
| `run_voice_standup` | voice-agents | 45 min, heartbeat 30 s | 2× | session row upsert by (team_id, run_date) |
| `send_async_checkin` | default | 1 min | 5× | notifications unique key |
| `extract_updates` | intelligence | 5 min | 3× | upsert member_updates by (session, user, version) |
| `resolve_people_and_tickets` | intelligence | 2 min | 3× | deterministic |
| `match_and_upsert_blockers` | intelligence | 2 min | 3× | upsert by match result |
| `render_report` | delivery | 2 min | 3× | overwrite blob by session_id |
| `send_digest` / `send_blocker_alerts` | delivery | 2 min | 5× | **unique(session_id, recipient, type)** checked before the send |
| `propose_pm_updates` | delivery | 2 min | 3× | review_items unique per (session, ticket) |

Worker deployments: `orchestrator-worker` (workflows plus the default queue), `intelligence-worker`, `delivery-worker` and `voice-worker`, each in its own Deployment so it can scale separately.

---

## 8. Voice agent (`services/voice_agent`)

### 8.1 Pipeline

```
MeetingProvider.audio_in ─► Silero VAD ─► Deepgram STT (streaming, keywords) ─► StandupController (fast LLM)
                                                                                     │
MeetingProvider.audio_out ◄─ TTS (Azure Neural) ◄──────────────────────────────────┘
                     └─► TranscriptWriter (Redis buffer → Postgres batch insert)
```

### 8.2 Conversation state machine (per member)

```
INTRO ─► for each member in speaking_order:
           CALL_ON(name) ─► ASK(q_i) ─► LISTEN ─► JUDGE
                                          ▲          │ vague & followups < max
                                          └─ FOLLOW_UP ◄┘
                                                     │ complete
                         next question ◄─────────────┘
           ─► CONFIRM(one-line summary) ─► (yes) NEXT | (correction) AMEND ─► CONFIRM
        ─► OUTRO ─► leave()
```

- **Turn-taking is driven by the agent:** it calls on people by name, which solves speaker attribution in mixed audio. Each segment is tagged with the expected speaker and cross-checked against `participants().is_speaking` and per-speaker streams when the provider supplies them. A mismatch sets `speaker_confidence` low.
- **Time budget:** `per_person_seconds = clamp(total_budget / n_present, 60, 180)`. When the budget is spent, the agent wraps up politely ("Let's capture the rest async").
- **Absence detection:** a member not in `participants()` at their turn is skipped and retried once at the end, then marked absent.
- **Recording consent:** `set_recording_status(True)` is called and the consent line spoken before any audio is stored.
- **Jira preload:** questions are personalized with open tickets ("You had PROJ-142 in progress. Is it done?").
- **STT vocabulary:** member names and aliases, project names, ticket prefixes (`PROJ`, `PAY`) and common tech terms are compiled per team at `load_context` time.
- **Barge-in:** user speech interrupts TTS (Pipecat interruption support).
- **Latency target:** under 1.0 s p50 and under 1.5 s p95 from end of speech to the first TTS audio. Streaming LLM and TTS are used, and short prompts are cached.
- **Heartbeat:** the activity heartbeats every 10 s with `{member_index, question_index}`. On retry it resumes from the heartbeat details and rejoins the call.
- **Prompts:** versioned files in `prompts/`. The controller LLM returns JSON (`{action: ask|follow_up|confirm|next, utterance, judged_complete}`) validated by Pydantic.

### 8.3 Scaling
- A dedicated `voice` node pool (CPU-optimized, no GPU required with hosted STT/TTS).
- Each worker runs N concurrent calls (start with 4 per pod). KEDA scales on the `voice-agents` Temporal task-queue backlog, and pods are pre-warmed 10 minutes before peak schedule times.

---

## 9. Intelligence (`services/intelligence`)

### 9.1 Extraction schemas

```python
class WorkItem(BaseModel):
    summary: str
    ticket_keys: list[str] = []
    status: Literal["done", "in_progress", "planned"]
    evidence_segment_ids: list[UUID]

class Blocker(BaseModel):
    description: str
    blocked_on_raw: str | None
    blocked_on_member_id: UUID | None
    ticket_keys: list[str]
    severity: Literal["low", "medium", "high"]
    confidence: float
    evidence_segment_ids: list[UUID]

class Dependency(BaseModel):
    description: str
    on_raw: str
    on_member_id: UUID | None
    on_team_id: UUID | None
    ticket_keys: list[str]
    evidence_segment_ids: list[UUID]

class MemberUpdate(BaseModel):
    member_id: UUID
    completed: list[WorkItem]
    planned: list[WorkItem]
    blockers: list[Blocker]
    dependencies: list[Dependency]
    challenges: list[str]
    answers: dict[UUID, str]          # question_id → normalized answer
```

- The strong model is called through `instructor` with `max_retries=2`. The input is the transcript grouped by member and question, with segment IDs inline.
- **Grounding guard:** any item whose `evidence_segment_ids` is empty, or points at segments that don't exist or belong to another speaker, is dropped and logged to Langfuse.
- Ticket keys are validated with a regex plus `PMAdapter.get_ticket`. Invalid keys are stripped.

### 9.2 People resolution
1. Exact or alias match against the org roster, which earns a high score.
2. `rapidfuzz` token-set ratio on name plus department hints ("Amit from backend" boosts department=Backend).
3. The LLM picks among the top 3 candidates, given the context sentence.
4. The score is a weighted combination. **≥ 0.85** is applied automatically. **0.6–0.85** creates a `review_items(person_match)` entry and **blocks the alert** until a lead approves. **< 0.6** is left unresolved and shown in the report only.

### 9.3 Blocker matching and lifecycle
- An embedding of `description + ticket_keys` is compared to the team's open or acknowledged blockers:
  - Shared ticket key **and** cosine > 0.80 → same blocker.
  - Cosine > 0.90 with no ticket → same blocker.
  - 0.80–0.90 with no ticket → `review_items(blocker_match)`.
- A matched blocker updates `last_seen_session_id` and increments `days_open`, and **no new alert is sent**.
- States: `open → acknowledged → resolved`. A blocker that is not mentioned for 2 consecutive sessions while acknowledged gets a soft prompt, "Is this resolved?", in the next standup.
- **Escalation:** at `days_open ≥ team.escalation_days` (default 3) an escalation email goes to the lead (type `escalation`, idempotent per blocker per day).

### 9.4 Evals
- The golden set lives in `tests/evals/`: 30+ anonymized transcripts with expected `MemberUpdate` JSON, including Indian-English accents, code-switching and vague answers.
- Metrics: blocker precision and recall, person-resolution accuracy and invented-item rate (target **0**). These run in CI on prompt or model changes and are reported to Langfuse.

---

## 10. Delivery (`services/delivery`)

| Output | Implementation |
|---|---|
| Daily digest | Jinja2 email template (inline CSS, teal/blue accents to match the UI), sections: attendance, per-member update, **Blockers**, dependencies, async responses. PDF through WeasyPrint is stored in blob storage and attached |
| Blocker alert | To the blocking person, cc the reporter and lead. Includes context, linked tickets and evidence quote. Has **Acknowledge** and **Mark as resolved** buttons |
| Escalation | To the lead. Lists the blocker, days open and history |
| Async check-in | Adaptive Card through Bot Framework proactive message. The questions come from the active template version, and submit posts back to `/async-checkins/{token}`, which signals the workflow |
| PM write-back (v2) | Creates `review_items(pm_writeback)`. Only approved items call `PMAdapter.propose_update` |

- **Signed action links:** the token is `base64url(payload) + HMAC-SHA256`, with the payload `{blocker_id, action, recipient, exp}`. It expires after 7 days, is single-use per action and is resolved by the frontend's public action page.
- **Idempotency:** the `notifications` row is inserted with status `pending` under the unique key before sending. On conflict the send is skipped. After the send the row is set to `sent` and stores the provider ID.

---

## 11. Dashboard metrics

Postgres materialized views are refreshed `CONCURRENTLY` after each session's delivery, plus a nightly job:

| View | Definition |
|---|---|
| `mv_participation` | present + async / expected per team per day |
| `mv_blocker_stats` | open count, age distribution, mean and median time to resolve, raised vs resolved per week |
| `mv_carry_over` | planned items not appearing in the next session's `completed` (matched by ticket key or embedding) |
| `mv_said_vs_pm` | items said to be `done` whose ticket status ≠ Done 24 h later (Jira poll) |
| `mv_dependency_edges` | from → to (member or team), weight = count, last seen |
| `blocker_themes` | weekly k-means / HDBSCAN on blocker embeddings, labeled by LLM |
| burndown | pulled live from `PMAdapter.sprint_burndown`, cached 15 min in Redis |

Individual-level views are filtered by RBAC (§6.1). The default API response aggregates at team level.

---

## 12. Security and compliance

- **Consent:** a spoken announcement at call start, Teams recording status set, and org-configurable consent text.
- **Retention:** a nightly `retention_sweeper` deletes raw audio after `retention_days_audio` (default 0, meaning not stored) and transcripts after `retention_days_transcript`. Summaries follow org policy.
- **DPDP / GDPR:** `POST /users/{id}/erase` redacts transcript text and the speaker link, deletes updates, and writes an audit entry. A data export endpoint is available for subject access requests.
- **Isolation:** RLS on every tenant table, tenant ID checked in every activity, and separate DB roles.
- **Least privilege:** Graph permissions are limited to the list in §6.1, and application access policy is restricted to the service mailbox.
- **Secrets:** Key Vault through CSI driver. No secrets in env files committed to git, and `gitleaks` runs in pre-commit.
- **Audit:** every config change and every outbound message is recorded in an append-only table.
- **App security:** rate limits (Redis, per org), CORS restricted to the frontend origin, and a Dependabot plus `pip-audit` CI step.

---

## 13. Infra and DevOps

**Local (`infra/docker-compose.yml`):** postgres:16 + pgvector, redis, temporal + temporal-ui, minio, mailpit, and all backend services with hot reload. `make dev` boots everything, and `make seed` loads Neha's "Payments" team with fake providers.

**Kubernetes (Helm, `infra/helm/scrum-bot`):**

| Deployment | Pool | Scaling |
|---|---|---|
| api | general | HPA on CPU/RPS |
| orchestrator-worker, intelligence-worker, delivery-worker | general | KEDA on Temporal queue backlog |
| voice-worker | **voice** (tainted) | KEDA on `voice-agents` backlog + scheduled pre-warm |

**CI (GitHub Actions, `backend.yml`, path filter `backend/**`):** ruff → mypy → import-linter → pytest (unit + testcontainers integration) → alembic upgrade/downgrade check → openapi drift check → evals (on prompt changes) → build images → Trivy scan.

**CD:** staging on merge to main, prod on tag. Alembic migrations run as a pre-deploy Job.

---

## 14. Testing strategy

| Level | What | Tooling |
|---|---|---|
| Unit | Schemas, resolution scoring, blocker matching, token signing, state machine transitions | pytest |
| Integration | Repos with real Postgres (RLS cross-tenant tests), adapters with recorded HTTP (VCR) | testcontainers, respx |
| Workflow | `DailyStandupWorkflow` with time-skipping env: absentee wait, retry after voice crash, no duplicate mail | `temporalio.testing.WorkflowEnvironment` |
| Voice | Pipeline fed with recorded WAV fixtures through `FakeMeetingProvider`; asserts turn order, follow-up, confirmation and transcript tags | pytest-asyncio |
| Evals | Golden transcript extraction quality | custom harness + Langfuse |
| E2E | **Neha story**: seed → trigger-now → fake call script → assert digest in Mailpit, Amit alert, resolve link closes blocker, Thursday repeat escalates | pytest + Mailpit API |
| Load | 200 concurrent fake calls, 1,000 teams' schedules firing within 10 min | Locust + Temporal metrics |

---

## 15. Phased task breakdown

### Phase 0: Spike (1–2 weeks)
- [ ] B0.1 Recall.ai account; bot joins a Teams test meeting from a script
- [ ] B0.2 Stream bot audio in through WebSocket, then Silero VAD and Deepgram, and print the transcript
- [ ] B0.3 Pipecat: LLM reply, Azure TTS and audio out; measure latency
- [ ] B0.4 Set recording status / spoken consent; verify attendees see the notice
- [ ] B0.5 Write up findings: latency, speaker attribution quality, cost per call-hour

**Exit:** a recorded 2-way conversation with p50 latency under 1.5 s, and a go/no-go decision on Recall.ai for the MVP.

### Phase 1: MVP (6–8 weeks)
- [ ] B1.1 uv workspace, core package, settings, telemetry, docker-compose
- [ ] B1.2 Alembic baseline: all §4 tables, RLS helper and CI test
- [ ] B1.3 Entra ID auth, `/me`, onboarding, RBAC dependency
- [ ] B1.4 CRUD: teams, members, templates (versioned), schedules, integrations (Teams + mail)
- [ ] B1.5 CalendarAdapter: recurring meeting creation
- [ ] B1.6 Temporal Schedules sync; `DailyStandupWorkflow` (no async fallback yet)
- [ ] B1.7 Voice agent: state machine, consent, time budget, transcript persistence, heartbeating
- [ ] B1.8 Extraction with grounding guard; basic people resolution (exact + fuzzy)
- [ ] B1.9 Digest render (HTML + PDF) and Graph sendMail with idempotency ledger
- [ ] B1.10 Sessions, transcript and report endpoints; openapi export
- [ ] B1.11 E2E test for Neha's Tuesday (digest only)

**Exit:** one pilot team runs 5 consecutive real standups with a digest delivered each day and no duplicate emails.

### Phase 2: v1 (4–6 weeks)
- [ ] B2.1 Jira OAuth and open-items preload into context and prompts
- [ ] B2.2 STT custom vocabulary per team
- [ ] B2.3 LLM-assisted people resolution, confidence thresholds and review queue API
- [ ] B2.4 Blocker matching (pgvector), lifecycle, escalation
- [ ] B2.5 Blocker alert email and signed action links (`/actions/{token}`)
- [ ] B2.6 Async Adaptive Card check-in plus workflow signal and window
- [ ] B2.7 Eval suite in CI
- [ ] B2.8 E2E for the full Tuesday-to-Thursday story

**Exit:** wrong-person alert rate is 0 in the pilot, and repeat blockers escalate instead of re-alerting.

### Phase 3: v2 (6–8 weeks)
- [ ] B3.1 Materialized views and `/metrics/*` endpoints
- [ ] B3.2 Carry-over and said-vs-Jira jobs; blocker theme clustering
- [ ] B3.3 PM write-back proposals plus approval flow
- [ ] B3.4 Zoom / Google Meet providers through Recall.ai
- [ ] B3.5 .NET Graph media bridge (`GraphMediaBridgeProvider`) for in-tenant enterprise customers
- [ ] B3.6 Retention sweeper, erase/export endpoints
- [ ] B3.7 Load tests and KEDA tuning

**Exit:** dashboard numbers match hand-computed values on seeded data, and one enterprise tenant runs on option A.

---

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Teams media access is harder than expected | Blocks the product | Phase 0 spike first; `MeetingProvider` abstraction; Recall.ai fallback |
| STT accuracy on Indian-English names and tickets | Bad extraction | Custom vocabulary, agent-driven turn-taking, read-back confirmation, eval set with accents |
| Voice latency over 1.5 s feels robotic | User drop-off | Streaming STT/LLM/TTS, small fast model, region co-location, latency SLO alert |
| Wrong person gets a blocker email | Trust loss | Confidence thresholds, review queue, grounding guard |
| Duplicate emails on retries | Annoyance | Unique notification ledger, deterministic workflow IDs |
| Vendor cost per call-hour | Margin | Per-person time budget, usage metering per org, option A for large tenants |
| Teams perceive surveillance | Empty updates | Team-level aggregates by default, RBAC on individual views, transparent consent |
