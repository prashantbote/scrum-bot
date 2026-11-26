"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pause, Play, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import type { Schedule } from "@/lib/api/types";
import { useCan } from "@/lib/rbac/Can";
import { useUnsavedChanges } from "@/lib/hooks/useUnsavedChanges";
import { dateTimeInZone, shortDate } from "@/lib/format";
import { describe, fromCron, nextRuns, toCron } from "@/lib/schedule/cron";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Switch } from "@/components/ui/primitives";
import { CronBuilder, TimezoneSelect } from "@/components/forms/ScheduleFields";
import { ErrorState, SkeletonRows } from "@/components/feedback/states";

interface FormState {
  days: number[];
  time: string;
  timezone: string;
  holiday_calendar: string;
  skip_dates: string[];
  async_window_minutes: number;
  lead_minutes: number;
}

const HOLIDAYS = [
  { value: "", label: "None" },
  { value: "IN", label: "India public holidays" },
  { value: "US", label: "US federal holidays" },
  { value: "UK", label: "UK bank holidays" },
];

function fromSchedule(s: Schedule | undefined, fallbackTz: string): FormState {
  const simple = s ? fromCron(s.cron) : { days: [1, 2, 3, 4, 5], time: "10:30" };
  return {
    ...simple,
    timezone: s?.timezone ?? fallbackTz,
    holiday_calendar: s?.holiday_calendar ?? "IN",
    skip_dates: s?.skip_dates ?? [],
    async_window_minutes: s?.async_window_minutes ?? 120,
    lead_minutes: s?.lead_minutes ?? 5,
  };
}

