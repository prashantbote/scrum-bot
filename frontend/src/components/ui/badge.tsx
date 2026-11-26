import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import type { AttendanceStatus, BlockerStatus, IntegrationStatus, SessionStatus, Severity } from "@/lib/api/types";

const badgeVariants = cva(
  "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-control px-1.5 text-caption font-medium",
  {
    variants: {
      tone: {
        teal: "bg-teal-50 text-teal-700",
        blue: "bg-blue-50 text-blue-700",
        warning: "bg-warning-bg text-warning",
        danger: "bg-danger-bg text-danger",
        neutral: "bg-neutral-bg text-neutral",
        outline: "border border-border bg-surface text-fg-muted",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/* Status → badge mapping (FRONTEND_IMPLEMENTATION_PLAN §4.2). Badges always carry text. */

const BLOCKER: Record<BlockerStatus, [BadgeTone, string]> = {
  open: ["danger", "Open"],
  acknowledged: ["blue", "Acknowledged"],
  resolved: ["teal", "Resolved"],
  needs_review: ["warning", "Needs review"],
};
export function BlockerStatusBadge({ status }: { status: BlockerStatus }) {
  const [tone, label] = BLOCKER[status];
  return <Badge tone={tone}>{label}</Badge>;
}

const ATTENDANCE: Record<AttendanceStatus, [BadgeTone, string]> = {
  present: ["teal", "Present"],
  async: ["blue", "Async"],
  absent: ["neutral", "Absent"],
};
export function AttendanceBadge({ status }: { status: AttendanceStatus }) {
  const [tone, label] = ATTENDANCE[status];
  return <Badge tone={tone}>{label}</Badge>;
}

const SESSION: Record<SessionStatus, [BadgeTone, string]> = {
  scheduled: ["outline", "Scheduled"],
  running: ["blue", "Running"],
  extracting: ["blue", "Processing"],
  delivered: ["teal", "Delivered"],
  skipped: ["neutral", "Skipped"],
  failed: ["danger", "Failed"],
};
export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  const [tone, label] = SESSION[status];
  return <Badge tone={tone}>{label}</Badge>;
}

const INTEGRATION: Record<IntegrationStatus, [BadgeTone, string]> = {
  connected: ["teal", "Connected"],
  expiring: ["warning", "Token expiring"],
  error: ["danger", "Error"],
  disconnected: ["neutral", "Not connected"],
};
export function IntegrationStatusBadge({ status }: { status: IntegrationStatus }) {
  const [tone, label] = INTEGRATION[status];
  return <Badge tone={tone}>{label}</Badge>;
}

const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-danger",
  medium: "bg-warning",
  low: "bg-fg-subtle",
};
export function SeverityDot({ severity }: { severity: Severity }) {
  return (
    <span
      role="img"
      aria-label={`${severity} severity`}
      title={`${severity} severity`}
      className={cn("inline-block size-2 shrink-0 rounded-full", SEVERITY_DOT[severity])}
    />
  );
}

export function TicketChip({ ticketKey }: { ticketKey: string }) {
  return <span className="ticket">{ticketKey}</span>;
}
