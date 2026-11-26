"use client";

import * as React from "react";
import { format, subDays } from "date-fns";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";
import { qk, STALE } from "@/lib/api/queryKeys";
import type { MetricsQuery } from "@/lib/api/types";

export const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
] as const;
export type RangeValue = (typeof RANGES)[number]["value"];

export function rangeQuery(teamId: string, range: RangeValue, today = new Date()): MetricsQuery {
  const days = Number(range);
  return {
    team: teamId,
    from: format(subDays(today, days - 1), "yyyy-MM-dd"),
    to: format(today, "yyyy-MM-dd"),
  };
}

export function useMetrics(q: MetricsQuery | null) {
  const enabled = !!q?.team;
  const opts = { enabled, staleTime: STALE.metrics } as const;
  const qq = q ?? { team: "", from: "", to: "" };
  return {
    participation: useQuery({ queryKey: qk.metrics.participation(qq), queryFn: () => api.participation(qq), ...opts }),
    blockers: useQuery({ queryKey: qk.metrics.blockers(qq), queryFn: () => api.blockerMetrics(qq), ...opts }),
    carryOver: useQuery({ queryKey: qk.metrics.carryOver(qq), queryFn: () => api.carryOver(qq), ...opts }),
    mismatches: useQuery({ queryKey: qk.metrics.mismatches(qq), queryFn: () => api.mismatches(qq), ...opts }),
    dependencies: useQuery({ queryKey: qk.metrics.dependencies(qq), queryFn: () => api.dependencies(qq), ...opts }),
    themes: useQuery({ queryKey: qk.metrics.themes(qq), queryFn: () => api.themes(qq), ...opts }),
    burndown: useQuery({ queryKey: qk.metrics.burndown(qq), queryFn: () => api.burndown(qq), ...opts }),
  };
}

/** Persisted range filter (per-viewer convenience). */
export function useRange(): [RangeValue, (r: RangeValue) => void] {
  const [range, setRange] = React.useState<RangeValue>("7");
  React.useEffect(() => {
    try {
      const v = window.localStorage.getItem("scrumbot.range");
      if (v === "7" || v === "14" || v === "30") setRange(v);
    } catch {
      /* ignore */
    }
  }, []);
  return [
    range,
    (r) => {
      setRange(r);
      try {
        window.localStorage.setItem("scrumbot.range", r);
      } catch {
        /* ignore */
      }
    },
  ];
}
