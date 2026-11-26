import * as React from "react";
import Link from "next/link";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { InfoTip, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { Sparkline } from "@/components/charts/Sparkline";

export interface KpiCardProps {
  label: string;
  value: React.ReactNode;
  /** Secondary line under the value, e.g. "3 resolved". */
  sub?: React.ReactNode;
  delta?: { value: number; label: string; /** true when an increase is good. */ goodWhenUp: boolean };
  sparkline?: number[];
  info?: string;
  href?: string;
  loading?: boolean;
  className?: string;
}

/**
 * Compact KPI card (~96 px): label · value · delta chip · optional sparkline.
 * When `href` is set the whole card is clickable via a stretched link, so the info button
 * isn't nested inside the link (invalid interactive nesting).
 */
export function KpiCard({ label, value, sub, delta, sparkline, info, href, loading, className }: KpiCardProps) {
  const good = delta ? (delta.value === 0 ? null : delta.value > 0 === delta.goodWhenUp) : null;
  return (
    <Card
      className={cn(
        "relative flex h-24 min-w-[200px] flex-col justify-between px-4 py-3",
        href && "transition-colors focus-within:border-blue-600 hover:border-border-strong",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        {href ? (
          <Link href={href} className="label-caps truncate after:absolute after:inset-0 after:rounded-card focus-visible:shadow-none">
            {label}
          </Link>
        ) : (
          <span className="label-caps truncate">{label}</span>
        )}
        {info && (
          <span className="relative z-10">
            <InfoTip text={info} />
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="h-8 w-24" />
      ) : (
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="tabular text-kpi font-semibold">{value}</span>
              {delta && delta.value !== 0 && (
                <span
                  className={cn(
                    "tabular inline-flex items-center gap-0.5 rounded-control px-1 text-caption font-medium",
                    good ? "bg-teal-50 text-teal-700" : "bg-danger-bg text-danger",
                  )}
                  aria-label={`${delta.value > 0 ? "Up" : "Down"} ${delta.label} versus previous period`}
                >
                  {delta.value > 0 ? <TrendingUp className="size-3" aria-hidden /> : <TrendingDown className="size-3" aria-hidden />}
                  {delta.label}
                </span>
              )}
            </div>
            {sub && <div className="truncate text-caption text-fg-muted">{sub}</div>}
          </div>
          {sparkline && sparkline.length > 1 && <Sparkline data={sparkline} className="h-6 w-20 shrink-0" />}
        </div>
      )}
    </Card>
  );
}
