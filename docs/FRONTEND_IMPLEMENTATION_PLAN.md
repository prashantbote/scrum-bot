# Scrum Bot: Frontend Implementation Plan

> Scope: everything under `frontend/`. Companion docs: [README](README.md) · [Backend plan](BACKEND_IMPLEMENTATION_PLAN.md)
> Theme: **Enterprise Minimal**, with a light grey background, teal and blue accents, compact information cards and simple typography.

---

## 1. Goals and scope

The frontend is a **single Next.js web app** with four areas:

1. **Admin console:** org setup, integrations, users and roles, teams, question templates, schedules, retention settings.
2. **Standup records:** session list, transcript with speaker and question tags, daily report, async responses.
3. **Blocker operations:** blockers board, review queue (low-confidence matches, PM write-back approvals) and a **public action page** for one-click acknowledge or resolve links from email.
4. **Dashboard:** team health (participation, blocker KPIs, time to resolve, carry-over, said-vs-Jira mismatches, dependency map, recurring themes, burndown).

**Non-goals:** live call UI (the call happens in Teams), mobile native apps, a custom email editor.

---

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Framework | Next.js (App Router), React, TypeScript (strict) | SSR for fast first paint, route groups for auth/public |
| Styling | Tailwind CSS with CSS-variable design tokens | Theme lives in one place, no hard-coded colors |
| Components | shadcn/ui (Radix primitives), restyled to Enterprise Minimal | Accessible, owned source, easy to compact |
| Icons | lucide-react (16 px, 1.5 stroke) | Thin, neutral |
| Data fetching | TanStack Query + generated client (`openapi-typescript` + `openapi-fetch`) | Typed contract with backend, caching, optimistic updates |
| Forms | React Hook Form + Zod | Schema validation mirrors backend Pydantic models |
| Tables | TanStack Table | Dense, sortable, virtualized |
| Charts | Recharts | Bars, lines, sparklines, donut |
| Graph | React Flow | Dependency map |
| Auth | MSAL React (`@azure/msal-react`), Entra ID | Customers already use Microsoft 365 |
| Dates | date-fns + date-fns-tz | Team time zones |
| Testing | Vitest + Testing Library, MSW, Playwright, Storybook + axe | Unit, mocked API, E2E, visual and a11y |
| Quality | ESLint, Prettier, `tsc --noEmit`, size-limit | CI gates |

---

## 3. Folder structure

```
frontend/
├── package.json
├── next.config.mjs
├── tailwind.config.ts              # maps Tailwind theme → CSS variables
├── src/
│   ├── app/
│   │   ├── layout.tsx              # fonts, providers (MSAL, Query, Theme)
│   │   ├── (public)/
│   │   │   ├── login/page.tsx
│   │   │   └── a/[token]/page.tsx  # blocker action page (no login required)
│   │   └── (app)/                  # authenticated shell (top bar + side nav)
│   │       ├── layout.tsx
│   │       ├── dashboard/page.tsx
│   │       ├── onboarding/[step]/page.tsx
│   │       ├── teams/page.tsx
│   │       ├── teams/[teamId]/{page,members,questions,schedule}/...
│   │       ├── standups/page.tsx
│   │       ├── standups/[sessionId]/{page,transcript,report}/...
│   │       ├── blockers/page.tsx
│   │       ├── blockers/[blockerId]/page.tsx
│   │       ├── review/page.tsx
│   │       ├── integrations/page.tsx
│   │       ├── settings/{org,users,retention}/page.tsx
│   │       └── audit/page.tsx
│   ├── components/
│   │   ├── ui/                     # shadcn primitives (button, input, select, dialog, tabs, badge, table…)
│   │   ├── layout/                 # AppShell, TopBar, SideNav, PageHeader, Section
│   │   ├── cards/                  # KpiCard, InfoCard, MemberUpdateCard, BlockerCard, StatusCard
│   │   ├── charts/                 # Sparkline, TrendLine, StackedBar, Donut, DependencyGraph
│   │   ├── forms/                  # QuestionListEditor, CronBuilder, TimezoneSelect, MemberPicker
│   │   └── feedback/               # EmptyState, ErrorState, Skeletons, Toasts
│   ├── features/                   # feature hooks + composed views (teams, standups, blockers, metrics…)
│   ├── lib/
│   │   ├── api/                    # schema.d.ts (generated), client.ts, queryKeys.ts
│   │   ├── auth/                   # msalConfig.ts, useAccessToken.ts
│   │   ├── rbac/                   # roles.ts, <Can/>, route guard
│   │   └── format/                 # dates, durations, percentages
│   └── styles/
│       ├── tokens.css              # design tokens (single source of truth)
│       └── globals.css
├── tests/                          # vitest unit/component
├── e2e/                            # playwright specs (Neha story)
├── mocks/                          # MSW handlers + fixtures from openapi examples
└── .storybook/
```

