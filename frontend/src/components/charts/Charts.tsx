"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/* Shared Enterprise Minimal chart styling â€” colors come from tokens.css. */
const axis = { stroke: "var(--border-strong)", fontSize: 12, tickLine: false, axisLine: false } as const;
const tick = { fill: "var(--text-muted)", fontSize: 12 };
const grid = { stroke: "var(--border)", strokeDasharray: "3 3", vertical: false } as const;
const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
    boxShadow: "var(--shadow-popover)",
  },
  labelStyle: { color: "var(--text)", fontWeight: 500 },
  itemStyle: { color: "var(--text-muted)" },
  cursor: { stroke: "var(--border-strong)", fill: "var(--surface-muted)" },
};
const legendStyle = { fontSize: 12, color: "var(--text-muted)" };

export interface Series {
  key: string;
  label: string;
  color: string; // e.g. "var(--chart-1)"
  dashed?: boolean;
}

export function TrendLine({
  data,
  xKey,
  series,
  yFormat,
  yDomain,
  height = 180,
  ariaLabel,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  series: Series[];
  yFormat?: (v: number) => string;
  yDomain?: [number | "auto", number | "auto"];
  height?: number;
  ariaLabel: string;
}) {
  return (
    <div role="img" aria-label={ariaLabel} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...grid} />
          <XAxis dataKey={xKey} {...axis} tick={tick} />
          <YAxis {...axis} tick={tick} tickFormatter={yFormat} domain={yDomain} width={44} />
          <Tooltip {...tooltipStyle} formatter={(v) => (yFormat ? yFormat(Number(v)) : String(v))} />
          {series.length > 1 && <Legend wrapperStyle={legendStyle} iconType="plainline" />}
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "4 4" : undefined}
              dot={{ r: 2.5, fill: s.color, strokeWidth: 0 }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Bars({
  data,
  xKey,
  series,
  stacked,
  height = 180,
  layout = "horizontal",
  ariaLabel,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  series: Series[];
  stacked?: boolean;
  height?: number;
  layout?: "horizontal" | "vertical";
  ariaLabel: string;
}) {
  const vertical = layout === "vertical";
  return (
    <div role="img" aria-label={ariaLabel} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={layout}
          margin={{ top: 4, right: 8, bottom: 0, left: vertical ? 8 : 0 }}
          barCategoryGap={vertical ? 6 : "24%"}
        >
          <CartesianGrid {...grid} vertical={vertical} horizontal={!vertical} />
          {vertical ? (
            <>
              <XAxis type="number" {...axis} tick={tick} allowDecimals={false} />
              <YAxis type="category" dataKey={xKey} {...axis} tick={tick} width={72} />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} {...axis} tick={tick} />
              <YAxis {...axis} tick={tick} allowDecimals={false} width={44} />
            </>
          )}
          <Tooltip {...tooltipStyle} />
          {series.length > 1 && <Legend wrapperStyle={legendStyle} iconType="square" iconSize={8} />}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={s.color}
              stackId={stacked ? "a" : undefined}
              radius={stacked ? 0 : [2, 2, 0, 0]}
              maxBarSize={28}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BurndownChart({
  data,
  height = 180,
}: {
  data: { date: string; ideal: number; remaining: number }[];
  height?: number;
}) {
  return (
    <div role="img" aria-label="Sprint burndown: remaining points versus ideal line" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...grid} />
          <XAxis dataKey="date" {...axis} tick={tick} />
          <YAxis {...axis} tick={tick} width={44} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={legendStyle} iconType="plainline" />
          <Area
            type="monotone"
            dataKey="remaining"
            name="Remaining"
            stroke="var(--chart-1)"
            fill="var(--teal-50)"
            strokeWidth={2}
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="ideal"
            name="Ideal"
            stroke="var(--chart-5)"
            strokeDasharray="4 4"
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
