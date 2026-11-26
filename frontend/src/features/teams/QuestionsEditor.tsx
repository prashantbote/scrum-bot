"use client";

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, MessageSquareText, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { QuestionTemplate } from "@/lib/api/types";
import { useCan } from "@/lib/rbac/Can";
import { useUnsavedChanges } from "@/lib/hooks/useUnsavedChanges";
import { shortDate } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/primitives";
import { QueryState } from "@/components/feedback/states";
import {
  DEFAULT_QUESTIONS,
  QuestionListEditor,
  templateSchema,
  type TemplateForm,
} from "@/components/forms/QuestionListEditor";

const toForm = (t?: QuestionTemplate): TemplateForm => ({
  questions: t
    ? t.questions.map(({ text, type, required, followup_policy, max_followups }) => ({ text, type, required, followup_policy, max_followups }))
    : DEFAULT_QUESTIONS,
});

function AgentPreview({ form }: { form: TemplateForm }) {
  const lines: { who: "bot" | "member"; text: string }[] = [
    { who: "bot", text: "Good morning, everyone! This standup is being recorded for notes. Let's start with Rahul." },
  ];
  form.questions.forEach((q, i) => {
    lines.push({ who: "bot", text: i === 0 ? `Rahul, ${q.text.charAt(0).toLowerCase()}${q.text.slice(1)}` : q.text });
    lines.push({ who: "member", text: "…" });
    if (q.followup_policy !== "none" && q.max_followups > 0)
      lines.push({
        who: "bot",
        text: q.followup_policy === "always" ? "(always asks one follow-up)" : `(asks up to ${q.max_followups} follow-up${q.max_followups > 1 ? "s" : ""} if the answer is vague)`,
      });
  });
  lines.push({ who: "bot", text: "So: … Correct?  (reads back a one-line summary)" });
  return (
    <ol className="flex flex-col gap-2">
      {lines.map((l, i) => (
        <li key={i} className={l.who === "bot" ? "self-start" : "self-end"}>
          <span
            className={
              l.who === "bot"
                ? "inline-block rounded-card bg-teal-50 px-3 py-1.5 text-meta text-teal-700"
                : "inline-block rounded-card bg-surface-muted px-3 py-1.5 text-meta text-fg-muted"
            }
          >
            <span className="sr-only">{l.who === "bot" ? "Scrum Bot: " : "Member: "}</span>
            {l.text}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function QuestionsEditor({ teamId, onSaved }: { teamId: string; onSaved?: () => void }) {
  const qc = useQueryClient();
  const canEdit = useCan("team.configure", { teamId });
  const templates = useQuery({ queryKey: qk.teams.templates(teamId), queryFn: () => api.templates(teamId) });
  const active = templates.data?.find((t) => t.is_active);

  const form = useForm<TemplateForm>({ resolver: zodResolver(templateSchema), defaultValues: toForm(undefined) });
  const { isDirty, errors } = form.formState;
  useUnsavedChanges(isDirty);

  React.useEffect(() => {
    if (templates.data) form.reset(toForm(templates.data.find((t) => t.is_active)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates.data]);

  const save = useMutation({
    mutationFn: (v: TemplateForm) => api.createTemplate(teamId, { questions: v.questions.map((q, i) => ({ ...q, position: i + 1 })) }),
    onSuccess: (tpl) => {
      toast.success(`Saved as version ${tpl.version}. It applies from the next standup.`);
      qc.invalidateQueries({ queryKey: qk.teams.templates(teamId) });
      qc.invalidateQueries({ queryKey: qk.teams.all });
      onSaved?.();
    },
  });
  const restore = useMutation({
    mutationFn: api.activateTemplate,
    onSuccess: (tpl) => {
      toast.success(`Version ${tpl.version} is active again`);
      qc.invalidateQueries({ queryKey: qk.teams.templates(teamId) });
    },
  });

  return (
    <Card>
      <CardHeader
        title={active ? `Questions · version ${active.version}` : "Questions"}
        description="Templates are versioned, so old reports always show the questions that were actually asked."
        action={
          <>
            <Dialog>
              <DialogTrigger asChild>
                <Button size="sm" variant="ghost">
                  <MessageSquareText /> Preview as agent
                </Button>
              </DialogTrigger>
              <DialogContent title="How the bot will ask" description="Example for the first member.">
                <AgentPreview form={form.watch()} />
              </DialogContent>
            </Dialog>
            <Dialog>
              <DialogTrigger asChild>
                <Button size="sm" variant="ghost">
                  <History /> History
                </Button>
              </DialogTrigger>
              <DialogContent side="right" title="Version history" description="Restore an older version if needed.">
                <ul className="flex flex-col gap-3">
                  {(templates.data ?? []).map((t) => (
                    <li key={t.id} className="rounded-card border border-border p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-body font-medium">Version {t.version}</span>
                        {t.is_active ? (
                          <Badge tone="teal">Active</Badge>
                        ) : (
                          canEdit && (
                            <Button size="sm" variant="secondary" onClick={() => restore.mutate(t.id)} loading={restore.isPending && restore.variables === t.id}>
                              <RotateCcw /> Restore
                            </Button>
                          )
                        )}
                      </div>
                      <p className="text-caption text-fg-muted">
                        {t.created_by_name} · {shortDate(t.created_at.slice(0, 10))}
                      </p>
                      <ol className="mt-2 list-decimal pl-4 text-meta">
                        {t.questions.map((q) => (
                          <li key={q.id}>{q.text}</li>
                        ))}
                      </ol>
                    </li>
                  ))}
                </ul>
              </DialogContent>
            </Dialog>
          </>
        }
      />
      <QueryState query={templates}>
        {() => (
          <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="flex flex-col gap-3 p-4" noValidate>
            <QuestionListEditor control={form.control} register={form.register} errors={errors} disabled={!canEdit} />
            {canEdit && (
              <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
                {isDirty && <span className="mr-auto text-caption text-fg-muted">Unsaved changes</span>}
                <Button type="button" variant="ghost" disabled={!isDirty} onClick={() => form.reset(toForm(active))}>
                  Discard
                </Button>
                <Button type="submit" variant="primary" loading={save.isPending} disabled={!isDirty && !!active}>
                  {active ? "Save as new version" : "Save questions"}
                </Button>
              </div>
            )}
          </form>
        )}
      </QueryState>
    </Card>
  );
}
