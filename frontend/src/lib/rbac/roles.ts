import type { Me, Role } from "@/lib/api/types";

/**
 * Capability matrix from docs/BACKEND_IMPLEMENTATION_PLAN.md §6.1.
 * The backend enforces these; the frontend mirrors them to hide what a user cannot do.
 */
export type Action =
  | "org.manage"
  | "integrations.manage"
  | "users.manage"
  | "team.configure"
  | "team.view"
  | "reports.view"
  | "transcript.view"
  | "metrics.individual"
  | "review.decide"
  | "blocker.update"
  | "audit.view";

export interface Scope {
  teamId?: string;
  /** The user an individual-level view is about. */
  userId?: string;
}

export const ROLE_LABEL: Record<Role, string> = {
  org_admin: "Org Admin",
  scrum_lead: "Scrum Lead",
  member: "Member",
  viewer: "Viewer",
};

function leads(me: Me, teamId?: string) {
  return teamId ? me.lead_team_ids.includes(teamId) : me.lead_team_ids.length > 0;
}
function belongs(me: Me, teamId?: string) {
  return teamId ? me.member_team_ids.includes(teamId) || leads(me, teamId) : true;
}

export function can(me: Me | null | undefined, action: Action, scope: Scope = {}): boolean {
  if (!me) return false;
  if (me.role === "org_admin") return true;

  switch (action) {
    case "org.manage":
    case "integrations.manage":
    case "users.manage":
    case "audit.view":
      return false;

    case "team.configure":
    case "review.decide":
      return me.role === "scrum_lead" && leads(me, scope.teamId);

    case "team.view":
    case "reports.view":
      return me.role === "viewer" || belongs(me, scope.teamId);

    case "blocker.update":
      return me.role === "scrum_lead" || me.role === "member";

    case "transcript.view":
      if (me.role === "scrum_lead") return leads(me, scope.teamId);
      // Members may view their own segments only (filtered server-side); viewers never.
      return me.role === "member" && belongs(me, scope.teamId);

    case "metrics.individual":
      if (me.role === "scrum_lead") return leads(me, scope.teamId);
      if (me.role === "member") return scope.userId === me.id;
      return false;
  }
}

/** Route prefix → required action (most specific first). Used by the client route guard. */
export const ROUTE_RULES: { prefix: string; action: Action }[] = [
  { prefix: "/settings/users", action: "users.manage" },
  { prefix: "/settings", action: "org.manage" },
  { prefix: "/integrations", action: "integrations.manage" },
  { prefix: "/audit", action: "audit.view" },
  { prefix: "/onboarding", action: "org.manage" },
  { prefix: "/review", action: "review.decide" },
];

export function canVisit(me: Me | null | undefined, pathname: string): boolean {
  const rule = ROUTE_RULES.find((r) => pathname === r.prefix || pathname.startsWith(`${r.prefix}/`));
  if (!rule) return true;
  return can(me, rule.action);
}
