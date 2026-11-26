"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import type { Team } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/primitives";
import { TimezoneSelect } from "@/components/forms/ScheduleFields";
import { useCurrentTeam } from "./current-team";

export const teamSchema = z.object({
  name: z.string().trim().min(2, "Team name must be at least 2 characters").max(60),
  lead_user_id: z.string().min(1, "Pick a scrum lead"),
  timezone: z.string().min(1),
});
export type TeamForm = z.infer<typeof teamSchema>;

/** Team create form, shared by the Teams page dialog and the onboarding wizard. */
export function TeamFormFields({
  onCreated,
  submitLabel = "Create team",
}: {
  onCreated: (team: Team) => void;
  submitLabel?: string;
}) {
  const { me } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: qk.users.list(), queryFn: () => api.users() });
  const leads = (users.data?.items ?? []).filter((u) => u.role === "scrum_lead" || u.role === "org_admin");
  const form = useForm<TeamForm>({
    resolver: zodResolver(teamSchema),
    defaultValues: { name: "", lead_user_id: me?.role === "scrum_lead" ? me.id : "", timezone: "Asia/Kolkata" },
  });
  const create = useMutation({
    mutationFn: api.createTeam,
    meta: { silent: true },
    onSuccess: (team) => {
      qc.invalidateQueries({ queryKey: qk.teams.all });
      toast.success(`Team "${team.name}" created`);
      onCreated(team);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        const fields = err.fieldErrors();
        if (fields.name) form.setError("name", { message: fields.name });
        else form.setError("root", { message: err.message });
      }
    },
  });
  const { errors } = form.formState;

  return (
    <form onSubmit={form.handleSubmit((v) => create.mutate(v))} className="flex flex-col gap-3" noValidate>
      <Field label="Team name" htmlFor="team-name" required error={errors.name?.message}>
        <Input id="team-name" placeholder="e.g. Payments" aria-invalid={!!errors.name} {...form.register("name")} />
      </Field>
      <Field label="Scrum lead" htmlFor="team-lead" required error={errors.lead_user_id?.message} hint="Receives the daily report and escalations.">
        <Select id="team-lead" aria-invalid={!!errors.lead_user_id} {...form.register("lead_user_id")}>
          <option value="">Select a person…</option>
          {leads.map((u) => (
            <option key={u.id} value={u.id}>
              {u.display_name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Time zone" htmlFor="team-tz" hint="Standup times and reports use this zone.">
        <Controller
          control={form.control}
          name="timezone"
          render={({ field }) => <TimezoneSelect id="team-tz" value={field.value} onChange={field.onChange} />}
        />
      </Field>
      {errors.root && (
        <p role="alert" className="text-caption text-danger">
          {errors.root.message}
        </p>
      )}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="submit" variant="primary" loading={create.isPending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

export function NewTeamDialog() {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const { setTeamId } = useCurrentTeam();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary">
          <Plus /> New team
        </Button>
      </DialogTrigger>
      <DialogContent title="New team" description="You'll add members, questions and a schedule next.">
        <TeamFormFields
          onCreated={(team) => {
            setOpen(false);
            setTeamId(team.id);
            router.push(`/teams/${team.id}/members`);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
