"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { InfoCard } from "@/components/cards/InfoCard";
import { Card, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { IntegrationStatusBadge, SessionStatusBadge } from "@/components/ui/badge";
import { QueryState, SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk, STALE } from "@/lib/api/queryKeys";
import type { SessionSummary } from "@/lib/api/types";
import { dateTimeInZone, duration, pct, shortDate } from "@/lib/format";
import { describe, fromCron } from "@/lib/schedule/cron";

const sessionCols: ColumnDef<SessionSummary, unknown>[] = [
  { accessorKey: "run_date", header: "Date", cell: ({ getValue }) => shortDate(getValue<string>()) },
  { accessorKey: "status", header: "Status", cell: ({ row }) => <SessionStatusBadge status={row.original.status} /> },
  { accessorKey: "attendance_pct", header: "Attendance", cell: ({ getValue }) => <span className="tabular">{pct(getValue<number>())}</span> },
  { accessorKey: "blocker_count", header: "Blockers", cell: ({ getValue }) => <span className="tabular">{getValue<number>()}</span> },
  { accessorKey: "duration_seconds", header: "Duration", cell: ({ getValue }) => duration(getValue<number | null>()) },
];

export default function TeamOverviewPage() {
  const { teamId } = useParams<{ teamId: string }>();
  const router = useRouter();
  const team = useQuery({ queryKey: qk.teams.detail(teamId), queryFn: () => api.team(teamId), staleTime: STALE.config });
  const schedule = useQuery({ queryKey: qk.teams.schedule(teamId), queryFn: () => api.schedule(teamId), retry: false });
  const templates = useQuery({ queryKey: qk.teams.templates(teamId), queryFn: () => api.templates(teamId) });
  const integrations = useQuery({ queryKey: qk.integrations.all, queryFn: api.integrations });
  const sessions = useQuery({ queryKey: qk.sessions.list(teamId), queryFn: () => api.sessions(teamId) });
  const active = templates.data?.find((t) => t.is_active);

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <InfoCard title="Schedule" footer={{ label: "Edit schedule", href: `/teams/${teamId}/schedule` }}>
          {schedule.isPending ? (
            <SkeletonRows rows={2} className="p-0" />
          ) : schedule.data ? (
            <div className="flex flex-col gap-1 text-meta">
              <span className="text-body font-medium">{describe(fromCron(schedule.data.cron))}</span>
              <span className="text-fg-muted">{schedule.data.timezone}</span>
              <span className="text-fg-muted">
                Next:{" "}
                {schedule.data.paused
                  ? "paused"
                  : team.data?.next_run_at
                    ? dateTimeInZone(team.data.next_run_at, schedule.data.timezone)
                    : "—"}
              </span>
            </div>
          ) : (
            <p className="text-meta text-fg-muted">No schedule yet.</p>
          )}
        </InfoCard>
        <InfoCard title="Questions" footer={{ label: "Edit questions", href: `/teams/${teamId}/questions` }}>
          {active ? (
            <ol className="list-decimal pl-4 text-meta">
              {active.questions.map((q) => (
                <li key={q.id} className="truncate">
                  {q.text}
                </li>
              ))}
            </ol>
          ) : templates.isPending ? (
            <SkeletonRows rows={3} className="p-0" />
          ) : (
            <p className="text-meta text-fg-muted">No questions yet.</p>
          )}
          {active && <p className="mt-2 text-caption text-fg-muted">Version {active.version} · by {active.created_by_name}</p>}
        </InfoCard>
        <InfoCard title="Integrations" footer={{ label: "Manage integrations", href: "/integrations" }}>
          <ul className="flex flex-col gap-1.5">
            {(integrations.data ?? []).filter((i) => i.kind !== "ado").map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-2 text-meta">
                <span className="truncate">{i.display_name}</span>
                <IntegrationStatusBadge status={i.status} />
              </li>
            ))}
          </ul>
        </InfoCard>
      </div>

      <Card>
        <CardHeader title="Recent standups" action={<Link href="/standups" className="link text-meta">All standups</Link>} />
        <QueryState query={sessions}>
          {(d) => (
            <DataTable
              caption="Recent standups"
              columns={sessionCols}
              data={d.items.slice(0, 7)}
              getRowId={(s) => s.id}
              onRowClick={(s) => router.push(`/standups/${s.id}`)}
              empty="No standups yet — the first one runs at the next scheduled time."
            />
          )}
        </QueryState>
      </Card>
    </div>
  );
}