export function ScheduleEditor({ teamId, onSaved, compact }: { teamId: string; onSaved?: () => void; compact?: boolean }) {
  const qc = useQueryClient();
  const canEdit = useCan("team.configure", { teamId });
  const team = useQuery({ queryKey: qk.teams.detail(teamId), queryFn: () => api.team(teamId) });
  const schedule = useQuery({ queryKey: qk.teams.schedule(teamId), queryFn: () => api.schedule(teamId), retry: false });
  const exists = !!schedule.data;
  const [state, setState] = React.useState<FormState | null>(null);
  const [dirty, setDirty] = React.useState(false);
  const [skipInput, setSkipInput] = React.useState("");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  useUnsavedChanges(dirty);

  const loaded = !schedule.isPending && !team.isPending;
  React.useEffect(() => {
    if (loaded && !dirty) setState(fromSchedule(schedule.data, team.data?.timezone ?? "Asia/Kolkata"));
  }, [loaded, schedule.data, team.data, dirty]);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => {
    setState((s) => (s ? { ...s, [k]: v } : s));
    setDirty(true);
  };

  const preview = React.useMemo(() => {
    if (!state || state.days.length === 0 || !state.time) return [];
    try {
      return nextRuns(toCron({ days: state.days, time: state.time }), state.timezone, 5, { skipDates: state.skip_dates });
    } catch {
      return [];
    }
  }, [state]);

  const save = useMutation({
    mutationFn: (s: FormState) =>
      api.saveSchedule(teamId, {
        cron: toCron({ days: s.days, time: s.time }),
        timezone: s.timezone,
        holiday_calendar: s.holiday_calendar || null,
        skip_dates: s.skip_dates,
        async_window_minutes: s.async_window_minutes,
        lead_minutes: s.lead_minutes,
        paused: schedule.data?.paused ?? false,
      }),
    meta: { silent: true },
    onSuccess: (saved) => {
      setDirty(false);
      qc.setQueryData(qk.teams.schedule(teamId), saved);
      qc.invalidateQueries({ queryKey: qk.teams.all });
      toast.success(exists ? "Schedule updated" : "Schedule created and recurring Teams meeting sent to members");
      onSaved?.();
    },
    onError: (err) => {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      toast.error(err instanceof Error ? err.message : "Couldn't save schedule");
    },
  });
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.pauseSchedule(teamId, paused),
    onSuccess: (s) => {
      qc.setQueryData(qk.teams.schedule(teamId), s);
      qc.invalidateQueries({ queryKey: qk.teams.all });
      toast.success(s.paused ? "Standups paused" : "Standups resumed");
    },
  });
  const trigger = useMutation({
    mutationFn: () => api.triggerNow(teamId),
    onSuccess: () => toast.success("Standup started — the bot is joining the Teams meeting now"),
  });

  if (!loaded || !state) return <SkeletonRows rows={6} />;
  if (schedule.isError && !(schedule.error instanceof ApiError && schedule.error.status === 404))
    return <ErrorState error={schedule.error} onRetry={() => schedule.refetch()} />;

  const submit = () => {
    const e: Record<string, string> = {};
    if (state.days.length === 0) e.days = "Pick at least one day";
    if (!state.time) e.time = "Pick a time";
    setErrors(e);
    if (Object.keys(e).length === 0) save.mutate(state);
  };

  return (
    <div className={compact ? "flex flex-col gap-3" : "grid grid-cols-1 gap-3 lg:grid-cols-3"}>
      <Card className={compact ? "" : "lg:col-span-2"}>
        <CardHeader
          title="Standup schedule"
          description={exists ? describe({ days: state.days, time: state.time }) + ` · ${state.timezone}` : "Not scheduled yet"}
          action={
            exists &&
            canEdit && (
              <label className="flex items-center gap-2 text-meta">
                <Switch
                  checked={!schedule.data!.paused}
                  onCheckedChange={(on) => pause.mutate(!on)}
                  disabled={pause.isPending}
                  aria-label="Standups enabled"
                />
                {schedule.data!.paused ? "Paused" : "Active"}
              </label>
            )
          }
        />
        <fieldset disabled={!canEdit} className="flex flex-col gap-4 p-4">
          <CronBuilder
            days={state.days}
            time={state.time}
            onDaysChange={(d) => set("days", d)}
            onTimeChange={(t) => set("time", t)}
            idPrefix={`sched-${teamId}`}
            error={errors.days ?? errors.cron}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Time zone" htmlFor="sched-tz">
              <TimezoneSelect id="sched-tz" value={state.timezone} onChange={(v) => set("timezone", v)} />
            </Field>
            <Field label="Holiday calendar" htmlFor="sched-holidays" hint="No standup on public holidays.">
              <Select id="sched-holidays" value={state.holiday_calendar} onChange={(e) => set("holiday_calendar", e.target.value)}>
                {HOLIDAYS.map((h) => (
                  <option key={h.value} value={h.value}>
                    {h.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Async window"
              htmlFor="sched-async"
              hint="How long absentees have to answer the check-in card before the report goes out."
              error={errors.async_window_minutes}
            >
              <Select id="sched-async" value={state.async_window_minutes} onChange={(e) => set("async_window_minutes", Number(e.target.value))}>
                {[0, 30, 60, 120, 240].map((m) => (
                  <option key={m} value={m}>
                    {m === 0 ? "No async fallback" : m < 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? "s" : ""}`}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Prepare context" htmlFor="sched-lead" hint="Minutes before the call to load Jira tickets.">
              <Select id="sched-lead" value={state.lead_minutes} onChange={(e) => set("lead_minutes", Number(e.target.value))}>
                {[2, 5, 10].map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-meta font-medium">Skip dates</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {state.skip_dates.map((d) => (
                <span key={d} className="inline-flex h-6 items-center gap-1 rounded-control border border-border bg-surface-muted pl-2 pr-1 text-caption">
                  {shortDate(d)}
                  <button type="button" aria-label={`Remove skip date ${d}`} className="rounded-control p-0.5 hover:bg-neutral-bg" onClick={() => set("skip_dates", state.skip_dates.filter((x) => x !== d))}>
                    <X className="size-3" />
                  </button>
                </span>
              ))}
              <label htmlFor="sched-skip" className="sr-only">
                Add skip date
              </label>
              <Input id="sched-skip" type="date" className="w-40" value={skipInput} onChange={(e) => setSkipInput(e.target.value)} />
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!skipInput}
                onClick={() => {
                  if (!state.skip_dates.includes(skipInput)) set("skip_dates", [...state.skip_dates, skipInput].sort());
                  setSkipInput("");
                }}
              >
                Add
              </Button>
            </div>
          </div>
        </fieldset>
        {canEdit && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
            {dirty && <span className="mr-auto text-caption text-fg-muted">Unsaved changes</span>}
            {exists && (
              <Button type="button" variant="secondary" onClick={() => trigger.mutate()} loading={trigger.isPending}>
                <Zap /> Run now
              </Button>
            )}
            <Button type="button" variant="primary" onClick={submit} loading={save.isPending} disabled={exists && !dirty}>
              {exists ? "Save schedule" : "Create schedule"}
            </Button>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Next 5 runs" description={`Shown in ${state.timezone}`} />
        <div className="p-4">
          {schedule.data?.paused ? (
            <p className="flex items-center gap-2 text-meta text-fg-muted">
              <Pause className="size-4" aria-hidden /> Paused — no standups will run.
            </p>
          ) : preview.length === 0 ? (
            <p className="text-meta text-fg-muted">Pick days and a time to preview.</p>
          ) : (
            <ol className="flex flex-col gap-1.5">
              {preview.map((d) => (
                <li key={d.toISOString()} className="flex items-center gap-2 text-meta">
                  <CalendarClock className="size-4 text-teal-600" aria-hidden />
                  <span className="tabular">{dateTimeInZone(d.toISOString(), state.timezone, "EEE d MMM yyyy, HH:mm")}</span>
                </li>
              ))}
            </ol>
          )}
          {schedule.data?.join_url && (
            <p className="mt-3 flex items-center gap-1.5 border-t border-border pt-3 text-caption text-fg-muted">
              <Play className="size-3.5" aria-hidden /> Recurring Teams meeting is on members&apos; calendars.
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
