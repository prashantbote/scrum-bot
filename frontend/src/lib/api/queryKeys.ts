import type { BlockerStatus, MetricsQuery, ReviewKind } from "./types";

/** Centralized TanStack Query key factory. Invalidate by prefix, e.g. qk.blockers.all. */
export const qk = {
  me: ["me"] as const,
  org: { settings: ["org", "settings"] as const },
  users: { list: (search?: string) => ["users", "list", search ?? ""] as const, all: ["users"] as const },
  teams: {
    all: ["teams"] as const,
    list: () => ["teams", "list"] as const,
    detail: (id: string) => ["teams", "detail", id] as const,
    members: (id: string) => ["teams", "members", id] as const,
    templates: (id: string) => ["teams", "templates", id] as const,
    schedule: (id: string) => ["teams", "schedule", id] as const,
  },
  integrations: { all: ["integrations"] as const },
  sessions: {
    all: ["sessions"] as const,
    list: (teamId: string) => ["sessions", "list", teamId] as const,
    detail: (id: string) => ["sessions", "detail", id] as const,
    attendance: (id: string) => ["sessions", "attendance", id] as const,
    transcript: (id: string) => ["sessions", "transcript", id] as const,
    updates: (id: string) => ["sessions", "updates", id] as const,
    report: (id: string) => ["sessions", "report", id] as const,
  },
  blockers: {
    all: ["blockers"] as const,
    list: (q: { team?: string; status?: BlockerStatus }) => ["blockers", "list", q] as const,
    detail: (id: string) => ["blockers", "detail", id] as const,
  },
  review: {
    all: ["review"] as const,
    list: (kind?: ReviewKind) => ["review", "list", kind ?? "all"] as const,
  },
  metrics: {
    all: ["metrics"] as const,
    participation: (q: MetricsQuery) => ["metrics", "participation", q] as const,
    blockers: (q: MetricsQuery) => ["metrics", "blockers", q] as const,
    carryOver: (q: MetricsQuery) => ["metrics", "carry-over", q] as const,
    mismatches: (q: MetricsQuery) => ["metrics", "mismatches", q] as const,
    dependencies: (q: MetricsQuery) => ["metrics", "dependencies", q] as const,
    themes: (q: MetricsQuery) => ["metrics", "themes", q] as const,
    burndown: (q: MetricsQuery) => ["metrics", "burndown", q] as const,
  },
  actions: { preview: (token: string) => ["actions", token] as const },
  audit: { list: (q: { entity?: string; actor?: string }) => ["audit", q] as const },
};

/** Stale times from the plan (§6): metrics 5 min, config 30 s. */
export const STALE = { metrics: 5 * 60_000, config: 30_000 } as const;
