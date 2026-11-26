import type { Role } from "@/lib/api/types";

export interface SeedUser {
  id: string;
  display_name: string;
  email: string;
  role: Role;
  department: string | null;
  aliases: string[];
  pm_account_id: string | null;
}

const domain = "acme.example";
const u = (
  id: string,
  display_name: string,
  role: Role,
  department: string | null,
  aliases: string[] = [],
): SeedUser => ({
  id,
  display_name,
  email: `${display_name.toLowerCase().replace(/\s+/g, ".")}@${domain}`,
  role,
  department,
  aliases,
  pm_account_id: role === "viewer" ? null : `jira-${id.slice(2)}`,
});

export const USERS: SeedUser[] = [
  u("u-deepa", "Deepa Iyer", "org_admin", "Engineering Ops"),
  u("u-neha", "Neha Kapoor", "scrum_lead", "Payments"),
  u("u-rahul", "Rahul Verma", "member", "Payments"),
  u("u-amit", "Amit Sharma", "member", "Backend", ["Amit from backend"]),
  u("u-priya", "Priya Nair", "member", "Payments"),
  u("u-karan", "Karan Mehta", "member", "Payments"),
  u("u-sneha", "Sneha Joshi", "member", "Payments"),
  u("u-arjun", "Arjun Patel", "scrum_lead", "Backend"),
  u("u-meera", "Meera Das", "member", "Backend"),
  u("u-amits", "Amit Singh", "member", "QA", ["Amit from QA"]),
  u("u-vikram", "Vikram Rao", "viewer", "Leadership"),
];

/** Personas offered on the mock sign-in screen. */
export const PERSONAS = [
  { userId: "u-neha", blurb: "Scrum Lead · Payments — the story's main user" },
  { userId: "u-deepa", blurb: "Org Admin — integrations, users, audit" },
  { userId: "u-rahul", blurb: "Member · Payments — sees own individual data" },
  { userId: "u-vikram", blurb: "Viewer — team-level aggregates only" },
] as const;

export const TEAM_DEFS = [
  {
    id: "team-payments",
    name: "Payments",
    lead: "u-neha",
    timezone: "Asia/Kolkata",
    cron: "30 10 * * 1-5",
    members: ["u-rahul", "u-amit", "u-priya", "u-karan", "u-sneha"],
  },
  {
    id: "team-backend",
    name: "Backend Platform",
    lead: "u-arjun",
    timezone: "Asia/Kolkata",
    cron: "0 10 * * 1-5",
    members: ["u-amit", "u-meera", "u-amits"],
  },
] as const;

export function userById(id: string): SeedUser {
  const user = USERS.find((x) => x.id === id);
  if (!user) throw new Error(`Unknown seed user ${id}`);
  return user;
}

export const firstName = (id: string) => userById(id).display_name.split(" ")[0]!;
