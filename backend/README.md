# Scrum Bot — Backend

Python services that run the daily standup end to end, built to
[docs/BACKEND_IMPLEMENTATION_PLAN.md](../docs/BACKEND_IMPLEMENTATION_PLAN.md) on an **open-source stack**:

| Concern | Plan said | Implemented with (open source) |
|---|---|---|
| Workflows | Temporal | Temporal (dev server in compose, test server in pytest) |
| Data | PostgreSQL 16 + pgvector, Redis | same; **row-level security** on every tenant table |
| LLM | LiteLLM + `instructor`, hosted models | any **OpenAI-compatible** server — **Ollama** locally (`qwen2.5:7b` extraction, `llama3.2:3b` live turns), vLLM / llama.cpp in prod; JSON-schema constrained output validated by Pydantic with retries |
| Embeddings | hosted | **nomic-embed-text** on Ollama (768-d, pgvector HNSW); deterministic hashing embedder for CI |
| Meeting | Recall.ai + Teams | **LiveKit** (WebRTC SFU) — one audio track per participant, so speaker attribution is exact |
| STT / TTS / VAD | Deepgram / Azure / Silero | **faster-whisper** (vocabulary prompt + name snapping) / **Piper** / energy VAD + Whisper's Silero filter |
| Mail | Graph `sendMail` | **SMTP** (Mailpit locally) with an idempotent notification ledger |
| Async check-in | Teams Adaptive Card | signed **email link** to the web form (`/a/<token>?type=checkin`) that signals the workflow |
| Calendar | Graph online meetings | LiveKit room + **iCalendar (RFC 5545) invite** by email |
| Identity | Entra ID | any **OIDC** provider (Keycloak, Authentik, Zitadel — or Entra); `dev` persona mode for local work |
| Secrets | Key Vault | AES-256-GCM **envelope encryption**; KEK from env / OpenBao-Vault via CSI |
| Blobs | Azure Blob / S3 | local disk or any S3 API (**SeaweedFS** in compose) |
| PDF | WeasyPrint | WeasyPrint (skipped gracefully where Pango is missing) |
| PM tool | Jira | Jira Cloud REST/Agile (OAuth 3LO) + an in-memory demo catalog |

## Quick start

```bash
make dev          # Postgres+pgvector :55432, Redis, Temporal :7233 (UI :8233), Mailpit :8025, SeaweedFS
make seed         # migrations + Neha's Payments story week (frontend parity data)
ollama pull qwen2.5:7b-instruct-q4_K_M && ollama pull llama3.2:3b && ollama pull nomic-embed-text
make api          # http://localhost:8800/docs
make worker       # all Temporal workers in one process
```

Point the frontend at it: `NEXT_PUBLIC_APP_MODE=api NEXT_PUBLIC_API_URL=http://localhost:8800/api/v1 npm run dev`,
sign in as a persona, then **Teams → Payments → Schedule → Run now**: the scripted demo meeting runs, the open-source
LLM extracts updates, blockers are matched/escalated and the digest + alerts land in Mailpit (http://localhost:8025).
The sign-in page lists fresh signed email links (blocker action, expired link, async check-in) from `/dev/demo-links`.

No Make on Windows? Each target is one command — see the [Makefile](Makefile).

### Real voice

```bash
make voices                                    # faster-whisper, Piper, LiveKit SDK + the en_US-lessac-medium voice
docker compose -f ../infra/docker-compose.yml --profile voice up -d livekit
SCRUM_MEETING_PROVIDER=livekit SCRUM_STT_PROVIDER=whisper SCRUM_TTS_PROVIDER=piper make worker
```
People join `SCRUM_MEETING_JOIN_URL_TEMPLATE` (e.g. the open-source LiveKit Meet app) with their email as identity.

## Layout

```
packages/core/scrum_core          settings, db (session_for → SET app.org_id), models, schemas, security, audit, cron
packages/adapters/scrum_adapters  meeting/ (livekit, fake) · stt · tts · llm · mail · pm · calendar · blob · registry
services/api/scrum_api            FastAPI: 46 routes, RBAC, RFC 7807, Idempotency-Key, rate limits, OpenAPI
services/orchestrator             DailyStandupWorkflow (+ resend, alerts, retention sweeper), load_context
services/voice_agent/scrum_voice  controller (state machine), pipeline (VAD→STT→judge→TTS), transcript writer
services/intelligence             extraction (LLM + heuristic), grounding guard, people resolution, blocker matching
services/delivery                 Jinja2 emails, PDF, notification ledger, alerts, escalation, async check-in
services/runtime/scrum_runtime    composition root: `scrum-worker orchestrator|voice|intelligence|delivery|all`
migrations/                       Alembic baseline incl. RLS policies, grants, auth lookup function
scripts/                          seed.py, export_openapi.py
tests/                            unit · integration (RLS, API) · workflows (Temporal E2E) · voice · evals
```
Layering is enforced by **import-linter**: services → adapters → core, and services never import each other.

## Quality gates

```bash
make lint typecheck   # ruff, ruff format, import-linter, mypy (strict on packages/)
make test             # 47 tests: unit, RLS, API, Temporal story E2E, controller, heuristic evals
make test-all         # + real Piper→Whisper speech and the Ollama extraction evals
make openapi          # writes openapi.json → frontend `npm run gen:api` (+ compile-time contract check)
```

Current open-source LLM eval (qwen2.5:7b, 8 golden transcripts incl. Indian-English and Hinglish):
blocker precision 1.00 / recall 1.00, blocked-on 3/4, done-ticket recall 7/8, invented items reaching output: 0.

## Notes and known gaps
- **Metrics** are computed live over RLS-protected tables rather than materialized views (plain MVs bypass RLS);
  fine at standup volumes, revisit with per-org MVs if dashboards slow down.
- **LiveKit provider** is written against the LiveKit Python SDK but has only been exercised through the shared PCM
  path (Piper → VAD → Whisper → controller); run it against a LiveKit server before a pilot.
- **Barge-in** isn't implemented: the pipeline is half-duplex because the agent drives turn-taking.
- **Directory sync** (`POST /users/sync`) reports the roster; users are JIT-provisioned at first OIDC sign-in.
- **Azure DevOps**, Zoom/Meet and the .NET Graph media bridge remain v2 items.
- The frontend `live` mode still uses MSAL (Entra); a Keycloak front-end login needs a generic OIDC client.
