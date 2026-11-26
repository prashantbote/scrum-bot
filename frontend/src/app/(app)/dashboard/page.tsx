"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { format, parseISO } from "date-fns";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { KpiCard } from "@/components/cards/KpiCard";
import { InfoCard, MiniTable } from "@/components/cards/InfoCard";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/primitives";
import { Badge, TicketChip } from "@/components/ui/badge";
import { useCurrentTeam } from "@/features/teams/current-team";
import { RANGES, rangeQuery, useMetrics, useRange, type RangeValue } from "@/features/metrics/hooks";
import { useCan } from "@/lib/rbac/Can";
import { days, pct, signed } from "@/lib/format";

// Heavy chart libraries are split out of the initial bundle (plan §10).
const chartFallback = () => <Skeleton className="h-[180px] w-full" />;
const TrendLine = dynamic(() => import("@/components/charts/Charts").then((m) => m.TrendLine), { ssr: false, loading: chartFallback }) as typeof import("@/components/charts/Charts").TrendLine;
const Bars = dynamic(() => import("@/components/charts/Charts").then((m) => m.Bars), { ssr: false, loading: chartFallback }) as typeof import("@/components/charts/Charts").Bars;
const BurndownChart = dynamic(() => import("@/components/charts/Charts").then((m) => m.BurndownChart), { ssr: false, loading: chartFallback });
const DependencyGraph = dynamic(() => import("@/components/charts/DependencyGraph"), { ssr: false, loading: () => <Skeleton className="h-[220px] w-full" /> });

const short = (d: string) => format(parseISO(d), "EEE d");

