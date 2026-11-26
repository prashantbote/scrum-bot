"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Users, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk, STALE } from "@/lib/api/queryKeys";
import type { Team } from "@/lib/api/types";
import { dateTimeInZone } from "@/lib/format";
import { useAuth } from "@/lib/auth/AuthProvider";
import dynamic from "next/dynamic";

// Form + validation libraries load only when the dialog can be used (keeps /teams under budget).
const NewTeamDialog = dynamic(() => import("@/features/teams/NewTeamDialog").then((m) => m.NewTeamDialog), {
  ssr: false,
  loading: () => <Button variant="primary" disabled>New team</Button>,
});

const columns: ColumnDef<Team, unknown>[] = [
  {
    accessorKey: "name",
    header: "Team",
    cell: ({ row }) => (
      <Link href={`/teams/${row.original.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
        {row.original.name}
      </Link>
    ),
  },
  { accessorKey: "lead_name", header: "Scrum lead" },
  { accessorKey: "member_count", header: "Members", cell: ({ getValue }) => <span className="tabular">{getValue<number>()}</span> },
  {
    accessorKey: "next_run_at",
    header: "Next standup",
    cell: ({ row }) =>
      row.original.next_run_at ? dateTimeInZone(row.original.next_run_at, row.original.timezone) : <span className="text-fg-muted">Paused</span>,
  },
  {
    accessorKey: "active_template_version",
    header: "Questions",
    cell: ({ getValue }) => (getValue<number | null>() ? `v${getValue<number>()}` : <span className="text-fg-muted">Not set</span>),
  },
  {
    accessorKey: "active",
    header: "Status",
    cell: ({ row }) => (row.original.active ? <Badge tone="teal">Active</Badge> : <Badge tone="neutral">Inactive</Badge>),
  },
];

function TeamsInner() {
  const router = useRouter();
  const search = useSearchParams().get("q")?.toLowerCase() ?? "";
  const { me } = useAuth();
  const teams = useQuery({ queryKey: qk.teams.list(), queryFn: api.teams, staleTime: STALE.config });
  const canCreate = me?.role === "org_admin" || me?.role === "scrum_lead";

  return (
    <>
      <PageHeader
        title="Teams"
        description="Each team has its own members, questions and standup schedule."
        actions={
          <>
            {me?.role === "org_admin" && (
              <Button asChild variant="secondary">
                <Link href="/onboarding/org">
                  <Wand2 /> Setup wizard
                </Link>
              </Button>
            )}
            {canCreate && <NewTeamDialog />}
          </>
        }
      />
      <Card>
        <QueryState
          query={teams}
          isEmpty={(d) => d.items.length === 0}
          empty={<EmptyState icon={Users} title="No teams yet" description="Create your first team to schedule a standup." action={canCreate && <NewTeamDialog />} />}
        >
          {(d) => (
            <DataTable
              caption="Teams"
              columns={columns}
              data={d.items.filter((t) => !search || t.name.toLowerCase().includes(search) || t.lead_name.toLowerCase().includes(search))}
              getRowId={(t) => t.id}
              onRowClick={(t) => router.push(`/teams/${t.id}`)}
              empty={search ? `No team matches “${search}”` : undefined}
            />
          )}
        </QueryState>
      </Card>
    </>
  );
}

export default function TeamsPage() {
  return (
    <React.Suspense fallback={null}>
      <TeamsInner />
    </React.Suspense>
  );
}
