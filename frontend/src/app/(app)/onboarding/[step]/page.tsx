"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, CircleCheck, CircleDashed } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { IntegrationStatusBadge } from "@/components/ui/badge";
import { SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { IntegrationKind } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { describe, fromCron } from "@/lib/schedule/cron";
import { cn } from "@/lib/utils";
import { TeamFormFields } from "@/features/teams/NewTeamDialog";
import { MembersEditor } from "@/features/teams/MembersEditor";
import { QuestionsEditor } from "@/features/teams/QuestionsEditor";
import { ScheduleEditor } from "@/features/teams/ScheduleEditor";
import { useCurrentTeam } from "@/features/teams/current-team";

const STEPS = [
  { id: "org", label: "Organization" },
  { id: "integrations", label: "Integrations" },
  { id: "team", label: "Team" },
  { id: "members", label: "Members" },
  { id: "questions", label: "Questions" },
  { id: "schedule", label: "Schedule" },
  { id: "review", label: "Review" },
] as const;
type StepId = (typeof STEPS)[number]["id"];

const TEAM_KEY = "scrumbot.onboarding.team";
function useWizardTeam(): [string | null, (id: string) => void] {
  const [id, setId] = React.useState<string | null>(null);
  React.useEffect(() => {
    try {
      setId(window.sessionStorage.getItem(TEAM_KEY));
    } catch {
      /* ignore */
    }
  }, []);
  return [
    id,
    (v) => {
      setId(v);
      try {
        window.sessionStorage.setItem(TEAM_KEY, v);
      } catch {
        /* ignore */
      }
    },
  ];
}

function Stepper({ current }: { current: number }) {
  return (
    <nav aria-label="Setup progress" className="mb-4 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1">
        {STEPS.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={s.id} className="flex items-center gap-1">
              <span
                aria-current={active ? "step" : undefined}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-control px-2 text-meta font-medium",
                  active ? "bg-teal-50 text-teal-700" : done ? "text-fg" : "text-fg-muted",
                )}
              >
                <span
                  className={cn(
                    "inline-flex size-5 items-center justify-center rounded-full text-caption",
                    done ? "bg-teal-600 text-white" : active ? "border border-teal-600 text-teal-700" : "border border-border-strong",
                  )}
                >
                  {done ? <Check className="size-3" aria-label="done" /> : i + 1}
                </span>
                {s.label}
              </span>
              {i < STEPS.length - 1 && <ChevronRight className="size-3.5 text-fg-subtle" aria-hidden />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function Nav({ back, next, nextLabel = "Continue", nextDisabled }: { back?: string; next?: () => void; nextLabel?: string; nextDisabled?: boolean }) {
  return (
    <div className="mt-4 flex items-center justify-between">
      {back ? (
        <Button asChild variant="ghost">
          <Link href={`/onboarding/${back}`}>
            <ChevronLeft /> Back
          </Link>
        </Button>
      ) : (
        <span />
      )}
      {next && (
        <Button variant="primary" onClick={next} disabled={nextDisabled}>
          {nextLabel} <ChevronRight />
        </Button>
      )}
    </div>
  );
}

const orgSchema = z.object({ name: z.string().trim().min(2, "Organization name is required") });

function OrgStep({ go }: { go: (s: StepId) => void }) {
  const { me } = useAuth();
  const qc = useQueryClient();
  const form = useForm<z.infer<typeof orgSchema>>({ resolver: zodResolver(orgSchema), defaultValues: { name: me?.org_name ?? "" } });
  const onboard = useMutation({
    mutationFn: api.onboardOrg,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.me });
      go("integrations");
    },
  });
  return (
    <Card className="max-w-xl">
      <CardHeader title="Your organization" description="Signed in with Microsoft Entra ID — your tenant is already linked." />
      <form onSubmit={form.handleSubmit((v) => onboard.mutate(v))} className="flex flex-col gap-3 p-4" noValidate>
        <Field label="Organization name" htmlFor="ob-org" required error={form.formState.errors.name?.message}>
          <Input id="ob-org" aria-invalid={!!form.formState.errors.name} {...form.register("name")} />
        </Field>
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={onboard.isPending}>
            Continue <ChevronRight />
          </Button>
        </div>
      </form>
    </Card>
  );
}