export default function DashboardPage() {
  const { teamId, team } = useCurrentTeam();
  const [range, setRange] = useRange();
  const q = React.useMemo(() => (teamId ? rangeQuery(teamId, range) : null), [teamId, range]);
  const m = useMetrics(q);
  const individual = useCan("metrics.individual", { teamId: teamId ?? undefined });

  if (!teamId) {
    return (
      <>
        <PageHeader title="Team health" />
        <EmptyState title="No team yet" description="Create a team to start collecting standups." action={<Link href="/teams" className="link">Go to Teams</Link>} />
      </>
    );
  }

  const part = m.participation.data;
  const blk = m.blockers.data;
  const noData = part && part.series.length === 0;

  return (
    <>
      <PageHeader
        title="Team health"
        description={`${team?.name ?? ""} · aggregated across the team, not a ranking of people`}
        actions={
          <Select aria-label="Date range" value={range} onChange={(e) => setRange(e.target.value as RangeValue)} className="w-40">
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        }
      />

      {m.participation.isError ? (
        <ErrorState error={m.participation.error} onRetry={() => m.participation.refetch()} />
      ) : noData ? (
        <EmptyState title="No standups in this period" description="Pick a longer range, or check the team's schedule." />
      ) : (
        <div className="flex flex-col gap-3">
          {/* KPI row */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Attendance"
              loading={!part}
              value={part ? pct(part.rate) : "—"}
              sub="Present or answered async"
              delta={part && part.delta !== 0 ? { value: part.delta, label: `${signed(part.delta)} pts`, goodWhenUp: true } : undefined}
              sparkline={part?.series.map((s) => s.rate)}
              info="Members who joined the call or answered the async check-in, divided by members expected."
              href="/standups"
            />
            <KpiCard
              label="Blockers"
              loading={!blk}
              value={blk ? `${blk.raised} raised` : "—"}
              sub={blk ? `${blk.resolved} resolved · ${blk.open} open now` : undefined}
              info="Blockers first raised in this period, and blockers resolved in this period."
              href="/blockers"
            />
            <KpiCard
              label="Avg time to resolve"
              loading={!blk}
              value={blk ? (blk.resolved ? days(blk.avg_resolve_days) : "—") : "—"}
              sub="From first mention to resolved"
              delta={
                blk && blk.avg_resolve_delta !== 0
                  ? { value: blk.avg_resolve_delta, label: `${signed(blk.avg_resolve_delta, 1)} d`, goodWhenUp: false }
                  : undefined
              }
              info="Mean days between a blocker's first mention and its resolution, for blockers resolved in this period."
            />
            <KpiCard
              label="Said vs Jira"
              loading={!m.mismatches.data}
              value={m.mismatches.data ? m.mismatches.data.length : "—"}
              sub="Reported done, still open in Jira"
              info="Items a member reported as done whose Jira ticket was not Done 24 hours later."
            />
          </div>

          {/* Trends */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <InfoCard
              title="Participation trend"
              info="Daily share of members present or async."
              footer={{ label: "View standups", href: "/standups" }}
              table={
                part && (
                  <MiniTable
                    caption="Participation by day"
                    headers={["Day", "Present", "Async", "Absent", "Rate"]}
                    rows={part.series.map((s) => [short(s.date), s.present, s.async, s.absent, pct(s.rate)])}
                  />
                )
              }
            >
              {part ? (
                <TrendLine
                  ariaLabel={`Participation by day: ${part.series.map((s) => `${short(s.date)} ${pct(s.rate)}`).join(", ")}`}
                  data={part.series.map((s) => ({ day: short(s.date), rate: Math.round(s.rate * 100) }))}
                  xKey="day"
                  series={[{ key: "rate", label: "Attendance", color: "var(--chart-1)" }]}
                  yFormat={(v) => `${v}%`}
                  yDomain={[0, 100]}
                />
              ) : (
                <Skeleton className="h-[180px] w-full" />
              )}
            </InfoCard>

            <InfoCard
              title="Blockers raised vs resolved"
              info="Weekly counts over the last four weeks. Open blockers by age are listed below the chart."
              footer={{ label: "Open blockers board", href: "/blockers" }}
              table={
                blk && (
                  <MiniTable
                    caption="Blockers per week"
                    headers={["Week of", "Raised", "Resolved"]}
                    rows={blk.weekly.map((w) => [w.week, w.raised, w.resolved])}
                  />
                )
              }
            >
              {blk ? (
                <div className="flex flex-col gap-3">
                  <Bars
                    ariaLabel={`Blockers per week: ${blk.weekly.map((w) => `${w.week} raised ${w.raised}, resolved ${w.resolved}`).join("; ")}`}
                    data={blk.weekly}
                    xKey="week"
                    height={150}
                    series={[
                      { key: "raised", label: "Raised", color: "var(--chart-2)" },
                      { key: "resolved", label: "Resolved", color: "var(--chart-1)" },
                    ]}
                  />
                  <div className="flex flex-wrap gap-1.5" aria-label="Open blockers by age">
                    <span className="label-caps mr-1 self-center">Open by age</span>
                    {blk.age_buckets.map((b) => (
                      <Badge key={b.bucket} tone={b.count === 0 ? "outline" : b.bucket.startsWith("<") ? "neutral" : "warning"}>
                        {b.bucket}: {b.count}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <Skeleton className="h-[180px] w-full" />
              )}
            </InfoCard>
          </div>

          {/* Dependencies + mismatches */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <InfoCard
              title="Dependency map"
              info="Who this team reported waiting on, from blockers and dependencies. Thicker blue edge = most frequent."
              table={
                m.dependencies.data && (
                  <MiniTable
                    caption="Dependencies"
                    headers={["Waits on", "Mentions"]}
                    rows={m.dependencies.data.edges.map((e) => [m.dependencies.data!.nodes.find((n) => n.id === e.target)?.label ?? e.target, e.weight])}
                  />
                )
              }
            >
              {m.dependencies.data ? (
                m.dependencies.data.edges.length ? (
                  <DependencyGraph graph={m.dependencies.data} />
                ) : (
                  <EmptyState title="No cross-team waits" description="Nobody reported waiting on another team in this period." />
                )
              ) : (
                <Skeleton className="h-[220px] w-full" />
              )}
            </InfoCard>

            <InfoCard
              title="Said vs Jira mismatches"
              info="Reported done in standup, but the ticket is still open in Jira the next day."
              bodyClassName="p-0"
            >
              {!m.mismatches.data ? (
                <div className="p-4">
                  <Skeleton className="h-24 w-full" />
                </div>
              ) : m.mismatches.data.length === 0 ? (
                <EmptyState title="Everything matches" description="What people said lines up with Jira." />
              ) : !individual ? (
                <p className="p-4 text-meta text-fg-muted">
                  {m.mismatches.data.length} item(s) differ from Jira. Individual details are visible to the team&apos;s scrum lead.
                </p>
              ) : (
                <table className="w-full text-meta">
                  <caption className="sr-only">Said versus Jira mismatches</caption>
                  <thead>
                    <tr className="border-b border-border bg-surface-muted text-left text-caption text-fg-muted">
                      <th scope="col" className="h-8 px-4 font-medium">Member</th>
                      <th scope="col" className="px-2 font-medium">Ticket</th>
                      <th scope="col" className="px-2 font-medium">Said</th>
                      <th scope="col" className="px-4 font-medium">Jira</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.mismatches.data.map((r) => (
                      <tr key={`${r.ticket_key}-${r.date}`} className="h-row border-b border-border last:border-0">
                        <td className="px-4">{r.member_name}</td>
                        <td className="px-2">
                          <TicketChip ticketKey={r.ticket_key} />
                        </td>
                        <td className="px-2">
                          <Link href={`/standups/${r.session_id}`} className="link">
                            {r.said}
                          </Link>
                          <span className="ml-1 text-caption text-fg-muted">{short(r.date)}</span>
                        </td>
                        <td className="px-4">
                          <Badge tone="warning">{r.pm_status}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </InfoCard>
          </div>

          {/* Themes, carry-over, burndown */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <InfoCard title="Recurring blocker themes" info="Blocker descriptions clustered weekly and labelled by AI.">
              {m.themes.data ? (
                m.themes.data.length ? (
                  <ul className="flex flex-col gap-2">
                    {m.themes.data.map((t) => (
                      <li key={t.label} className="flex items-center justify-between gap-2 text-meta">
                        <span>{t.label}</span>
                        <span className="flex items-center gap-1.5">
                          <span className="tabular font-medium">{t.count}</span>
                          {t.trend === "up" ? (
                            <TrendingUp className="size-3.5 text-danger" aria-label="rising" />
                          ) : t.trend === "down" ? (
                            <TrendingDown className="size-3.5 text-teal-600" aria-label="falling" />
                          ) : (
                            <Minus className="size-3.5 text-fg-subtle" aria-label="steady" />
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="No blockers this period. Nice." />
                )
              ) : (
                <Skeleton className="h-28 w-full" />
              )}
            </InfoCard>

            <InfoCard
              title="Carry-over"
              info="Items planned for today that weren't reported done the next standup."
              table={
                m.carryOver.data && (
                  <MiniTable caption="Carry-over by day" headers={["Day", "Rate"]} rows={m.carryOver.data.series.map((s) => [short(s.date), pct(s.rate)])} />
                )
              }
            >
              {m.carryOver.data ? (
                <div className="flex flex-col gap-2">
                  <div className="flex items-baseline gap-2">
                    <span className="tabular text-kpi font-semibold">{pct(m.carryOver.data.rate)}</span>
                    <span className="text-caption text-fg-muted">{signed(m.carryOver.data.delta)} pts vs previous</span>
                  </div>
                  <TrendLine
                    ariaLabel="Carry-over rate by day"
                    height={110}
                    data={m.carryOver.data.series.map((s) => ({ day: short(s.date), rate: Math.round(s.rate * 100) }))}
                    xKey="day"
                    series={[{ key: "rate", label: "Carry-over", color: "var(--chart-2)" }]}
                    yFormat={(v) => `${v}%`}
                  />
                </div>
              ) : (
                <Skeleton className="h-28 w-full" />
              )}
            </InfoCard>

            <InfoCard
              title={m.burndown.data ? `Burndown · ${m.burndown.data.sprint_name}` : "Sprint burndown"}
              info="Pulled from Jira; cached for 15 minutes."
              table={
                m.burndown.data && (
                  <MiniTable caption="Burndown" headers={["Day", "Remaining", "Ideal"]} rows={m.burndown.data.points.map((p) => [short(p.date), p.remaining, p.ideal])} />
                )
              }
            >
              {m.burndown.data ? (
                <BurndownChart height={150} data={m.burndown.data.points.map((p) => ({ ...p, date: short(p.date) }))} />
              ) : (
                <Skeleton className="h-28 w-full" />
              )}
            </InfoCard>
          </div>
        </div>
      )}
    </>
  );
}
