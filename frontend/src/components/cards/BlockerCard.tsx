"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Check, Eye } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge, SeverityDot, TicketChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Blocker, BlockerStatus } from "@/lib/api/types";
import { plural, relativeDays } from "@/lib/format";
import { cn } from "@/lib/utils";

export function AgeBadge({ days, escalated }: { days: number; escalated?: boolean }) {
  if (escalated) return <Badge tone="danger">Escalated · {plural(days, "day")}</Badge>;
  if (days >= 2) return <Badge tone="warning">{plural(days, "day")} open</Badge>;
  return <Badge tone="outline">{days === 0 ? "New today" : "1 day open"}</Badge>;
}

/** Board card: severity · description (2 lines) · reporter → blocked-on · tickets · age · actions. */
export function BlockerCard({
  blocker,
  onStatus,
  pending,
  canUpdate,
  compact,
}: {
  blocker: Blocker;
  onStatus?: (status: BlockerStatus) => void;
  pending?: boolean;
  canUpdate?: boolean;
  compact?: boolean;
}) {
  const who = (
    <span className="inline-flex min-w-0 items-center gap-1 text-caption text-fg-muted">
      <span className="truncate">{blocker.reporter_name}</span>
      <ArrowRight className="size-3 shrink-0" aria-label="blocked on" />
      <span className="truncate">{blocker.blocked_on_name ?? blocker.blocked_on_raw ?? "Unassigned"}</span>
    </span>
  );

  if (compact) {
    return (
      <Card className="flex h-10 items-center gap-2 px-3">
        <SeverityDot severity={blocker.severity} />
        <Link href={`/blockers/${blocker.id}`} className="min-w-0 flex-1 truncate text-meta hover:underline">
          {blocker.description}
        </Link>
        {blocker.ticket_keys[0] && <TicketChip ticketKey={blocker.ticket_keys[0]} />}
        {blocker.status === "resolved" ? (
          <span className="shrink-0 text-caption text-fg-muted">
            Resolved {blocker.resolved_at ? relativeDays(blocker.resolved_at) : ""}
          </span>
        ) : (
          <AgeBadge days={blocker.days_open} escalated={blocker.escalated} />
        )}
      </Card>
    );
  }

  return (
    <Card className={cn("flex flex-col gap-2 p-3", pending && "opacity-60")}>
      <div className="flex items-start gap-2">
        <span className="mt-1.5">
          <SeverityDot severity={blocker.severity} />
        </span>
        <Link href={`/blockers/${blocker.id}`} className="line-clamp-2 flex-1 text-meta font-medium hover:underline">
          {blocker.description}
        </Link>
      </div>
      {who}
      <div className="flex flex-wrap items-center gap-1.5">
        {blocker.ticket_keys.map((t) => (
          <TicketChip key={t} ticketKey={t} />
        ))}
        {blocker.status !== "resolved" && (
          <AgeBadge days={blocker.days_open} escalated={blocker.escalated} />
        )}
        <span className="text-caption text-fg-muted">{blocker.team_name}</span>
      </div>
      {canUpdate && onStatus && blocker.status !== "resolved" && (
        <div className="flex gap-1.5 pt-1">
          {blocker.status === "open" && (
            <Button size="sm" variant="secondary" onClick={() => onStatus("acknowledged")} disabled={pending}>
              <Eye /> Acknowledge
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={() => onStatus("resolved")} disabled={pending}>
            <Check /> Resolve
          </Button>
        </div>
      )}
      {canUpdate && onStatus && blocker.status === "resolved" && (
        <div className="pt-1">
          <Button size="sm" variant="ghost" onClick={() => onStatus("open")} disabled={pending}>
            Reopen
          </Button>
        </div>
      )}
    </Card>
  );
}
