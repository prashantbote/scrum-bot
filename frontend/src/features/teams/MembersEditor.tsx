"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GripVertical, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { TeamMember, User } from "@/lib/api/types";
import { useCan } from "@/lib/rbac/Can";
import { useUnsavedChanges } from "@/lib/hooks/useUnsavedChanges";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/ui/primitives";
import { MemberPicker } from "@/components/forms/MemberPicker";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { cn } from "@/lib/utils";

type Row = Pick<TeamMember, "user_id" | "display_name" | "email" | "department" | "pm_account_id"> & {
  aliases: string;
  originalAliases: string;
};

const toRow = (m: TeamMember): Row => ({
  user_id: m.user_id,
  display_name: m.display_name,
  email: m.email,
  department: m.department,
  pm_account_id: m.pm_account_id,
  aliases: m.aliases.join(", "),
  originalAliases: m.aliases.join(", "),
});

export function MembersEditor({ teamId, onSaved }: { teamId: string; onSaved?: () => void }) {
  const qc = useQueryClient();
  const canEdit = useCan("team.configure", { teamId });
  const members = useQuery({ queryKey: qk.teams.members(teamId), queryFn: () => api.members(teamId) });
  const [rows, setRows] = React.useState<Row[] | null>(null);
  const [dirty, setDirty] = React.useState(false);
  const [dragFrom, setDragFrom] = React.useState<number | null>(null);
  useUnsavedChanges(dirty);

  React.useEffect(() => {
    if (members.data && !dirty) setRows(members.data.map(toRow));
  }, [members.data, dirty]);

  const update = (fn: (r: Row[]) => Row[]) => {
    setRows((r) => fn(r ?? []));
    setDirty(true);
  };
  const move = (from: number, to: number) =>
    update((r) => {
      if (to < 0 || to >= r.length) return r;
      const next = [...r];
      const [x] = next.splice(from, 1);
      next.splice(to, 0, x!);
      return next;
    });

  const save = useMutation({
    mutationFn: async (list: Row[]) => {
      const changed = list.filter((r) => r.aliases !== r.originalAliases);
      await Promise.all(
        changed.map((r) =>
          api.updateUser(r.user_id, { aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean) }),
        ),
      );
      return api.setMembers(
        teamId,
        list.map((r, i) => ({ user_id: r.user_id, speaking_order: i + 1, pm_account_id: r.pm_account_id || null })),
      );
    },
    onSuccess: (saved) => {
      setDirty(false);
      setRows(saved.map(toRow));
      qc.setQueryData(qk.teams.members(teamId), saved);
      qc.invalidateQueries({ queryKey: qk.teams.all });
      toast.success("Members saved");
      onSaved?.();
    },
  });

  const addUser = (u: User) =>
    update((r) => [
      ...r,
      { user_id: u.id, display_name: u.display_name, email: u.email, department: u.department, pm_account_id: null, aliases: u.aliases.join(", "), originalAliases: u.aliases.join(", ") },
    ]);

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader
          title="Speaking order"
          description="The bot calls on people in this order. Aliases and Jira IDs improve name and ticket recognition."
          action={
            canEdit && (
              <Button variant="primary" size="sm" disabled={!dirty} loading={save.isPending} onClick={() => rows && save.mutate(rows)}>
                Save members
              </Button>
            )
          }
        />
        <QueryState query={members}>
          {() =>
            !rows || rows.length === 0 ? (
              <EmptyState title="No members yet" description="Add people from your directory." />
            ) : (
              <ol className="divide-y divide-border">
                {rows.map((r, i) => (
                  <li
                    key={r.user_id}
                    draggable={canEdit}
                    onDragStart={() => setDragFrom(i)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (dragFrom !== null) move(dragFrom, i);
                      setDragFrom(null);
                    }}
                    className={cn("flex flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-center", dragFrom === i && "bg-teal-50")}
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      {canEdit && <GripVertical className="size-4 shrink-0 cursor-grab text-fg-subtle" aria-hidden />}
                      <span className="tabular w-4 text-meta text-fg-muted">{i + 1}</span>
                      <Avatar name={r.display_name} />
                      <span className="min-w-0">
                        <span className="block truncate text-body font-medium">{r.display_name}</span>
                        <span className="block truncate text-caption text-fg-muted">{r.department ?? "—"}</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-2 pl-6 sm:pl-0">
                      <label className="sr-only" htmlFor={`jira-${r.user_id}`}>
                        Jira account for {r.display_name}
                      </label>
                      <Input
                        id={`jira-${r.user_id}`}
                        className="w-32 font-mono text-meta"
                        placeholder="Jira account"
                        value={r.pm_account_id ?? ""}
                        disabled={!canEdit}
                        onChange={(e) => update((rs) => rs.map((x) => (x.user_id === r.user_id ? { ...x, pm_account_id: e.target.value } : x)))}
                      />
                      <label className="sr-only" htmlFor={`alias-${r.user_id}`}>
                        Aliases for {r.display_name}
                      </label>
                      <Input
                        id={`alias-${r.user_id}`}
                        className="w-40"
                        placeholder="Aliases, comma separated"
                        value={r.aliases}
                        disabled={!canEdit}
                        onChange={(e) => update((rs) => rs.map((x) => (x.user_id === r.user_id ? { ...x, aliases: e.target.value } : x)))}
                      />
                      {canEdit && (
                        <span className="flex">
                          <Button size="icon-sm" variant="ghost" aria-label={`Move ${r.display_name} up`} disabled={i === 0} onClick={() => move(i, i - 1)}>
                            <ArrowUp />
                          </Button>
                          <Button size="icon-sm" variant="ghost" aria-label={`Move ${r.display_name} down`} disabled={i === rows.length - 1} onClick={() => move(i, i + 1)}>
                            <ArrowDown />
                          </Button>
                          <Button size="icon-sm" variant="ghost" aria-label={`Remove ${r.display_name}`} onClick={() => update((rs) => rs.filter((x) => x.user_id !== r.user_id))}>
                            <Trash2 />
                          </Button>
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )
          }
        </QueryState>
      </Card>
      {canEdit && (
        <Card>
          <CardHeader title="Add people" description="From your Microsoft Entra directory" />
          <div className="p-4">
            <MemberPicker excludeIds={(rows ?? []).map((r) => r.user_id)} onAdd={addUser} />
          </div>
        </Card>
      )}
    </div>
  );
}
