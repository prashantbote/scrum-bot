"use client";

import * as React from "react";
import { useFieldArray, type Control, type FieldErrors, type UseFormRegister } from "react-hook-form";
import { z } from "zod";
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** Mirrors the backend `questions` table (plan §4.1). */
export const questionSchema = z.object({
  text: z.string().trim().min(5, "Write the question in a few words").max(200, "Keep it under 200 characters"),
  type: z.enum(["text", "yes_no", "ticket_list"]),
  required: z.boolean(),
  followup_policy: z.enum(["none", "if_vague", "always"]),
  max_followups: z.coerce.number().int().min(0).max(3),
});
export const templateSchema = z.object({
  questions: z.array(questionSchema).min(1, "Add at least one question").max(8, "Keep standups short: 8 questions max"),
});
export type TemplateForm = z.infer<typeof templateSchema>;

export const DEFAULT_QUESTIONS: TemplateForm["questions"] = [
  { text: "What did you complete yesterday?", type: "ticket_list", required: true, followup_policy: "if_vague", max_followups: 2 },
  { text: "What will you work on today?", type: "ticket_list", required: true, followup_policy: "if_vague", max_followups: 2 },
  { text: "Any blockers or dependencies?", type: "text", required: true, followup_policy: "if_vague", max_followups: 2 },
];

const TYPE_LABEL = { text: "Free text", yes_no: "Yes / no", ticket_list: "Tickets + text" } as const;
const FOLLOWUP_LABEL = { none: "Never", if_vague: "If answer is vague", always: "Always" } as const;

/**
 * Ordered question editor. Reorder by drag (pointer) or the up/down buttons (keyboard),
 * per the accessibility requirement in plan §4.8.
 */
export function QuestionListEditor({
  control,
  register,
  errors,
  disabled,
}: {
  control: Control<TemplateForm>;
  register: UseFormRegister<TemplateForm>;
  errors?: FieldErrors<TemplateForm>;
  disabled?: boolean;
}) {
  const { fields, append, remove, move } = useFieldArray({ control, name: "questions" });
  const [dragFrom, setDragFrom] = React.useState<number | null>(null);
  const [liveMsg, setLiveMsg] = React.useState("");

  const moveTo = (from: number, to: number) => {
    if (to < 0 || to >= fields.length || from === to) return;
    move(from, to);
    setLiveMsg(`Question moved to position ${to + 1} of ${fields.length}`);
  };

  return (
    <div className="flex flex-col gap-2">
      <p className="sr-only" aria-live="polite">
        {liveMsg}
      </p>
      <ol className="flex flex-col gap-2">
        {fields.map((f, i) => {
          const err = errors?.questions?.[i];
          return (
            <li
              key={f.id}
              draggable={!disabled}
              onDragStart={() => setDragFrom(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragFrom !== null) moveTo(dragFrom, i);
                setDragFrom(null);
              }}
              className={cn(
                "rounded-card border border-border bg-surface p-3",
                dragFrom === i && "border-dashed border-teal-600 bg-teal-50",
              )}
            >
              <div className="flex items-start gap-2">
                <span className="mt-1.5 flex shrink-0 items-center gap-1 text-fg-subtle">
                  <GripVertical className="size-4 cursor-grab" aria-hidden />
                  <span className="tabular w-4 text-meta font-medium text-fg-muted">{i + 1}</span>
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <div>
                    <label htmlFor={`q-${i}-text`} className="sr-only">
                      Question {i + 1}
                    </label>
                    <Input
                      id={`q-${i}-text`}
                      placeholder="e.g. What did you complete yesterday?"
                      disabled={disabled}
                      aria-invalid={!!err?.text}
                      aria-describedby={err?.text ? `q-${i}-text-error` : undefined}
                      {...register(`questions.${i}.text`)}
                    />
                    {err?.text && (
                      <p id={`q-${i}-text-error`} className="mt-1 text-caption text-danger" role="alert">
                        {err.text.message}
                      </p>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <label className="flex flex-col gap-0.5 text-caption text-fg-muted">
                      Answer type
                      <Select disabled={disabled} {...register(`questions.${i}.type`)}>
                        {Object.entries(TYPE_LABEL).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </Select>
                    </label>
                    <label className="flex flex-col gap-0.5 text-caption text-fg-muted">
                      Follow up
                      <Select disabled={disabled} {...register(`questions.${i}.followup_policy`)}>
                        {Object.entries(FOLLOWUP_LABEL).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </Select>
                    </label>
                    <label className="flex flex-col gap-0.5 text-caption text-fg-muted">
                      Max follow-ups
                      <Select disabled={disabled} {...register(`questions.${i}.max_followups`)}>
                        {[0, 1, 2, 3].map((n) => (
                          <option key={n} value={n}>
                            {n}
                          </option>
                        ))}
                      </Select>
                    </label>
                    <label className="flex items-center gap-2 self-end pb-1.5 text-meta">
                      <input
                        type="checkbox"
                        className="size-4 accent-[var(--teal-600)]"
                        disabled={disabled}
                        {...register(`questions.${i}.required`)}
                      />
                      Required
                    </label>
                  </div>
                </div>
                {!disabled && (
                  <div className="flex shrink-0 flex-col gap-0.5">
                    <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move question ${i + 1} up`} disabled={i === 0} onClick={() => moveTo(i, i - 1)}>
                      <ArrowUp />
                    </Button>
                    <Button type="button" size="icon-sm" variant="ghost" aria-label={`Move question ${i + 1} down`} disabled={i === fields.length - 1} onClick={() => moveTo(i, i + 1)}>
                      <ArrowDown />
                    </Button>
                    <Button type="button" size="icon-sm" variant="ghost" aria-label={`Remove question ${i + 1}`} onClick={() => remove(i)} disabled={fields.length === 1}>
                      <Trash2 />
                    </Button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {errors?.questions?.root?.message || errors?.questions?.message ? (
        <p className="text-caption text-danger" role="alert">
          {errors.questions.root?.message ?? errors.questions.message}
        </p>
      ) : null}
      {!disabled && fields.length < 8 && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start"
          onClick={() => append({ text: "", type: "text", required: false, followup_policy: "none", max_followups: 0 })}
        >
          <Plus /> Add question
        </Button>
      )}
    </div>
  );
}
