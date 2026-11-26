"use client";

import * as React from "react";
import { useParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PageHeader, SubNav } from "@/components/layout/PageHeader";
import { SessionStatusBadge } from "@/components/ui/badge";
import { ErrorState, SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import { duration, longDate, pct } from "@/lib/format";
import { useCan } from "@/lib/rbac/Can";

export default function SessionLayout({ children }: { children: React.ReactNode }) {
  const { sessionId } = useParams<{ sessionId: string }>();
  const pathname = usePathname();
  const session = useQuery({ queryKey: qk.sessions.detail(sessionId), queryFn: () => api.session(sessionId) });
  const canTranscript = useCan("transcript.view", { teamId: session.data?.team_id });
  const base = `/standups/${sessionId}`;

  if (session.isPending) return <SkeletonRows rows={6} />;
  if (session.isError) return <ErrorState error={session.error} onRetry={() => session.refetch()} />;
  const s = session.data;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Standups", href: "/standups" }, { label: `${s.team_name} · ${s.run_date}` }]}
        title={`${s.team_name} standup`}
        description={`${longDate(s.run_date)} · ${pct(s.attendance_pct)} attendance · ${duration(s.duration_seconds)} · questions v${s.template_version}`}
        actions={<SessionStatusBadge status={s.status} />}
      />
      <SubNav
        items={[
          { href: base, label: "Summary", active: pathname === base },
          ...(canTranscript ? [{ href: `${base}/transcript`, label: "Transcript", active: pathname === `${base}/transcript` }] : []),
          { href: `${base}/report`, label: "Report", active: pathname === `${base}/report` },
        ]}
      />
      {children}
    </>
  );
}
