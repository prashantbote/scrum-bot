# Scrum Bot: Implementation Plan Index

Scrum Bot is an AI voice agent that runs a team's daily standup. It joins the team's Teams meeting at a set time and asks each member the team's configured questions. From the answers it pulls out updates, blockers and dependencies, then emails a digest to leads and an alert to whoever is blocking someone. It tracks each blocker until it is resolved, and a dashboard shows team health over time.

| Document | Scope |
|---|---|
| [BACKEND_IMPLEMENTATION_PLAN.md](BACKEND_IMPLEMENTATION_PLAN.md) | Python services, data model, Temporal workflows, voice agent, intelligence, delivery, infra |
| [FRONTEND_IMPLEMENTATION_PLAN.md](FRONTEND_IMPLEMENTATION_PLAN.md) | Next.js admin console and dashboard, plus the *Enterprise Minimal* design system |

---

## 1. Acceptance narrative

The whole system is built to make this week happen for **Neha, the lead of the "Payments" team**:

| When | What happens | Owner |
|---|---|---|
| Mon 10:00 | Neha signs in with Microsoft, creates the team, adds 5 members, connects Jira and Teams, sets the standup to 10:30 Mon–Fri and writes 3 questions | Frontend: onboarding wizard → Backend: API |
| Mon (on save) | A recurring Teams meeting is created and a Temporal Schedule is registered | Backend: orchestrator |
| Tue 10:25 | The workflow wakes, checks for holidays and preloads each member's open Jira tickets | Backend: orchestrator + adapters |
| Tue 10:30 | The bot joins, announces the recording, calls on each person by name, asks follow-ups and reads back a summary | Backend: voice agent |
| Tue 10:43 | Absent Karan gets an Adaptive Card and answers at 11:15 | Backend: delivery + workflow signal |
| Tue 10:45 | Extraction runs, "Amit" is resolved to Amit Sharma (95% confidence → automatic) | Backend: intelligence |
| Tue 10:50 | Digest goes to leads, blocker alert goes to Amit, Amit clicks **Mark as resolved** | Backend: delivery → Frontend: action page |
| Thu | Priya's repeat blocker is matched to the existing one and escalated after 3 days | Backend: intelligence |
| Fri | Neha sees attendance, blocker KPIs, the dependency map and said-vs-Jira mismatches | Frontend: dashboard |

This narrative is also the end-to-end acceptance test (see each plan's testing section).

---

## 2. Architecture: three planes

```
                ┌─────────────────────────────── CONTROL PLANE ───────────────────────────────┐
  Browser ────► │  frontend/ (Next.js)  ──REST/OpenAPI──►  backend/services/api (FastAPI)     │
                │                                            │  Postgres 16 + pgvector (RLS)   │
                └────────────────────────────────────────────┼─────────────────────────────────┘
                                                             │ create/update Temporal Schedules
                ┌─────────────────────────────── WORKFLOW PLANE ──────────────────────────────┐
                │  Temporal  ──►  orchestrator worker (DailyStandupWorkflow)                  │
                │                 ├─ intelligence activities (extract, resolve, match)        │
                │                 └─ delivery activities (render, mail, alerts, PM sync)      │
                └──────────────────────────────┬──────────────────────────────────────────────┘
                                               │ task_queue="voice-agents"
                ┌─────────────────────────────── MEDIA PLANE ─────────────────────────────────┐
                │  voice_agent workers (Pipecat) ◄──WebSocket audio──► MeetingProvider        │
                │  own node pool, scaled by concurrent calls        (Recall.ai → .NET bridge) │
                └─────────────────────────────────────────────────────────────────────────────┘
```

- **Control plane:** stateless request/response CRUD. Cheap to run and scales horizontally.
- **Workflow plane:** each daily standup is a durable workflow. It survives crashes, retries failed steps, enforces timeouts and handles waits like "give absentees 2 hours". It never sends duplicate mail.
- **Media plane:** long-lived, stateful and latency-sensitive. It is never mixed into the API or a basic task queue.

---

## 3. Repository layout

Backend and frontend are separate top-level projects. Each has its own toolchain, CI job and container image.

```
scrum_bot/
├── backend/        # Python uv workspace: services/ + packages/ + migrations/
├── frontend/       # Next.js + TypeScript app (admin console + dashboard)
├── infra/          # docker-compose (local), Helm charts, Terraform
└── docs/           # this folder
```

### Contract between backend and frontend

1. The backend is the source of truth for the API. CI exports `backend/openapi.json` from FastAPI on every build.
2. The frontend generates its typed client with `openapi-typescript` (`npm run gen:api`), and that client is the only way it calls the backend.
3. A change that breaks the contract fails CI through an `oasdiff` breaking-change check. Breaking changes need a new `/v2` route or a PR that updates both sides.
4. Authentication: the frontend gets an Entra ID access token through MSAL and sends it as `Authorization: Bearer`. The backend validates it and resolves `org_id` and role.

---

## 4. Unified delivery timeline

| Phase | Duration | Backend | Frontend | Exit criteria |
|---|---|---|---|---|
| **0. Spike** | 1–2 wks | Bot joins a Teams meeting through Recall.ai, hears audio and speaks back through Pipecat | Repo scaffold, design tokens, app shell, Storybook | A recorded demo of a 2-way voice exchange in a real Teams meeting with latency under 1.5 s |
| **1. MVP** | 6–8 wks | Users/config API, RLS, Temporal schedule, voice standup for one team, extraction, email digest | SSO login, onboarding wizard, question template and schedule editors, session list and transcript view, report view | Neha's Tuesday runs end to end for one real team and the digest arrives |
| **2. v1** | 4–6 wks | Blocker alerts and lifecycle, escalation, Jira preload, async Adaptive Card fallback, review queue | Blockers board, review queue, public blocker action page, integrations page | Amit's alert and resolve loop works; Priya's repeat blocker is escalated, not re-sent |
| **3. v2** | 6–8 wks | Dashboard materialized views, PM write-back with approval, Zoom/Meet providers, .NET media bridge | Full dashboard (KPIs, dependency graph, mismatches, themes, burndown), approvals UI, provider settings | Neha's Friday dashboard is accurate against seeded data, and an enterprise tenant runs on option A |

---

## 5. Definition of Done (every feature)

- [ ] Unit and integration tests pass. Coverage of new code is at least 80% (backend) or 70% (frontend).
- [ ] Every new table has `org_id` and an RLS policy, and a cross-tenant leak test exists.
- [ ] Config changes and outbound messages write to `audit_log`.
- [ ] OpenTelemetry spans and structured logs are added. LLM calls are traced in Langfuse.
- [ ] The OpenAPI contract is regenerated and the frontend client is updated.
- [ ] UI follows the Enterprise Minimal tokens. No hard-coded colors.
- [ ] Docs are updated (this folder plus service READMEs).
