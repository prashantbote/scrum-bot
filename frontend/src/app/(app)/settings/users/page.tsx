"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { DataTable } from "@/components/ui/data-table";
import { Avatar, Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/primitives";
import { QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { Role, User } from "@/lib/api/types";
import { ROLE_LABEL } from "@/lib/rbac/roles";
import { useAuth } from "@/lib/auth/AuthProvider";

function RoleSelect({ user }: { user: User }) {
  const { me } = useAuth();
  const qc = useQueryClient();
  const update = useMutation({
    mutationFn: (role: Role) => api.updateUser(user.id, { role }),
    onSuccess: (u) => {
      toast.success(`${u.display_name} is now ${ROLE_LABEL[u.role]}`);
      qc.invalidateQueries({ queryKey: qk.users.all });
    },
  });
  return (
    <Select
      aria-label={`Role for ${user.display_name}`}
      className="h-7 w-36 text-meta"
      value={user.role}
      disabled={update.isPending || user.id === me?.id}
      title={user.id === me?.id ? "You can't change your own role" : undefined}
      onChange={(e) => update.mutate(e.target.value as Role)}
    >
      {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
        <option key={r} value={r}>
          {ROLE_LABEL[r]}
        </option>
      ))}
    </Select>
  );
}

function EraseButton({ user }: { user: User }) {
  const erase = useMutation({
    mutationFn: () => api.eraseUser(user.id),
    onSuccess: () => toast.success(`Erasure completed for ${user.display_name}`),
  });
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label={`Erase data for ${user.display_name}`}>
          <Trash2 />
        </Button>
      </DialogTrigger>
      <DialogContent title={`Erase ${user.display_name}'s standup data?`} description="Data subject request (DPDP Act / GDPR)">
        <p className="text-meta text-fg-muted">
          Their transcript text is redacted and their extracted updates are deleted. Team-level aggregates are kept. This
          can&apos;t be undone and is recorded in the audit log.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <DialogClose asChild>
            <Button variant="danger" onClick={() => erase.mutate()}>
              Erase data
            </Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const columns: ColumnDef<User, unknown>[] = [
  {
    accessorKey: "display_name",
    header: "Name",
    cell: ({ row }) => (
      <span className="flex items-center gap-2">
        <Avatar name={row.original.display_name} size={24} />
        <span>
          <span className="block font-medium">{row.original.display_name}</span>
          <span className="block text-caption text-fg-muted">{row.original.email}</span>
        </span>
      </span>
    ),
  },
  { accessorKey: "department", header: "Department", cell: ({ getValue }) => getValue<string | null>() ?? "—" },
  { accessorKey: "aliases", header: "Aliases", enableSorting: false, cell: ({ getValue }) => <span className="text-fg-muted">{getValue<string[]>().join(", ") || "—"}</span> },
  { accessorKey: "role", header: "Role", cell: ({ row }) => <RoleSelect user={row.original} /> },
  { id: "actions", header: "", enableSorting: false, cell: ({ row }) => <EraseButton user={row.original} /> },
];

export default function UsersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = React.useState("");
  const users = useQuery({ queryKey: qk.users.list(), queryFn: () => api.users() });
  const sync = useMutation({
    mutationFn: api.syncUsers,
    onSuccess: (r) => {
      toast.success(`Directory synced: ${r.added} added, ${r.updated} updated`);
      qc.invalidateQueries({ queryKey: qk.users.all });
    },
  });
  const term = search.trim().toLowerCase();

  return (
    <Card>
      <CardHeader
        title="Users & roles"
        description="People are synced from Microsoft Entra ID. Roles control what each person can see and change."
        action={
          <Button size="sm" variant="secondary" onClick={() => sync.mutate()} loading={sync.isPending}>
            <RefreshCw /> Sync from Entra
          </Button>
        }
      />
      <div className="border-b border-border px-4 py-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by name or email"
            aria-label="Filter users"
            className="h-control w-full rounded-control border border-border-strong bg-surface pl-8 pr-2 text-body placeholder:text-fg-subtle focus-visible:border-blue-600"
          />
        </div>
      </div>
      <QueryState query={users}>
        {(d) => (
          <DataTable
            caption="Users"
            columns={columns}
            data={d.items.filter((u) => !term || u.display_name.toLowerCase().includes(term) || u.email.includes(term))}
            getRowId={(u) => u.id}
          />
        )}
      </QueryState>
    </Card>
  );
}
