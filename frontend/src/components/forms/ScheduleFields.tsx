"use client";

import * as React from "react";
import { COMMON_TIMEZONES, WEEKDAYS } from "@/lib/schedule/cron";
import { Input, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** Days-of-week chips + time input. Emits a SimpleSchedule; parent converts to cron. */
export function CronBuilder({
  days,
  time,
  onDaysChange,
  onTimeChange,
  idPrefix = "sched",
  error,
}: {
  days: number[];
  time: string;
  onDaysChange: (d: number[]) => void;
  onTimeChange: (t: string) => void;
  idPrefix?: string;
  error?: string;
}) {
  const toggle = (d: number) => onDaysChange(days.includes(d) ? days.filter((x) => x !== d) : [...days, d]);
  return (
    <div className="flex flex-col gap-3">
      <fieldset>
        <legend className="mb-1 text-meta font-medium">Days</legend>
        <div className="flex flex-wrap gap-1.5" role="group" aria-describedby={error ? `${idPrefix}-days-error` : undefined}>
          {WEEKDAYS.map((d) => {
            const on = days.includes(d.value);
            return (
              <button
                key={d.value}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(d.value)}
                className={cn(
                  "h-control min-w-11 rounded-control border px-2 text-meta font-medium transition-colors",
                  on
                    ? "border-teal-600 bg-teal-50 text-teal-700"
                    : "border-border-strong bg-surface text-fg-muted hover:bg-surface-muted",
                )}
              >
                {d.short}
              </button>
            );
          })}
        </div>
        {error && (
          <p id={`${idPrefix}-days-error`} className="mt-1 text-caption text-danger" role="alert">
            {error}
          </p>
        )}
      </fieldset>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${idPrefix}-time`} className="text-meta font-medium">
          Standup time
        </label>
        <Input
          id={`${idPrefix}-time`}
          type="time"
          step={300}
          value={time}
          onChange={(e) => onTimeChange(e.target.value)}
          className="w-32"
        />
      </div>
    </div>
  );
}

export function TimezoneSelect({
  value,
  onChange,
  id,
  ...rest
}: { value: string; onChange: (tz: string) => void; id: string } & Omit<
  React.SelectHTMLAttributes<HTMLSelectElement>,
  "value" | "onChange"
>) {
  const zones = React.useMemo(() => {
    const all: readonly string[] = COMMON_TIMEZONES;
    return all.includes(value) ? all : [value, ...all];
  }, [value]);
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} {...rest}>
      {zones.map((z) => (
        <option key={z} value={z}>
          {z.replace("_", " ")}
        </option>
      ))}
    </Select>
  );
}