---

## 4. Enterprise Minimal design system

### 4.1 Principles
1. **Quiet canvas, loud data.** The UI is grey and white, and only meaningful states and actions use color.
2. **Teal = primary action / positive health. Blue = information / links / navigation focus.**
3. **Compact by default.** Show a lot of information without clutter. Every card answers one question.
4. **Flat.** 1 px borders, almost no shadow, no gradients.

### 4.2 Color tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F4F6F8` | App background (light grey) |
| `--surface` | `#FFFFFF` | Cards, tables, panels |
| `--surface-muted` | `#F9FAFB` | Table header, hovered rows, input bg |
| `--border` | `#E2E6EA` | Card and table borders, dividers |
| `--border-strong` | `#CBD2D9` | Input borders, focused sections |
| `--text` | `#1F2933` | Primary text |
| `--text-muted` | `#5F6B7A` | Labels, secondary text (≥ 4.5:1 on `--bg`) |
| `--text-subtle` | `#8A94A3` | Placeholder, disabled (non-essential only) |
| `--teal-600` | `#0D7C72` | **Primary** buttons, active nav, positive deltas (5.1:1 on white) |
| `--teal-700` | `#0A655D` | Primary hover/pressed |
| `--teal-400` | `#14B8A6` | Chart series, progress fill (decorative only, never body text) |
| `--teal-50` | `#E6F4F2` | Selected row, active nav background, success tint |
| `--blue-600` | `#2563EB` | Links, focus ring, info badges, secondary chart series (5.2:1 on white) |
| `--blue-700` | `#1D4ED8` | Link hover |
| `--blue-50` | `#EAF1FE` | Info tint, "acknowledged" badge background |
| `--warning` | `#B45309` on `#FEF3E2` | Aging blockers (2+ days), mismatches |
| `--danger` | `#B42318` on `#FDECEA` | High severity, escalated, errors |
| `--success` | uses teal-600 on teal-50 | Resolved, present |

**Chart palette (ordered):** `#0D7C72`, `#2563EB`, `#14B8A6`, `#60A5FA`, `#94A3B8`, `#0A655D`. Status colors are never reused as series colors.

**Status → badge mapping**

| State | Badge |
|---|---|
| Blocker `open` | danger tint |
| Blocker `acknowledged` | blue tint |
| Blocker `resolved` | teal tint |
| `needs_review` | warning tint |
| Attendance `present` / `async` / `absent` | teal / blue / neutral grey |

### 4.3 Typography
- **Font:** Inter (via `next/font`, self-hosted) with fallback `system-ui, -apple-system, "Segoe UI", sans-serif`. Use `JetBrains Mono` or `ui-monospace` only for ticket keys (e.g. `PROJ-142`).
- **Weights:** 400 (body), 500 (labels, buttons), 600 (headings, KPI values). Nothing heavier.
- **Scale:**

| Role | Size / line-height | Weight |
|---|---|---|
| Page title | 20 / 28 | 600 |
| Section title | 16 / 24 | 600 |
| Card title / label | 12 / 16, uppercase tracking 0.04em | 500, `--text-muted` |
| Body | 14 / 20 | 400 |
| Dense table / meta | 13 / 18 | 400 |
| Caption | 12 / 16 | 400 |
| KPI value | 24 / 32, `font-variant-numeric: tabular-nums` | 600 |

