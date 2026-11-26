"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KanbanSquare, Mail, PlugZap, ShieldCheck, Video, Workflow } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, Section } from "@/components/layout/PageHeader";
import { StatusCard } from "@/components/cards/StatusCard";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/primitives";
import { QueryState, SkeletonRows } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { Integration, IntegrationKind } from "@/lib/api/types";
import { relativeDays } from "@/lib/format";
import { config } from "@/lib/config";

const ICON: Record<IntegrationKind, React.ReactNode> = {
  teams: <Video className="size-4" />,
  jira: <KanbanSquare className="size-4" />,
  mail: <Mail className="size-4" />,
  ado: <Workflow className="size-4" />,
};

const PURPOSE: Record<IntegrationKind, string> = {
  teams: "Bot joins the recurring standup meeting and sends async check-in cards.",
  jira: "Preloads each member's open tickets and checks what was said against ticket status.",
  mail: "Sends the daily digest, blocker alerts and escalations.",
  ado: "Alternative to Jira for teams on Azure Boards.",
};

const GRAPH_PERMISSIONS = [
  ["Calls.JoinGroupCall.All", "Join the standup meeting as a participant"],
  ["Calls.AccessMedia.All", "Hear and speak in the call"],
  ["OnlineMeetings.ReadWrite.All", "Create the recurring standup meeting"],
  ["Calendars.ReadWrite", "Send the calendar invite to members"],
  ["Mail.Send", "Send reports and blocker alerts from the service mailbox"],
] as const;

function IntegrationRow({ integ }: { integ: Integration }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: qk.integrations.all });
  const connect = useMutation({
    mutationFn: () => api.connectIntegration(integ.kind),
    onSuccess: (r) => {
      if (config.mode !== "mock" && r.authorize_url) {
        window.location.href = r.authorize_url; // OAuth consent, returns to /integrations/{kind}/callback
        return;
      }
      toast.success(`${integ.display_name} connected`);
      refresh();
    },
  });
  const test = useMutation({
    mutationFn: () => api.testIntegration(integ.id),
    onSuccess: (r) => {
      toast.success(`${r.display_name}: connection OK`);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteIntegration(integ.id),
    onSuccess: () => {
      toast.success(`${integ.display_name} disconnected`);
      refresh();
    },
  });
  const connected = integ.status !== "disconnected";

  return (
    <StatusCard
      icon={ICON[integ.kind]}
      name={integ.display_name}
      detail={connected ? integ.detail : PURPOSE[integ.kind]}
      status={integ.status}
      lastChecked={integ.last_checked_at ? relativeDays(integ.last_checked_at) : null}
      actions={
        connected ? (
          <>
            {integ.status === "expiring" || integ.status === "error" ? (
              <Button size="sm" variant="primary" onClick={() => connect.mutate()} loading={connect.isPending}>
                Reconnect
              </Button>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => test.mutate()} loading={test.isPending}>
                Test
              </Button>
            )}
            <Dialog>
              <DialogTrigger asChild>
                <Button size="sm" variant="ghost">
                  Disconnect
                </Button>
              </DialogTrigger>
              <DialogContent title={`Disconnect ${integ.display_name}?`}>
                <p className="text-meta text-fg-muted">
                  {integ.kind === "teams"
                    ? "Scheduled standups will fail until Teams is reconnected."
                    : integ.kind === "mail"
                      ? "Reports and blocker alerts will stop being emailed."
                      : "The bot will stop preloading tickets and mismatch checks will stop."}{" "}
                  The stored token is deleted.
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <DialogClose asChild>
                    <Button variant="ghost">Cancel</Button>
                  </DialogClose>
                  <DialogClose asChild>
                    <Button variant="danger" onClick={() => remove.mutate()}>
                      Disconnect
                    </Button>
                  </DialogClose>
                </div>
              </DialogContent>
            </Dialog>
          </>
        ) : (
          <Button size="sm" variant="primary" onClick={() => connect.mutate()} loading={connect.isPending}>
            <PlugZap /> Connect
          </Button>
        )
      }
    />
  );
}

export default function IntegrationsPage() {
  const integrations = useQuery({ queryKey: qk.integrations.all, queryFn: api.integrations });
  return (
    <>
      <PageHeader title="Integrations" description="Tokens are envelope-encrypted and refreshed automatically before they expire." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section title="Connections" className="xl:col-span-2">
          <QueryState query={integrations} loading={<SkeletonRows rows={4} />}>
            {(list) => (
              <div className="flex flex-col gap-2">
                {list.map((i) => (
                  <IntegrationRow key={i.id} integ={i} />
                ))}
              </div>
            )}
          </QueryState>
        </Section>
        <Section title="Microsoft Graph consent">
          <Card className="p-4">
            <p className="flex items-start gap-2 text-meta text-fg-muted">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-teal-600" aria-hidden />
              A tenant admin approved these permissions. Scrum Bot requests nothing beyond this list.
            </p>
            <ul className="mt-3 flex flex-col gap-2">
              {GRAPH_PERMISSIONS.map(([perm, why]) => (
                <li key={perm}>
                  <code className="ticket">{perm}</code>
                  <p className="mt-0.5 text-caption text-fg-muted">{why}</p>
                </li>
              ))}
            </ul>
          </Card>
        </Section>
      </div>
    </>
  );
}
