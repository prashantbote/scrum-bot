"use client";

import * as React from "react";
import { useParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PageHeader, SubNav } from "@/components/layout/PageHeader";
import { ErrorState, SkeletonRows } from "@/components/feedback/states";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/endpoints";
import { qk, STALE } from "@/lib/api/queryKeys";
import { useCan } from "@/lib/rbac/Can";

export default function TeamLayout({ children }: { children: React.ReactNode }) {
  const { teamId } = useParams<{ teamId: string }>();
  const pathname = usePathname();
  const team = useQuery({ queryKey: qk.teams.detail(teamId), queryFn: () => api.team(teamId), staleTime: STALE.config });
  const canConfigure = useCan("team.configure", { teamId });
  const base = `/teams/${teamId}`;

  if (team.isPending) return <SkeletonRows rows={6} />;
  if (team.isError) return <ErrorState error={team.error} onRetry={() => team.refetch()} />;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Teams", href: "/teams" }, { label: team.data.name }]}
        title={team.data.name}
        description={`Lead: ${team.data.lead_name} · ${team.data.timezone} · ${team.data.member_count} members`}
        actions={!canConfigure && <Badge tone="outline">View only</Badge>}
      />
      <SubNav
        items={[
          { href: base, label: "Overview", active: pathname === base },
          { href: `${base}/members`, label: "Members", active: pathname === `${base}/members` },
          { href: `${base}/questions`, label: "Questions", active: pathname === `${base}/questions` },
          { href: `${base}/schedule`, label: "Schedule", active: pathname === `${base}/schedule` },
        ]}
      />
      {children}
    </>
  );
}