function IntegrationsStep({ go }: { go: (s: StepId) => void }) {
  const qc = useQueryClient();
  const integrations = useQuery({ queryKey: qk.integrations.all, queryFn: api.integrations });
  const connect = useMutation({
    mutationFn: (kind: IntegrationKind) => api.connectIntegration(kind),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.integrations.all }),
  });
  const rows: { kind: IntegrationKind; required: boolean; why: string }[] = [
    { kind: "teams", required: true, why: "The bot joins your standup meeting" },
    { kind: "mail", required: true, why: "Reports and blocker alerts by email" },
    { kind: "jira", required: false, why: "Ticket context and said-vs-Jira checks" },
  ];
  const status = (k: IntegrationKind) => integrations.data?.find((i) => i.kind === k)?.status ?? "disconnected";
  const ready = rows.filter((r) => r.required).every((r) => status(r.kind) !== "disconnected");
  return (
    <>
      <Card className="max-w-xl">
        <CardHeader title="Connect your tools" />
        {integrations.isPending ? (
          <SkeletonRows rows={3} />
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((r) => {
              const integ = integrations.data?.find((i) => i.kind === r.kind);
              const st = status(r.kind);
              return (
                <li key={r.kind} className="flex items-center gap-3 px-4 py-3">
                  {st === "disconnected" ? <CircleDashed className="size-4 text-fg-subtle" aria-hidden /> : <CircleCheck className="size-4 text-teal-600" aria-hidden />}
                  <span className="min-w-0 flex-1">
                    <span className="block text-body font-medium">
                      {integ?.display_name ?? r.kind} {!r.required && <span className="text-caption font-normal text-fg-muted">(optional)</span>}
                    </span>
                    <span className="block text-caption text-fg-muted">{r.why}</span>
                  </span>
                  {st === "disconnected" ? (
                    <Button size="sm" variant="primary" onClick={() => connect.mutate(r.kind)} loading={connect.isPending && connect.variables === r.kind}>
                      Connect
                    </Button>
                  ) : (
                    <IntegrationStatusBadge status={st} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <Nav back="org" next={() => go("team")} nextDisabled={!ready} />
    </>
  );
}

function TeamStep({ go, teamId, setTeamId }: { go: (s: StepId) => void; teamId: string | null; setTeamId: (id: string) => void }) {
  const { setTeamId: selectTeam } = useCurrentTeam();
  const team = useQuery({ queryKey: qk.teams.detail(teamId ?? ""), queryFn: () => api.team(teamId!), enabled: !!teamId, retry: false });
  return (
    <>
      <Card className="max-w-xl">
        <CardHeader title="Create a team" description="One standup per team. You can add more teams later." />
        <div className="p-4">
          {team.data ? (
            <p className="flex items-center gap-2 text-meta">
              <CircleCheck className="size-4 text-teal-600" aria-hidden /> Using <span className="font-medium">{team.data.name}</span>, led by{" "}
              {team.data.lead_name}.
            </p>
          ) : (
            <TeamFormFields
              submitLabel="Create team and continue"
              onCreated={(t) => {
                setTeamId(t.id);
                selectTeam(t.id);
                go("members");
              }}
            />
          )}
        </div>
      </Card>
      <Nav back="integrations" next={team.data ? () => go("members") : undefined} />
    </>
  );
}

function ReviewStep({ teamId }: { teamId: string }) {
  const router = useRouter();
  const team = useQuery({ queryKey: qk.teams.detail(teamId), queryFn: () => api.team(teamId) });
  const members = useQuery({ queryKey: qk.teams.members(teamId), queryFn: () => api.members(teamId) });
  const templates = useQuery({ queryKey: qk.teams.templates(teamId), queryFn: () => api.templates(teamId) });
  const schedule = useQuery({ queryKey: qk.teams.schedule(teamId), queryFn: () => api.schedule(teamId), retry: false });
  const active = templates.data?.find((t) => t.is_active);
  const items = [
    { ok: !!team.data, label: "Team", value: team.data?.name, step: "team" },
    { ok: (members.data?.length ?? 0) > 0, label: "Members", value: members.data?.map((m) => m.display_name.split(" ")[0]).join(", "), step: "members" },
    { ok: !!active, label: "Questions", value: active ? `${active.questions.length} questions (v${active.version})` : undefined, step: "questions" },
    { ok: !!schedule.data, label: "Schedule", value: schedule.data ? `${describe(fromCron(schedule.data.cron))} · ${schedule.data.timezone}` : undefined, step: "schedule" },
  ];
  const ready = items.every((i) => i.ok);
  return (
    <>
      <Card className="max-w-xl">
        <CardHeader title="Ready to go" description="The bot will join the recurring Teams meeting at the scheduled time." />
        <ul className="divide-y divide-border">
          {items.map((i) => (
            <li key={i.label} className="flex items-center gap-3 px-4 py-2.5">
              {i.ok ? <CircleCheck className="size-4 text-teal-600" aria-hidden /> : <CircleDashed className="size-4 text-warning" aria-hidden />}
              <span className="w-24 text-meta text-fg-muted">{i.label}</span>
              <span className="min-w-0 flex-1 truncate text-meta">{i.value ?? "Not set"}</span>
              <Link href={`/onboarding/${i.step}`} className="link text-meta">
                Edit
              </Link>
            </li>
          ))}
        </ul>
      </Card>
      <Nav
        back="schedule"
        nextLabel="Finish setup"
        nextDisabled={!ready}
        next={() => {
          try {
            window.sessionStorage.removeItem(TEAM_KEY);
          } catch {
            /* ignore */
          }
          router.push(`/teams/${teamId}`);
        }}
      />
    </>
  );
}

export default function OnboardingPage() {
  const { step } = useParams<{ step: string }>();
  const router = useRouter();
  const [teamId, setTeamId] = useWizardTeam();
  const index = Math.max(0, STEPS.findIndex((s) => s.id === step));
  const go = (s: StepId) => router.push(`/onboarding/${s}`);
  const needsTeam = ["members", "questions", "schedule", "review"].includes(step);

  return (
    <>
      <PageHeader title="Set up Scrum Bot" description="About five minutes. Everything can be changed later." />
      <Stepper current={index} />
      {needsTeam && !teamId ? (
        <Card className="max-w-xl p-4 text-meta">
          Create a team first.{" "}
          <Link href="/onboarding/team" className="link">
            Go to the Team step
          </Link>
        </Card>
      ) : step === "org" ? (
        <OrgStep go={go} />
      ) : step === "integrations" ? (
        <IntegrationsStep go={go} />
      ) : step === "team" ? (
        <TeamStep go={go} teamId={teamId} setTeamId={setTeamId} />
      ) : step === "members" ? (
        <>
          <MembersEditor teamId={teamId!} />
          <Nav back="team" next={() => go("questions")} />
        </>
      ) : step === "questions" ? (
        <>
          <QuestionsEditor teamId={teamId!} />
          <Nav back="members" next={() => go("schedule")} />
        </>
      ) : step === "schedule" ? (
        <>
          <ScheduleEditor teamId={teamId!} compact />
          <Nav back="questions" next={() => go("review")} />
        </>
      ) : step === "review" ? (
        <ReviewStep teamId={teamId!} />
      ) : (
        <Card className="p-4 text-meta">
          Unknown step.{" "}
          <Link href="/onboarding/org" className="link">
            Start over
          </Link>
        </Card>
      )}
    </>
  );
}
