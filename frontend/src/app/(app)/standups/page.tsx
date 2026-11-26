"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Mic } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { SessionStatusBadge } from "@/components/ui/badge";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { SessionSummary } from "@/lib/api/types";
import { duration, longDate, pct } from "@/lib/format";
import { useCurrentTeam } from "@/features/teams/current-team";
import { cn } from "@/lib/utils";

const columns: ColumnDef<SessionSummary, unknown>[] = [
  { accessorKey: "run_date", header: "Date", cell: ({ getValue }) => <span className="font-medium">{longDate(getValue<string>())}</span> },
  { accessorKey: "team_name", header: "Team" },
  { accessorKey: "status", header: "Status", cell: ({ row }) => <SessionStatusBadge status={row.original.status} /> },
  {
    accessorKey: "attendance_pct",
    header: "Attendance",
    cell: ({ getValue }) => {
      const v = getValue<number>();
      return <span className={cn("tabular", v < 0.8 && "text-warning")}>{pct(v)}</span>;
    },
  },
  {
    accessorKey: "blocker_count",
    header: "Blockers",
    cell: ({ getValue }) => {
      const v = getValue<number>();
      return <span className={cn("tabular", v > 0 ? "font-medium text-danger" : "text-fg-muted")}>{v}</span>;
    },
  },
  { accessorKey: "duration_seconds", header: "Duration", cell: ({ getValue }) => <span className="tabular">{duration(getValue<number | null>())}</span> },
];

export default function StandupsPage() {
  const router = useRouter();
  const { teamId, team } = useCurrentTeam();
  const sessions = useQuery({
    queryKey: qk.sessions.list(teamId ?? ""),
    queryFn: () => api.sessions(teamId!),
    enabled: !!teamId,
  });

  return (
    <>
      <PageHeader title="Standups" description={team ? `${team.name} · newest first` : undefined} />
      <Card>
        {!teamId ? (
          <EmptyState icon={Mic} title="No team selected" />
        ) : (
          <QueryState
            query={sessions}
            isEmpty={(d) => d.items.length === 0}
            empty={<EmptyState icon={Mic} title="No standups yet" description="The first standup will appear here after it runs." />}
          >
            {(d) => (
              <DataTable
                caption={`Standups for ${team?.name ?? "team"}`}
                columns={columns}
                data={d.items}
                getRowId={(s) => s.id}
                onRowClick={(s) => router.push(`/standups/${s.id}`)}
              />
            )}
          </QueryState>
        )}
      </Card>
    </>
  );
}
