import {
  ClipboardList,
  Gauge,
  type LucideIcon,
  Mic,
  Plug,
  ScrollText,
  Settings,
  ShieldAlert,
  Users,
} from "lucide-react";
import type { Action } from "@/lib/rbac/roles";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Hidden unless the user can perform this action. */
  requires?: Action;
  badge?: "review";
}

export const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/standups", label: "Standups", icon: Mic },
  { href: "/blockers", label: "Blockers", icon: ShieldAlert },
  { href: "/review", label: "Review", icon: ClipboardList, requires: "review.decide", badge: "review" },
  { href: "/teams", label: "Teams", icon: Users },
  { href: "/integrations", label: "Integrations", icon: Plug, requires: "integrations.manage" },
  { href: "/settings/org", label: "Settings", icon: Settings, requires: "org.manage" },
  { href: "/audit", label: "Audit", icon: ScrollText, requires: "audit.view" },
];