### 4.4 Spacing, shape, elevation
- 4 px base grid. Common gaps are 8, 12, 16 and 24. Page padding is 24 px on desktop and 16 px on mobile.
- Radius: 6 px on cards and dialogs, 4 px on inputs, buttons and badges, 999 px only on avatars.
- Border: 1 px `--border` everywhere. Shadow `0 1px 2px rgb(16 24 40 / 0.04)` on cards only, plus a slightly stronger one on popovers.
- Control height is 32 px (compact). Table rows are 36 px, with 44 px touch targets on mobile.

### 4.5 Compact card specs

| Card | Anatomy | Size |
|---|---|---|
| **KpiCard** | Label (12 px muted) · value (24 px tabular) · delta chip (▲ teal / ▼ danger) · optional 24 px sparkline | ~96 px tall, min 200 px wide |
| **InfoCard** | Title row (label + optional action icon) · body (list or short text) · footer link (blue) | Padding 12–16 px |
| **MemberUpdateCard** | Avatar + name + attendance badge · Done / Today / Blockers mini-lists · ticket chips (mono) · evidence link "▶ 10:32" | Collapsible, 3 lines per section, then "more" |
| **BlockerCard** | Severity dot · description (2 lines) · reporter → blocked-on · ticket chips · age badge · actions | 1-line compact mode on board |
| **StatusCard** | Integration logo + name · status dot (teal ok / warning / danger) · last checked · "Test" button | Fixed 72 px height |

### 4.6 Layout
- **Top bar (56 px):** product mark, org name, team switcher, global search (teams, members, tickets), user menu.
- **Side nav (220 px, collapsible to 56 px icons):** Dashboard, Standups, Blockers, Review (count badge), Teams, Integrations, Settings, Audit. The active item uses `--teal-50` background, `--teal-600` text and a 2 px left bar.
- **Content:** 12-column grid, max width 1440 px. KPI rows are 4 cards on desktop, 2 on tablet and 1 on mobile.
- **Breakpoints:** `sm 640`, `md 768`, `lg 1024`, `xl 1280`. The nav collapses into a drawer below `lg`.

### 4.7 Tokens as code

```css
/* src/styles/tokens.css */
:root {
  --bg: #F4F6F8; --surface: #FFFFFF; --surface-muted: #F9FAFB;
  --border: #E2E6EA; --border-strong: #CBD2D9;
  --text: #1F2933; --text-muted: #5F6B7A; --text-subtle: #8A94A3;
  --teal-50: #E6F4F2; --teal-400: #14B8A6; --teal-600: #0D7C72; --teal-700: #0A655D;
  --blue-50: #EAF1FE; --blue-600: #2563EB; --blue-700: #1D4ED8;
  --warning: #B45309; --warning-bg: #FEF3E2;
  --danger: #B42318;  --danger-bg: #FDECEA;
  --radius-card: 6px; --radius-control: 4px;
  --shadow-card: 0 1px 2px rgb(16 24 40 / 0.04);
  --focus-ring: 0 0 0 2px var(--surface), 0 0 0 4px var(--blue-600);
}
body { background: var(--bg); color: var(--text); font-size: 14px; line-height: 20px; }
```

```ts
// tailwind.config.ts (excerpt)
theme: {
  extend: {
    colors: {
      bg: "var(--bg)", surface: { DEFAULT: "var(--surface)", muted: "var(--surface-muted)" },
      border: { DEFAULT: "var(--border)", strong: "var(--border-strong)" },
      fg: { DEFAULT: "var(--text)", muted: "var(--text-muted)", subtle: "var(--text-subtle)" },
      teal: { 50: "var(--teal-50)", 400: "var(--teal-400)", 600: "var(--teal-600)", 700: "var(--teal-700)" },
      blue: { 50: "var(--blue-50)", 600: "var(--blue-600)", 700: "var(--blue-700)" },
      warning: { DEFAULT: "var(--warning)", bg: "var(--warning-bg)" },
      danger:  { DEFAULT: "var(--danger)",  bg: "var(--danger-bg)" },
    },
    borderRadius: { card: "var(--radius-card)", control: "var(--radius-control)" },
    boxShadow: { card: "var(--shadow-card)" },
    fontFamily: { sans: ["var(--font-inter)", "system-ui", "sans-serif"], mono: ["ui-monospace", "monospace"] },
  },
}
```

An ESLint rule (`no-restricted-syntax` on hex literals in `.tsx`) plus Stylelint blocks hard-coded colors outside `tokens.css`.

