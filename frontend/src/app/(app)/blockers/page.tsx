"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Columns3, Rows3, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { BlockerStatusBadge, SeverityDot, TicketChip } from "@/components/ui/badge";
import { AgeBadge, BlockerCard } from "@/components/cards/BlockerCard";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { Blocker, BlockerStatus, Severity } from "@/lib/api/types";
import { useCan } from "@/lib/rbac/Can";
import { shortDate } from "@/lib/format";
import { useCurrentTeam } from "@/features/teams/current-team";
import { useBlockerStatus } from "@/features/blockers/useBlockerStatus";

const COLUMNS: { status: BlockerStatus[]; title: string }[] = [
  { status: ["open", "needs_review"], title: "Open" },
  { status: ["acknowledged"], title: "Acknowledged" },
  { status: ["resolved"], title: "Resolved" },
];

const tableColumns: ColumnDef<Blocker, unknown>[] = [
  {
    accessorKey: "severity",
    header: "Sev",
    cell: ({ getValue }) => <SeverityDot severity={getValue<Severity>()} />,
    sortingFn: (a, b) => ["low", "medium", "high"].indexOf(a.original.severity) - ["low", "medium", "high"].indexOf(b.original.severity),
  },
  {
    accessorKey: "description",
    header: "Blocker",
    cell: ({ row }) => (
      <Link href={`/blockers/${row.original.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
        {row.original.description}
      </Link>
    ),
  },
  { accessorKey: "reporter_name", header: "Reported by" },
  { id: "on", header: "Blocked on", accessorFn: (b) => b.blocked_on_name ?? b.blocked_on_raw ?? "—" },
  { id: "tickets", header: "Tickets", enableSorting: false, cell: ({ row }) => <span className="flex gap-1">{row.original.ticket_keys.map((t) => <TicketChip key={t} ticketKey={t} />)}</span> },
  { accessorKey: "status", header: "Status", cell: ({ row }) => <BlockerStatusBadge status={row.original.status} /> },
  {
    accessorKey: "days_open",
    header: "Age",
    cell: ({ row }) => (row.original.status === "resolved" ? <span className="text-fg-muted">—</span> : <AgeBadge days={row.original.days_open} escalated={row.original.escalated} />),
  },
  { accessorKey: "first_seen_at", header: "First seen", cell: ({ getValue }) => shortDate(getValue<string>().slice(0, 10)) },
];

function BlockersInner() {
  const router = useRouter();
  const ticketQuery = useSearchParams().get("q") ?? "";
  const { teamId, teams } = useCurrentTeam();
  const [teamFilter, setTeamFilter] = React.useState<string>("current");
  const [severity, setSeverity] = React.useState<"" | Severity>("");
  const [minAge, setMinAge] = React.useState(0);
  const [view, setView] = React.useState<"board" | "table">("board");
  const canUpdate = useCan("blocker.update");
  const status = useBlockerStatus();

  const team = teamFilter === "current" ? teamId ?? undefined : teamFilter === "all" ? undefined : teamFilter;
  const blockers = useQuery({ queryKey: qk.blockers.list({ team }), queryFn: () => api.blockers({ team }) });

  const filtered = (blockers.data?.items ?? []).filter(
    (b) =>
      (!severity || b.severity === severity) &&
      (minAge === 0 || (b.status !== "resolved" && b.days_open >= minAge)) &&
      (!ticketQuery || b.ticket_keys.includes(ticketQuery)),
  );

  return (
    <>
      <PageHeader
        title="Blockers"
        description="Each blocker moves from open to acknowledged to resolved. Repeat mentions are matched, not re-alerted."
        actions={
          <div className="flex rounded-control border border-border-strong bg-surface p-0.5" role="group" aria-label="View">
            <Button size="sm" variant={view === "board" ? "secondary" : "ghost"} className={view === "board" ? "border-0 bg-surface-muted" : ""} aria-pressed={view === "board"} onClick={() => setView("board")}>
              <Columns3 /> Board
            </Button>
            <Button size="sm" variant={view === "table" ? "secondary" : "ghost"} className={view === "table" ? "border-0 bg-surface-muted" : ""} aria-pressed={view === "table"} onClick={() => setView("table")}>
              <Rows3 /> Table
            </Button>
          </div>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="f-team">Team</label>
        <Select id="f-team" className="w-44" value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)}>
          <option value="current">Current team</option>
          <option value="all">All teams</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </Select>
        <label className="sr-only" htmlFor="f-sev">Severity</label>
        <Select id="f-sev" className="w-36" value={severity} onChange={(e) => setSeverity(e.target.value as "" | Severity)}>
          <option value="">Any severity</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </Select>
        <label className="sr-only" htmlFor="f-age">Minimum age</label>
        <Select id="f-age" className="w-40" value={minAge} onChange={(e) => setMinAge(Number(e.target.value))}>
          <option value={0}>Any age</option>
          <option value={2}>Open ≥ 2 days</option>
          <option value={3}>Open ≥ 3 days</option>
          <option value={5}>Open ≥ 5 days</option>
        </Select>
        {ticketQuery && (
          <span className="flex items-center gap-1 text-meta text-fg-muted">
            Ticket <TicketChip ticketKey={ticketQuery} />
            <Link href="/blockers" className="link">clear</Link>
          </span>
        )}
      </div>

      <QueryState query={blockers}>
        {() =>
          filtered.length === 0 ? (
            <Card>
              <EmptyState icon={ShieldCheck} title="No blockers match" description="Nothing is blocking this team with these filters. Nice." />
            </Card>
          ) : view === "table" ? (
            <Card>
              <DataTable
                caption="Blockers"
                columns={tableColumns}
                data={filtered}
                getRowId={(b) => b.id}
                onRowClick={(b) => router.push(`/blockers/${b.id}`)}
                initialSorting={[{ id: "days_open", desc: true }]}
              />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {COLUMNS.map((col) => {
                const items = filtered
                  .filter((b) => col.status.includes(b.status))
                  .sort((a, b) => Number(b.escalated) - Number(a.escalated) || b.days_open - a.days_open);
                return (
                  <section key={col.title} aria-label={`${col.title} blockers`} className="flex flex-col gap-2 rounded-card bg-neutral-bg p-2">
                    <h2 className="flex items-center justify-between px-1 pt-0.5">
                      <span className="label-caps">{col.title}</span>
                      <span className="tabular text-caption text-fg-muted">{items.length}</span>
                    </h2>
                    {items.length === 0 ? (
                      <p className="px-1 pb-2 text-caption text-fg-muted">None</p>
                    ) : (
                      items.map((b) =>
                        col.title === "Resolved" ? (
                          <BlockerCard key={b.id} blocker={b} compact />
                        ) : (
                          <BlockerCard
                            key={b.id}
                            blocker={b}
                            canUpdate={canUpdate}
                            pending={status.isPending && status.variables?.id === b.id}
                            onStatus={(s) => status.mutate({ id: b.id, status: s })}
                          />
                        ),
                      )
                    )}
                  </section>
                );
              })}
            </div>
          )
        }
      </QueryState>
    </>
  );
}

export default function BlockersPage() {
  return (
    <React.Suspense fallback={null}>
      <BlockersInner />
    </React.Suspense>
  );
}
