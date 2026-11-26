"use client";

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import type { OrgSettings } from "@/lib/api/types";
import { useUnsavedChanges } from "@/lib/hooks/useUnsavedChanges";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { QueryState } from "@/components/feedback/states";

export const orgSchema = z.object({
  name: z.string().trim().min(2, "Organization name is required"),
  consent_text: z.string().trim().min(10, "The bot must announce recording; keep a short sentence").max(300),
  escalation_days: z.coerce.number().int().min(1).max(14),
  retention_days_audio: z.coerce.number().int().min(0).max(30),
  retention_days_transcript: z.coerce.number().int().min(1, "Must be at least 1 day").max(730),
});
type OrgForm = z.infer<typeof orgSchema>;

/** `section` picks which fields to show: organization basics or privacy/retention. */
export function OrgSettingsForm({ section }: { section: "org" | "retention" }) {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: qk.org.settings, queryFn: api.orgSettings });
  const form = useForm<OrgForm>({ resolver: zodResolver(orgSchema) });
  const { errors, isDirty } = form.formState;
  useUnsavedChanges(isDirty);

  React.useEffect(() => {
    if (settings.data) form.reset(settings.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (v: Partial<OrgSettings>) => api.updateOrgSettings(v),
    meta: { silent: true },
    onSuccess: (s) => {
      qc.setQueryData(qk.org.settings, s);
      form.reset(s);
      toast.success("Settings saved");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        const fields = err.fieldErrors();
        Object.entries(fields).forEach(([f, m]) => form.setError(f as keyof OrgForm, { message: m }));
        if (!Object.keys(fields).length) toast.error(err.message);
      }
    },
  });

  return (
    <Card className="max-w-2xl">
      <CardHeader title={section === "org" ? "Organization" : "Privacy & retention"} />
      <QueryState query={settings}>
        {() => (
          <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="flex flex-col gap-4 p-4" noValidate>
            {section === "org" ? (
              <>
                <Field label="Organization name" htmlFor="org-name" required error={errors.name?.message}>
                  <Input id="org-name" aria-invalid={!!errors.name} {...form.register("name")} />
                </Field>
                <Field
                  label="Escalate blockers after"
                  htmlFor="org-esc"
                  hint="Open blockers older than this are escalated to the scrum lead once."
                  error={errors.escalation_days?.message}
                >
                  <Select id="org-esc" className="w-40" {...form.register("escalation_days")}>
                    {[1, 2, 3, 5, 7].map((d) => (
                      <option key={d} value={d}>
                        {d} day{d > 1 ? "s" : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
              </>
            ) : (
              <>
                <Field
                  label="Recording announcement"
                  htmlFor="org-consent"
                  required
                  hint="Spoken by the bot at the start of every standup. Teams also shows the recording indicator."
                  error={errors.consent_text?.message}
                >
                  <Textarea id="org-consent" rows={2} aria-invalid={!!errors.consent_text} {...form.register("consent_text")} />
                </Field>
                <Field label="Keep raw audio" htmlFor="org-audio" hint="0 = audio is never stored; only the transcript is kept." error={errors.retention_days_audio?.message}>
                  <Select id="org-audio" className="w-48" {...form.register("retention_days_audio")}>
                    {[0, 1, 7, 30].map((d) => (
                      <option key={d} value={d}>
                        {d === 0 ? "Don't store audio" : `${d} day${d > 1 ? "s" : ""}`}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Keep transcripts" htmlFor="org-transcript" hint="Summaries and reports follow the same policy." error={errors.retention_days_transcript?.message}>
                  <Input id="org-transcript" type="number" min={1} max={730} className="w-32" aria-invalid={!!errors.retention_days_transcript} {...form.register("retention_days_transcript")} />
                </Field>
                <p className="rounded-control bg-surface-muted p-3 text-caption text-fg-muted">
                  Data subject requests (DPDP Act / GDPR): erase a person&apos;s transcript text and updates from{" "}
                  <a href="/settings/users" className="link">
                    Users &amp; roles
                  </a>
                  .
                </p>
              </>
            )}
            <div className="flex justify-end gap-2 border-t border-border pt-3">
              <Button type="button" variant="ghost" disabled={!isDirty} onClick={() => settings.data && form.reset(settings.data)}>
                Discard
              </Button>
              <Button type="submit" variant="primary" disabled={!isDirty} loading={save.isPending}>
                Save
              </Button>
            </div>
          </form>
        )}
      </QueryState>
    </Card>
  );
}