### 4.8 Accessibility
- WCAG 2.2 AA. All text and background pairs above were checked to be at least 4.5:1. `--teal-400` and `--text-subtle` are never used for essential text.
- Visible focus ring (blue) on every interactive element. Full keyboard navigation, including the question editor, which supports reordering with keys as well as drag.
- Status is never shown by color alone: badges always carry text and severity dots have an `aria-label`.
- Charts have a table fallback ("View as table") and descriptive `aria-label`s.
- `prefers-reduced-motion` respected. Animations are 150 ms or shorter.

---

## 5. Screen inventory

| # | Screen | Route | Roles | Key components | API endpoints |
|---|---|---|---|---|---|
| 1 | Login | `/login` | public | SSO button, tenant consent notice | MSAL → `GET /me` |
| 2 | Onboarding wizard | `/onboarding/[step]` | org_admin | Stepper: Org → Integrations → Team → Members → Questions → Schedule → Review | `POST /orgs/onboard`, `/integrations/*`, `POST /teams`, `PUT /teams/{id}/members`, `POST /teams/{id}/templates`, `PUT /teams/{id}/schedule` |
| 3 | Dashboard | `/dashboard` | all (scoped) | Filters (team, range), KPI row, participation trend, blocker age chart, TTR, carry-over, mismatches table, dependency graph, themes, burndown | `GET /metrics/*` |
| 4 | Teams list | `/teams` | admin, lead | Dense table: team, lead, members, next standup, status | `GET /teams` |
| 5 | Team detail | `/teams/[id]` | admin, lead | Overview InfoCards (schedule, template version, integrations), recent sessions | `GET /teams/{id}`, `GET /teams/{id}/sessions` |
| 6 | Members | `/teams/[id]/members` | admin, lead | MemberPicker (Entra search), speaking order (drag), Jira account mapping, aliases | `GET /users`, `PUT /teams/{id}/members`, `PATCH /users/{id}` |
| 7 | Question template editor | `/teams/[id]/questions` | admin, lead | QuestionListEditor: text, type, required, follow-up policy, max follow-ups; version history drawer; "Preview as agent" | `GET/POST /teams/{id}/templates`, `POST /templates/{id}/activate` |
| 8 | Schedule editor | `/teams/[id]/schedule` | admin, lead | Days of week chips, time, TimezoneSelect, holiday calendar, skip dates, async window, "Next 5 runs" preview, Pause / Run now | `GET/PUT /teams/{id}/schedule`, `POST …/trigger-now`, `POST …/pause` |
| 9 | Integrations | `/integrations` | org_admin | StatusCards for Teams, Jira, Mail; connect (OAuth redirect), test, disconnect | `GET /integrations`, `POST /integrations/{kind}/connect`, `POST /integrations/{id}/test`, `DELETE /integrations/{id}` |
| 10 | Standups list | `/standups` | all | Table: date, team, status, attendance %, blockers, duration | `GET /teams/{id}/sessions` |
| 11 | Session detail | `/standups/[id]` | all (scoped) | Attendance strip, MemberUpdateCards grid, blockers section, async responses | `GET /sessions/{id}`, `/attendance`, `/updates` |
| 12 | Transcript | `/standups/[id]/transcript` | lead, admin, self | Segments with speaker, timestamp and question tag; filter by member/question; highlights for evidence segments (deep link `#seg-…`) | `GET /sessions/{id}/transcript` |
| 13 | Report | `/standups/[id]/report` | all (scoped) | Rendered digest preview, download PDF, resend | `GET /sessions/{id}/report`, `POST …/resend-digest` |
| 14 | Blockers board | `/blockers` | all (scoped) | Columns Open / Acknowledged / Resolved (or table toggle); filters (team, severity, age ≥ N); BlockerCards; escalation badge | `GET /blockers`, `PATCH /blockers/{id}` |
| 15 | Blocker detail | `/blockers/[id]` | all (scoped) | Timeline (first seen, mentions, ack, escalation, resolved), evidence quotes linked to transcript, tickets, actions | `GET /blockers/{id}` |
| 16 | Review queue | `/review` | admin, lead | Tabs: Person matches / Blocker matches / PM write-backs; each row shows raw phrase, candidates with confidence bar, evidence quote, Approve / Choose other / Reject | `GET /review-items`, `POST …/approve`, `POST …/reject` |
| 17 | **Public blocker action** | `/a/[token]` | public (signed link) | Minimal centered card: blocker summary, ticket, reporter; buttons **Acknowledge** (blue) / **Mark as resolved** (teal); success state; expired-link state | `GET/POST /actions/{token}` |
| 18 | Async check-in (web fallback) | `/a/[token]?type=checkin` | public (signed) | Same questions as the Adaptive Card, compact form | `POST /async-checkins/{token}` |
| 19 | Users and roles | `/settings/users` | org_admin | Table with role select, sync from Entra | `GET /users`, `POST /users/sync`, `PATCH /users/{id}` |
| 20 | Org settings | `/settings/org`, `/settings/retention` | org_admin | Consent text, audio and transcript retention, escalation days, data erase requests | `GET/PATCH /org/settings`, `POST /users/{id}/erase` |
| 21 | Audit log | `/audit` | org_admin | Filterable table, JSON diff drawer | `GET /audit-log` |

