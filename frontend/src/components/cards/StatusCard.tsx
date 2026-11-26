import * as React from "react";
import { Card } from "@/components/ui/card";
import { IntegrationStatusBadge } from "@/components/ui/badge";
import type { IntegrationStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const DOT: Record<IntegrationStatus, string> = {
  connected: "bg-teal-600",
  expiring: "bg-warning",
  error: "bg-danger",
  disconnected: "bg-fg-subtle",
};

/** Fixed-height (72 px) integration status row. */
export function StatusCard({
  icon,
  name,
  detail,
  status,
  lastChecked,
  actions,
}: {
  icon: React.ReactNode;
  name: string;
  detail: string;
  status: IntegrationStatus;
  lastChecked: string | null;
  actions?: React.ReactNode;
}) {
  return (
    <Card className="flex min-h-[72px] items-center gap-3 px-4 py-3">
      <span className="relative inline-flex size-9 shrink-0 items-center justify-center rounded-card border border-border bg-surface-muted text-fg-muted">
        {icon}
        <span aria-hidden className={cn("absolute -right-0.5 -top-0.5 size-2.5 rounded-full ring-2 ring-surface", DOT[status])} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-body font-medium">{name}</span>
          <IntegrationStatusBadge status={status} />
        </div>
        <div className="truncate text-caption text-fg-muted">
          {detail}
          {lastChecked && <> · checked {lastChecked}</>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </Card>
  );
}
