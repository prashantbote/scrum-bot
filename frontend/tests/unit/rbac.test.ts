import { describe, expect, it } from "vitest";
import { can, canVisit } from "@/lib/rbac/roles";
import type { Me, Role } from "@/lib/api/types";

const me = (role: Role, lead: string[] = [], member: string[] = []): Me => ({
  id: `u-${role}`,
  org_id: "org",
  org_name: "Org",
  display_name: role,
  email: `${role}@x`,
  role,
  lead_team_ids: lead,
  member_team_ids: member,
  onboarded: true,
});

describe("RBAC matrix (backend plan §6.1)", () => {
  const admin = me("org_admin");
  const lead = me("scrum_lead", ["team-a"]);
  const member = me("member", [], ["team-a"]);
  const viewer = me("viewer");

  it("org admins can do everything", () => {
    for (const a of ["org.manage", "integrations.manage", "audit.view", "team.configure", "review.decide"] as const)
      expect(can(admin, a, { teamId: "team-z" })).toBe(true);
  });

  it("scrum leads configure only the teams they lead", () => {
    expect(can(lead, "team.configure", { teamId: "team-a" })).toBe(true);
    expect(can(lead, "team.configure", { teamId: "team-b" })).toBe(false);
    expect(can(lead, "integrations.manage")).toBe(false);
    expect(can(lead, "audit.view")).toBe(false);
  });

  it("members see individual metrics about themselves only", () => {
    expect(can(member, "metrics.individual", { userId: member.id })).toBe(true);
    expect(can(member, "metrics.individual", { userId: "someone-else" })).toBe(false);
    expect(can(member, "team.configure", { teamId: "team-a" })).toBe(false);
    expect(can(member, "reports.view", { teamId: "team-a" })).toBe(true);
    expect(can(member, "reports.view", { teamId: "team-b" })).toBe(false);
  });

  it("viewers get team-level aggregates only", () => {
    expect(can(viewer, "reports.view", { teamId: "team-a" })).toBe(true);
    expect(can(viewer, "metrics.individual", { teamId: "team-a" })).toBe(false);
    expect(can(viewer, "transcript.view", { teamId: "team-a" })).toBe(false);
    expect(can(viewer, "blocker.update")).toBe(false);
  });

  it("guards routes", () => {
    expect(canVisit(viewer, "/dashboard")).toBe(true);
    expect(canVisit(viewer, "/audit")).toBe(false);
    expect(canVisit(lead, "/review")).toBe(true);
    expect(canVisit(member, "/review")).toBe(false);
    expect(canVisit(lead, "/settings/users")).toBe(false);
    expect(canVisit(admin, "/settings/users")).toBe(true);
    expect(canVisit(null, "/dashboard")).toBe(true); // auth handled separately
  });
});
