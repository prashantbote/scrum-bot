"use client";

import * as React from "react";
import Link from "next/link";
import { Table2, LineChart } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * Compact information card: title row (label + optional action), body, optional blue footer link.
 * When `table` is given, a toggle swaps the chart body for an accessible table (plan §4.8).
 */
export function InfoCard({
  title,
  info,
  action,
  footer,
  table,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  info?: string;
  action?: React.ReactNode;
  footer?: { label: string; href: string };
  table?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  const [asTable, setAsTable] = React.useState(false);
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1">
            {title}
            {info && <InfoTip text={info} />}
          </span>
        }
        action={
          <>
            {action}
            {table && (
              <button
                type="button"
                onClick={() => setAsTable((v) => !v)}
                className="inline-flex size-7 items-center justify-center rounded-control text-fg-muted hover:bg-surface-muted hover:text-fg"
                aria-label={asTable ? `View ${title} as chart` : `View ${title} as table`}
                aria-pressed={asTable}
              >
                {asTable ? <LineChart className="size-4" /> : <Table2 className="size-4" />}
              </button>
            )}
          </>
        }
      />
      <div className={cn("min-h-0 flex-1 p-4", bodyClassName)}>{asTable && table ? table : children}</div>
      {footer && (
        <div className="border-t border-border px-4 py-2">
          <Link href={footer.href} className="link text-meta">
            {footer.label}
          </Link>
        </div>
      )}
    </Card>
  );
}

/** Minimal accessible table used as the chart fallback. */
export function MiniTable({ headers, rows, caption }: { headers: string[]; rows: (string | number)[][]; caption: string }) {
  return (
    <div className="max-h-64 overflow-auto">
      <table className="w-full text-meta">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border text-left text-caption text-fg-muted">
            {headers.map((h) => (
              <th key={h} scope="col" className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              {r.map((c, j) => (
                <td key={j} className="tabular py-1.5 pr-3">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
