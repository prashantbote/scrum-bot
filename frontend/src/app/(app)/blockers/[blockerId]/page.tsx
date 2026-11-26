"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CircleDot,
  Eye,
  Mail,
  MessageSquare,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BlockerStatusBadge, SeverityDot, TicketChip } from "@/components/ui/badge";
import { AgeBadge } from "@/components/cards/BlockerCard";
import { ErrorState, SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { BlockerEvent } from "@/lib/api/types";
import { dateTimeInZone, offset } from "@/lib/format";
import { useCan } from "@/lib/rbac/Can";
import { useBlockerStatus } from "@/features/blockers/useBlockerStatus";
import { cn } from "@/lib/utils";

const EVENT: Record<BlockerEvent["kind"], { icon: LucideIcon; label: string; tone: string }> = {
  raised: { icon: CircleDot, label: "Raised", tone: "bg-danger-bg text-danger" },
  mentioned: { icon: MessageSquare, label: "Mentioned again", tone: "bg-neutral-bg text-neutral" },
  alert_sent: { icon: Mail, label: "Alert sent", tone: "bg-blue-50 text-blue-700" },
  acknowledged: { icon: Eye, label: "Acknowledged", tone: "bg-blue-50 text-blue-700" },
  escalated: { icon: AlertTriangle, label: "Escalated", tone: "bg-warning-bg text-warning" },
  resolved: { icon: Check, label: "Resolved", tone: "bg-teal-50 text-teal-700" },
  reopened: { icon: RotateCcw, label: "Reopened", tone: "bg-danger-bg text-danger" },
};

const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

export default function BlockerDetailPage() {
  const { blockerId } = useParams<{ blockerId: string }>();
  const blocker = useQuery({ queryKey: qk.blockers.detail(blockerId), queryFn: () => api.blocker(blockerId) });
  const canUpdate = useCan("blocker.update");
  const status = useBlockerStatus();

  if (blocker.isPending) return <SkeletonRows rows={8} />;
  if (blocker.isError) return <ErrorState error={blocker.error} onRetry={() => blocker.refetch()} />;
  const b = blocker.data;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Blockers", href: "/blockers" }, { label: b.ticket_keys[0] ?? "Blocker" }]}
        title={b.description}
        description={`${b.team_name} · reported by ${b.reporter_name}`}
        actions={
          canUpdate && (
            <>
              {b.status === "open" && (
                <Button variant="secondary" onClick={() => status.mutate({ id: b.id, status: "acknowledged" })} disabled={status.isPending}>
                  <Eye /> Acknowledge
                </Button>
              )}
              {b.status !== "resolved" ? (
                <Button variant="primary" onClick={() => status.mutate({ id: b.id, status: "resolved" })} loading={status.isPending}>
                  <Check /> Resolve
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => status.mutate({ id: b.id, status: "open" })} loading={status.isPending}>
                  <RotateCcw /> Reopen
                </Button>
              )}
            </>
          )
        }
      />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className="flex flex-col gap-3 lg:col-span-2">
          <Card>
            <CardHeader title="Timeline" />
            <ol className="relative flex flex-col gap-0 p-4">
              {b.events.map((e, i) => {
                const meta = EVENT[e.kind];
                const Icon = meta.icon;
                return (
                  <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                    {i < b.events.length - 1 && <span aria-hidden className="absolute left-3.5 top-7 h-[calc(100%-20px)] w-px bg-border" />}
                    <span className={cn("z-10 inline-flex size-7 shrink-0 items-center justify-center rounded-full", meta.tone)}>
                      <Icon className="size-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0 pt-0.5">
                      <p className="text-meta">
                        <span className="font-medium">{meta.label}</span>
                        {e.actor_name && <span className="text-fg-muted"> · {e.actor_name}</span>}
                      </p>
                      {e.note && <p className="text-meta text-fg-muted">{e.note}</p>}
                      <p className="text-caption text-fg-muted">
                        {dateTimeInZone(e.at, tz())}
                        {e.session_id && (
                          <>
                            {" · "}
                            <Link href={`/standups/${e.session_id}`} className="link">
                              standup
                            </Link>
                          </>
                        )}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Card>

          <Card>
            <CardHeader title="What was said" description="Every blocker links to the transcript it was extracted from." />
            {b.evidence.length === 0 ? (
              <p className="px-4 py-3 text-meta text-fg-muted">Raised via async check-in (no voice transcript).</p>
            ) : (
              <ul className="divide-y divide-border">
                {b.evidence.map((ev) => (
                  <li key={ev.segment_id} className="px-4 py-2.5">
                    <blockquote className="border-l-2 border-teal-400 pl-3 text-body">“{ev.text}”</blockquote>
                    <p className="mt-1 pl-3 text-caption text-fg-muted">
                      {ev.speaker_label} ·{" "}
                      <Link href={`/standups/${ev.session_id}/transcript#${ev.segment_id}`} className="link">
                        {ev.session_id.slice(-10)} at {offset(ev.start_ms)}
                      </Link>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card className="self-start">
          <CardHeader title="Details" />
          <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2.5 p-4 text-meta">
            <dt className="text-fg-muted">Status</dt>
            <dd><BlockerStatusBadge status={b.status} /></dd>
            <dt className="text-fg-muted">Severity</dt>
            <dd className="flex items-center gap-1.5 capitalize"><SeverityDot severity={b.severity} /> {b.severity}</dd>
            <dt className="text-fg-muted">Age</dt>
            <dd>{b.status === "resolved" ? "Resolved" : <AgeBadge days={b.days_open} escalated={b.escalated} />}</dd>
            <dt className="text-fg-muted">Blocked on</dt>
            <dd>
              {b.blocked_on_name ?? "—"}
              {b.blocked_on_raw && <span className="block text-caption text-fg-muted">said: “{b.blocked_on_raw}”</span>}
            </dd>
            <dt className="text-fg-muted">Reporter</dt>
            <dd>{b.reporter_name}</dd>
            <dt className="text-fg-muted">Tickets</dt>
            <dd className="flex flex-wrap gap-1">{b.ticket_keys.map((t) => <TicketChip key={t} ticketKey={t} />)}</dd>
            <dt className="text-fg-muted">First seen</dt>
            <dd>{dateTimeInZone(b.first_seen_at, tz())}</dd>
            {b.resolved_at && (
              <>
                <dt className="text-fg-muted">Resolved</dt>
                <dd>{dateTimeInZone(b.resolved_at, tz())}</dd>
              </>
            )}
          </dl>
        </Card>
      </div>
    </>
  );
}
