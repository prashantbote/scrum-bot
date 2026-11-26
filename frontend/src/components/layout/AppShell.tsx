"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  Bot,
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  Menu,
  RotateCcw,
  Search,
  UserRound,
  X,
} from "lucide-react";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import { useAuth } from "@/lib/auth/AuthProvider";
import { can } from "@/lib/rbac/roles";
import { ROLE_LABEL } from "@/lib/rbac/roles";
import { config } from "@/lib/config";
import { cn } from "@/lib/utils";
import { useCurrentTeam } from "@/features/teams/current-team";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import {
  Avatar,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/primitives";
import { NAV } from "./nav";

const COLLAPSE_KEY = "scrumbot.nav.collapsed";

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { me } = useAuth();
  const reviewEnabled = can(me, "review.decide");
  const review = useQuery({
    queryKey: qk.review.list(),
    queryFn: () => api.reviewItems(),
    enabled: reviewEnabled,
    staleTime: 60_000,
  });
  const pending = review.data?.items.length ?? 0;

  return (
    <ul className="flex flex-col gap-0.5 p-2">
      {NAV.filter((n) => !n.requires || can(me, n.requires)).map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href.split("/").slice(0, 2).join("/")}/`);
        const Icon = item.icon;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              title={collapsed ? item.label : undefined}
              className={cn(
                "relative flex h-8 items-center gap-2.5 rounded-control px-2.5 text-body font-medium text-fg-muted transition-colors hover:bg-surface-muted hover:text-fg",
                active && "bg-teal-50 text-teal-700 hover:bg-teal-50 hover:text-teal-700",
                collapsed && "justify-center px-0",
              )}
            >
              {active && <span aria-hidden className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-teal-600" />}
              <Icon className="size-4 shrink-0" aria-hidden />
              {!collapsed && <span className="truncate">{item.label}</span>}
              {item.badge === "review" && pending > 0 && (
                <span
                  className={cn(
                    "tabular ml-auto rounded-control bg-warning-bg px-1.5 text-caption font-medium text-warning",
                    collapsed && "absolute right-0.5 top-0.5 ml-0 px-1 text-[10px] leading-4",
                  )}
                  aria-label={`${pending} pending`}
                >
                  {pending}
                </span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function TeamSwitcher({ className }: { className?: string }) {
  const { teams, teamId, setTeamId } = useCurrentTeam();
  if (teams.length === 0) return null;
  return (
    <Select
      aria-label="Current team"
      value={teamId ?? ""}
      onChange={(e) => setTeamId(e.target.value)}
      className={cn("w-44", className)}
    >
      {teams.map((t) => (
        <option key={t.id} value={t.id}>
          {t.name}
        </option>
      ))}
    </Select>
  );
}

function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = React.useState("");
  return (
    <form
      role="search"
      className="relative hidden w-72 md:block"
      onSubmit={(e) => {
        e.preventDefault();
        const term = q.trim();
        if (!term) return;
        // Ticket keys go to blockers; anything else to teams.
        router.push(/^[A-Z]+-\d+$/i.test(term) ? `/blockers?q=${encodeURIComponent(term.toUpperCase())}` : `/teams?q=${encodeURIComponent(term)}`);
      }}
    >
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search teams, people, tickets"
        aria-label="Search teams, people, tickets"
        className="h-control w-full rounded-control border border-border bg-surface-muted pl-8 pr-2 text-body placeholder:text-fg-subtle focus-visible:border-blue-600 focus-visible:bg-surface"
      />
    </form>
  );
}

function UserMenu() {
  const { me, signOut, mode } = useAuth();
  const router = useRouter();
  if (!me) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-control px-1.5 py-1 hover:bg-surface-muted"
          aria-label={`Account menu for ${me.display_name}`}
        >
          <Avatar name={me.display_name} />
          <span className="hidden text-left lg:block">
            <span className="block text-meta font-medium leading-4">{me.display_name}</span>
            <span className="block text-caption text-fg-muted">{ROLE_LABEL[me.role]}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>
          <div className="text-body font-medium">{me.display_name}</div>
          <div className="text-caption text-fg-muted">{me.email}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {mode !== "live" && (
          <>
            <DropdownMenuItem
              onSelect={() => {
                signOut();
                router.push("/login");
              }}
            >
              <UserRound /> Switch persona
            </DropdownMenuItem>
            {mode === "mock" && (
              <DropdownMenuItem
                onSelect={async () => {
                  const { resetDb } = await import("@mocks/db");
                  resetDb();
                  window.location.reload();
                }}
              >
                <RotateCcw /> Reset demo data
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuItem
          onSelect={() => {
            signOut();
            router.push("/login");
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  const { me } = useAuth();
  return (
    <Link href="/dashboard" className="flex min-w-0 items-center gap-2">
      <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-control bg-teal-600 text-white">
        <Bot className="size-4" aria-hidden />
      </span>
      {!compact && (
        <span className="min-w-0">
          <span className="block text-body font-semibold leading-4">Scrum Bot</span>
          <span className="block truncate text-caption text-fg-muted">{me?.org_name}</span>
        </span>
      )}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [drawer, setDrawer] = React.useState(false);

  React.useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = () => {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-control bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2"
      >
        Skip to content
      </a>

      {/* Top bar — 56 px */}
      <header className="sticky top-0 z-30 flex h-topbar items-center gap-3 border-b border-border bg-surface px-4">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          aria-label="Open navigation"
          onClick={() => setDrawer(true)}
        >
          <Menu />
        </Button>
        <div className={cn("hidden shrink-0 lg:block", collapsed ? "w-8" : "w-[188px]")}>
          <Brand compact={collapsed} />
        </div>
        <div className="lg:hidden">
          <Brand compact />
        </div>
        <TeamSwitcher className="hidden sm:block" />
        <div className="flex-1" />
        <GlobalSearch />
        {config.mode === "mock" && (
          <span className="hidden rounded-control border border-dashed border-border-strong px-1.5 text-caption text-fg-muted xl:inline">
            Demo data
          </span>
        )}
        <UserMenu />
      </header>

      <div className="flex flex-1">
        {/* Side nav — 220 px, collapsible to 56 px */}
        <nav
          aria-label="Primary"
          className={cn(
            "sticky top-14 hidden h-[calc(100vh-56px)] shrink-0 flex-col border-r border-border bg-surface lg:flex",
            collapsed ? "w-nav-collapsed" : "w-nav",
          )}
        >
          <div className="flex-1 overflow-y-auto">
            <NavLinks collapsed={collapsed} />
          </div>
          <div className="border-t border-border p-2">
            <Button
              variant="ghost"
              size="sm"
              className={cn("w-full justify-start", collapsed && "justify-center")}
              onClick={toggle}
              aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            >
              {collapsed ? <ChevronsRight /> : <ChevronsLeft />}
              {!collapsed && "Collapse"}
            </Button>
          </div>
        </nav>

        {/* Mobile drawer */}
        <DialogPrimitive.Root open={drawer} onOpenChange={setDrawer}>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-overlay lg:hidden" />
            <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-surface lg:hidden">
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">Primary navigation</DialogPrimitive.Description>
              <div className="flex h-topbar items-center justify-between border-b border-border px-4">
                <Brand />
                <DialogPrimitive.Close asChild>
                  <Button variant="ghost" size="icon" aria-label="Close navigation">
                    <X />
                  </Button>
                </DialogPrimitive.Close>
              </div>
              <div className="p-3 sm:hidden">
                <TeamSwitcher className="w-full" />
              </div>
              <nav aria-label="Primary mobile" className="flex-1 overflow-y-auto">
                <NavLinks collapsed={false} onNavigate={() => setDrawer(false)} />
              </nav>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>

        <main id="main" className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-content px-4 py-4 lg:px-6 lg:py-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
