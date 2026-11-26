"use client";

import * as React from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Bot, CheckCircle2, Clock, Eye, Check, XCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/input";
import { BlockerStatusBadge, TicketChip } from "@/components/ui/badge";
import { SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import type { ActionPreview, BlockerAction } from "@/lib/api/types";
import { longDate, plural } from "@/lib/format";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-start px-4 py-10 sm:justify-center">
      <div className="mb-4 flex items-center gap-2 text-meta text-fg-muted">
        <span className="inline-flex size-6 items-center justify-center rounded-control bg-teal-600 text-white">
          <Bot className="size-3.5" aria-hidden />
        </span>
        Scrum Bot
      </div>
      <Card className="w-full max-w-md p-5">{children}</Card>
    </main>
  );
}

function Outcome({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-4 text-center" role="status">
      {icon}
      <h1 className="text-section font-semibold">{title}</h1>
      <p className="text-meta text-fg-muted">{body}</p>
    </div>
  );
}

function BlockerActionView({ token, preview }: { token: string; preview: ActionPreview }) {
  const qc = useQueryClient();
  const b = preview.blocker!;
  const [done, setDone] = React.useState<BlockerAction | null>(null);
  const act = useMutation({
    mutationFn: (action: BlockerAction) => api.performAction(token, action),
    meta: { silent: true },
    onSuccess: (_r, action) => {
      setDone(action);
      qc.invalidateQueries({ queryKey: qk.actions.preview(token) });
    },
  });

  if (done === "resolve" || (preview.already_done && !done)) {
    return (
      <Outcome
        icon={<CheckCircle2 className="size-8 text-teal-600" aria-hidden />}
        title={done ? "Marked as resolved" : "Already resolved"}
        body={done ? `Thanks! ${b.reporter_name} and the scrum lead have been notified.` : "Someone already resolved this blocker. No action needed."}
      />
    );
  }
  if (done === "acknowledge") {
    return (
      <div className="flex flex-col gap-3">
        <Outcome
          icon={<Eye className="size-8 text-blue-600" aria-hidden />}
          title="Acknowledged"
          body={`${b.reporter_name} can see you're on it. Come back to this link when it's resolved.`}
        />
        <Button variant="primary" className="w-full" onClick={() => act.mutate("resolve")} loading={act.isPending}>
          <Check /> Mark as resolved
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="label-caps">Blocker · {b.team_name}</p>
        <h1 className="mt-1 text-section font-semibold">{b.description}</h1>
        <p className="mt-1 text-meta text-fg-muted">
          Reported by {b.reporter_name} · open {plural(b.days_open, "day")}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <BlockerStatusBadge status={b.status} />
          {b.ticket_keys.map((t) => (
            <TicketChip key={t} ticketKey={t} />
          ))}
        </div>
      </div>
      {act.isError && (
        <p role="alert" className="rounded-control bg-danger-bg px-3 py-2 text-meta text-danger">
          {act.error instanceof Error ? act.error.message : "Couldn't update the blocker."}
        </p>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        {preview.allowed_actions.includes("acknowledge") && (
          <Button variant="info" className="h-10 w-full sm:w-auto sm:flex-1" onClick={() => act.mutate("acknowledge")} disabled={act.isPending}>
            <Eye /> Acknowledge
          </Button>
        )}
        {preview.allowed_actions.includes("resolve") && (
          <Button variant="primary" className="h-10 w-full sm:w-auto sm:flex-1" onClick={() => act.mutate("resolve")} disabled={act.isPending}>
            <Check /> Mark as resolved
          </Button>
        )}
      </div>
      <p className="text-caption text-fg-muted">This link was sent only to you and works without signing in.</p>
    </div>
  );
}

function CheckinForm({ token, preview }: { token: string; preview: ActionPreview }) {
  const c = preview.checkin!;
  const { register, handleSubmit, setError, formState } = useForm<Record<string, string>>();
  const submit = useMutation({
    mutationFn: (answers: Record<string, string>) => api.submitCheckin(token, answers),
    meta: { silent: true },
    onError: (err) => {
      if (err instanceof ApiError) {
        for (const [field, message] of Object.entries(err.fieldErrors())) setError(field, { message });
        if (!err.problem.errors) setError("root", { message: err.message });
      }
    },
  });

  if (submit.isSuccess || preview.already_done) {
    return (
      <Outcome
        icon={<CheckCircle2 className="size-8 text-teal-600" aria-hidden />}
        title={submit.isSuccess ? "Update sent" : "Already submitted"}
        body={submit.isSuccess ? "Your answers will appear in today's report. Thanks!" : "You've already sent today's update."}
      />
    );
  }

  return (
    <form onSubmit={handleSubmit((v) => submit.mutate(v))} className="flex flex-col gap-4" noValidate>
      <div>
        <p className="label-caps">Async check-in · {c.team_name}</p>
        <h1 className="mt-1 text-section font-semibold">Hi {c.member_name.split(" ")[0]}, you missed today&apos;s standup</h1>
        <p className="text-meta text-fg-muted">{longDate(c.run_date)} · takes about a minute</p>
      </div>
      {c.questions.map((q) => (
        <Field key={q.id} label={q.text} htmlFor={q.id} required={q.required} error={formState.errors[q.id]?.message}>
          <Textarea
            id={q.id}
            rows={2}
            aria-invalid={!!formState.errors[q.id]}
            aria-describedby={formState.errors[q.id] ? `${q.id}-error` : undefined}
            {...register(q.id, { required: q.required ? "This answer is required" : false })}
          />
        </Field>
      ))}
      {formState.errors.root && (
        <p role="alert" className="rounded-control bg-danger-bg px-3 py-2 text-meta text-danger">
          {formState.errors.root.message}
        </p>
      )}
      <Button type="submit" variant="primary" className="h-10" loading={submit.isPending}>
        Send update
      </Button>
    </form>
  );
}

export default function ActionPage() {
  const { token } = useParams<{ token: string }>();
  const search = useSearchParams();
  const preview = useQuery({
    queryKey: qk.actions.preview(token),
    queryFn: () => api.actionPreview(token),
    retry: false,
  });

  return (
    <Shell>
      {preview.isPending ? (
        <SkeletonRows rows={4} />
      ) : preview.isError ? (
        <Outcome
          icon={<XCircle className="size-8 text-danger" aria-hidden />}
          title="Link not recognised"
          body={preview.error instanceof Error ? preview.error.message : "This link is invalid."}
        />
      ) : preview.data.expired ? (
        <Outcome
          icon={<Clock className="size-8 text-warning" aria-hidden />}
          title="This link has expired"
          body={
            preview.data.kind === "checkin"
              ? "The async window for this standup has closed."
              : "Links expire after 7 days. Open the blocker in Scrum Bot to update it."
          }
        />
      ) : preview.data.kind === "checkin" || search.get("type") === "checkin" ? (
        <CheckinForm token={token} preview={preview.data} />
      ) : (
        <BlockerActionView token={token} preview={preview.data} />
      )}
    </Shell>
  );
}
