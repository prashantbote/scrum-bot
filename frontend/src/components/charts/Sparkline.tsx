import * as React from "react";
import { cn } from "@/lib/utils";

/** Tiny dependency-free SVG sparkline (decorative; the KPI value carries the information). */
export function Sparkline({ data, className }: { data: number[]; className?: string }) {
  const w = 80;
  const h = 24;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - 2 - ((v - min) / range) * (h - 4)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${d} L${w},${h} L0,${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden className={cn("overflow-visible", className)}>
      <path d={area} fill="var(--teal-50)" />
      <path d={d} fill="none" stroke="var(--teal-400)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