### 5.1 Dashboard composition (Neha's Friday view)

```
┌ Filters: [Team: Payments ▾] [This week ▾] ────────────────────────────────────────────┐
├──────────────┬──────────────┬──────────────┬──────────────┐
│ Attendance   │ Blockers     │ Avg time to  │ Said vs Jira │   ← KpiCards (96 px)
│ 96%  ▲2      │ 4 raised · 3 │ resolve      │ mismatches   │
│ ▁▃▅▇▇        │ resolved     │ 1.2 d ▼0.4   │ 1            │
├──────────────┴──────────────┼──────────────┴──────────────┤
│ Participation trend (line)  │ Open blockers by age (bars)  │   ← InfoCards w/ charts
├─────────────────────────────┼──────────────────────────────┤
│ Dependency map (React Flow) │ Mismatches table             │
│ Payments ──▶ Backend (×5)   │ Sneha · PROJ-155 · said done │
├─────────────────────────────┴──────────────────────────────┤
│ Recurring blocker themes (chips + counts) │ Sprint burndown │
└────────────────────────────────────────────────────────────┘
```

---

## 6. State, data and auth

- **API client:** `lib/api/client.ts` wraps `openapi-fetch` with base URL, the bearer token from MSAL (`acquireTokenSilent`, with redirect fallback), RFC 7807 error parsing into a typed `ApiError`, and an `Idempotency-Key` on mutating calls.
- **Query keys:** a centralized factory, e.g. `qk.sessions.detail(id)` or `qk.metrics.blockers({team, from, to})`. Metrics `staleTime` is 5 min and config data is 30 s.
- **Optimistic updates:** blocker status changes and review approvals, rolled back on error with a toast.
- **Server vs client components:** layout and static shells are server components. Data views are client components using TanStack Query, since the token is client-side through MSAL. The public action page is a server component that validates the token through the API.
- **RBAC:** `GET /me` returns role and scoped team IDs. The `<Can action="team.configure" team={id}>` component and route middleware redirect unauthorized users to `/dashboard`. **Individual-level metrics are hidden for Viewer, and Members see only themselves.**
- **Forms:** Zod schemas generated or hand-mirrored from OpenAPI components. A dirty-state guard warns on navigation, and server validation errors are mapped to fields.
- **Time zones:** display in the team's time zone with the viewer's local time in a tooltip. The "Next 5 runs" preview is computed client-side and confirmed by the API.

---

## 7. Dashboard UX principles

- **Team health, not ranking.** No leaderboards and no per-person sorting by "productivity". Aggregates come first, and individual drill-downs need a role and are labeled for coaching use.
- Every metric has an info tooltip that explains how it is calculated (e.g. "Carry-over: items planned yesterday not reported done today").
- Every number links to its evidence (the sessions or blockers behind it).
- Empty states teach ("No blockers this week. Nice.") instead of showing blank charts.

---

## 8. Testing

