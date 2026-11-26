"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/ui/card";
import { AttendanceBadge, SeverityDot, TicketChip } from "@/components/ui/badge";
import { MemberUpdateCard } from "@/components/cards/MemberUpdateCard";
import { EmptyState, QueryState, SkeletonCards } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { TranscriptSegment } from "@/lib/api/types";
import { useCan } from "@/lib/rbac/Can";

export default function SessionSummaryPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const session = useQuery({ queryKey: qk.sessions.detail(sessionId), queryFn: () => api.session(sessionId) });
  const canTranscript = useCan("transcript.view", { teamId: session.data?.team_id });
  const attendance = useQuery({ queryKey: qk.sessions.attendance(sessionId), queryFn: () => api.attendance(sessionId) });
  const updates = useQuery({ queryKey: qk.sessions.updates(sessionId), queryFn: () => api.updates(sessionId) });
  const transcript = useQuery({
    queryKey: qk.sessions.transcript(sessionId),
    queryFn: () => api.transcript(sessionId),
    enabled: canTranscript,
  });
  const segMap = React.useMemo(
    () => new Map<string, TranscriptSegment>((transcript.data ?? []).map((s) => [s.id, s])),
    [transcript.data],
  );

  const blockers = (updates.data ?? []).flatMap((u) => u.blockers.map((b) => ({ ...b, who: u.display_name })));

  return (
    <div className="flex flex-col gap-3">
      {/* Attendance strip */}
      <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <span className="label-caps">Attendance</span>
        {(attendance.data ?? []).map((a) => (
          <span key={a.user_id} className="flex items-center gap-1.5 text-meta">
            {a.display_name}
            <AttendanceBadge status={a.status} />
          </span>
        ))}
      </Card>

      {/* Blockers */}
      <Card>
        <CardHeader title={`Blockers (${blockers.length})`} />
        {blockers.length === 0 ? (
          <p className="px-4 py-3 text-meta text-fg-muted">No blockers reported.</p>
        ) : (
          <ul className="divide-y divide-border">
            {blockers.map((b, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 px-4 py-2 text-meta">
                <SeverityDot severity={b.severity} />
                <span className="font-medium">{b.who}</span>
                <span>{b.description}</span>
                {b.blocked_on_raw && <span className="text-fg-muted">— waiting on {b.blocked_on_raw}</span>}
                {b.ticket_keys.map((t) => (
                  <TicketChip key={t} ticketKey={t} />
                ))}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Member updates */}
      <QueryState
        query={updates}
        loading={<SkeletonCards count={3} />}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No updates extracted yet" description="Updates appear a few minutes after the call ends." />}
      >
        {(list) => {
          const absent = (attendance.data ?? []).filter((a) => a.status === "absent" && !list.some((u) => u.member_id === a.user_id));
          return (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.map((u) => (
                <MemberUpdateCard key={u.member_id} update={u} sessionId={sessionId} segments={segMap} />
              ))}
              {absent.map((a) => (
                <MemberUpdateCard
                  key={a.user_id}
                  sessionId={sessionId}
                  update={{ member_id: a.user_id, display_name: a.display_name, attendance: "absent", missing: true }}
                />
              ))}
            </div>
          );
        }}
      </QueryState>
    </div>
  );
}
