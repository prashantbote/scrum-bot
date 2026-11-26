# Scrum Bot — Frontend

Next.js admin console and team-health dashboard for Scrum Bot, built to
[docs/FRONTEND_IMPLEMENTATION_PLAN.md](../docs/FRONTEND_IMPLEMENTATION_PLAN.md) with the **Enterprise Minimal** theme.

## Quick start

```bash
npm install
npm run dev          # http://localhost:3000
```

No backend or Microsoft tenant is needed: by default the app runs in **mock mode**. [MSW](https://mswjs.io) intercepts
`/api/v1/*` in the browser and serves a seeded world that follows the "A day with Scrum Bot" story (Neha's Payments team).
Pick a persona on the sign-in screen to see the app as each role:

| Persona | Role | Try |
|---|---|---|
| Neha Kapoor | Scrum Lead · Payments | Dashboard, Tuesday's standup, blockers, review queue, questions/schedule editors |
| Deepa Iyer | Org Admin | Integrations, users & roles, settings, audit log, setup wizard |
| Rahul Verma | Member | Only his own transcript segments; no configuration |
| Vikram Rao | Viewer | Team aggregates only; no names in mismatches, no transcripts |

Email links that work without signing in: `/a/demo-priya-review`, `/a/demo-rahul-sandbox` (already resolved),
`/a/demo-expired`, `/a/demo-checkin-karan?type=checkin`.

The mock data is anchored to the most recent Friday, so "Last 7 days" on the dashboard always shows the story week.
Changes persist in `localStorage`; use **account menu → Reset demo data** to start over.

## Live mode

```bash
cp .env.example .env.local
# NEXT_PUBLIC_APP_MODE=live, NEXT_PUBLIC_API_URL, NEXT_PUBLIC_ENTRA_* (app registration)
```

Live mode signs in with Microsoft Entra ID (MSAL, redirect flow) and calls the real backend with a bearer token.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` / `build` / `start` | Next.js dev server, production build (standalone), production server |
| `npm run lint` / `typecheck` | ESLint (incl. a no-hex-colors rule for components) / `tsc --noEmit` |
| `npm test` | Vitest: unit (cron, RBAC, formatters), component, and story integration tests against MSW |
| `npm run e2e` | Playwright: the Neha story, axe accessibility checks, mobile layout (builds and serves on :3100) |
| `npm run gen:api` | Generates `src/lib/api/schema.d.ts` from `../backend/openapi.json` once the backend publishes it |

## Layout

```
src/app/(public)/      login, signed action links (/a/[token])
src/app/(app)/         authenticated shell: dashboard, standups, blockers, review, teams, integrations, settings, audit, onboarding
src/components/        ui (primitives), layout, cards, charts, forms, feedback
src/features/          feature hooks and composed editors (teams, blockers, metrics, settings)
src/lib/               api client + types + query keys, auth (mock/MSAL), rbac, schedule (cron), format
src/styles/tokens.css  Enterprise Minimal design tokens — the only place colors are defined
mocks/                 MSW handlers, seed data, in-browser mock DB
tests/  e2e/           Vitest and Playwright suites
```

## Notes and known gaps

- **API types** are hand-written in `src/lib/api/types.ts` to mirror the backend plan until `backend/openapi.json` exists.
- **Storybook** is not set up yet; component states are covered by Vitest and axe runs in Playwright instead.
- **Bundle budget:** most routes are under 200 KB first-load JS; the form-heavy routes (onboarding, question editor,
  settings) are ~215–235 KB because of React Hook Form + Zod.
- **Table virtualization** (>200 rows) is not implemented; current lists are small and paginated by the API.
- **Route guards** run client-side because MSAL tokens live in the browser; the API enforces the same RBAC.