| Level | Scope | Tools |
|---|---|---|
| Unit | Formatters, RBAC rules, cron preview, Zod schemas | Vitest |
| Component | Cards, editors, tables in every state (loading, empty, error, dense data) | Testing Library + MSW |
| Visual / a11y | Storybook stories for all `components/*`; axe checks in CI; Chromatic or Playwright screenshots | Storybook, axe-core |
| E2E | **Neha story:** login (mocked MSAL) → onboarding → configure questions and schedule → open Tuesday session → review transcript → blockers board → public action page resolves Amit's blocker → Friday dashboard shows expected KPIs | Playwright + MSW (CI); against staging API nightly |
| Contract | Generated client compiles against latest `openapi.json`; MSW handlers typed from the same schema | `tsc`, openapi-typescript |

---

## 9. Phased task breakdown

### Phase 0: Foundation (parallel to backend spike, 1–2 weeks)
- [ ] F0.1 Scaffold Next.js + TS strict + Tailwind + ESLint/Prettier + Vitest + Playwright
- [ ] F0.2 `tokens.css`, Tailwind mapping, Inter font, restyle shadcn primitives (button, input, select, badge, table, tabs, dialog, toast)
- [ ] F0.3 AppShell (TopBar, SideNav, PageHeader), responsive behavior
- [ ] F0.4 Card library: KpiCard, InfoCard, StatusCard, skeletons, empty and error states, plus Storybook
- [ ] F0.5 MSAL config and protected route group; API client and MSW mocks pipeline

**Exit:** the Storybook design system is reviewed and approved, and the shell renders behind SSO.

### Phase 1: MVP (6–8 weeks)
- [ ] F1.1 Login and `/me` bootstrap, RBAC `<Can/>`
- [ ] F1.2 Onboarding wizard (org, Teams and mail integration, team, members, questions, schedule)
- [ ] F1.3 Teams list and detail, members editor (ordering, aliases)
- [ ] F1.4 Question template editor with versioning and preview
- [ ] F1.5 Schedule editor (CronBuilder, timezone, holidays, next-runs preview, run now)
- [ ] F1.6 Standups list, session detail (MemberUpdateCards), transcript view, report view and PDF download
- [ ] F1.7 E2E: setup and Tuesday session review

**Exit:** Neha can configure a team end to end and read Tuesday's report without help.

### Phase 2: v1 (4–6 weeks)
- [ ] F2.1 Integrations page (Jira connect, status, test)
- [ ] F2.2 Blockers board and detail timeline, evidence deep links
- [ ] F2.3 Review queue (person and blocker matches) with confidence bars
- [ ] F2.4 Public action page `/a/[token]` (acknowledge/resolve, expired, already-done states)
- [ ] F2.5 Async check-in web fallback
- [ ] F2.6 E2E: Amit resolves through the link; Priya's escalation shows on the board

**Exit:** the full blocker loop is usable from email to board, and the action page works on mobile.

### Phase 3: v2 (6–8 weeks)
- [ ] F3.1 Dashboard: KPI row, participation, blocker age and TTR, carry-over
- [ ] F3.2 Dependency graph (React Flow), mismatches table, themes, burndown
- [ ] F3.3 PM write-back approvals tab
- [ ] F3.4 Users and roles, org settings (retention, consent, erase), audit log
- [ ] F3.5 Meeting provider settings (Zoom/Meet, enterprise bridge)
- [ ] F3.6 Performance pass and a11y audit

**Exit:** Neha's Friday dashboard matches the seeded-data expectations, and the axe audit has 0 serious issues.

---

## 10. Performance and quality budgets

| Metric | Budget |
|---|---|
| LCP (dashboard, desktop, cached auth) | < 2.5 s |
| INP | < 200 ms |
| Initial JS per route | < 200 KB gzipped (charts and React Flow lazy-loaded) |
| Table rendering | Virtualize above 200 rows |
| Lighthouse a11y | ≥ 95 |

**CI (`frontend.yml`, path filter `frontend/**`):** install → `gen:api` (fails if the schema changed but the client was not regenerated) → lint → typecheck → unit and component tests → build → size-limit → Playwright (MSW) → Storybook build and axe.

**Deployment:** Docker image (`next start`, standalone output) on the same Kubernetes cluster behind the ingress, or Azure Static Web Apps / Vercel for the UI with the API on its own domain. Environment config: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_ENTRA_CLIENT_ID` and `NEXT_PUBLIC_ENTRA_AUTHORITY`.
