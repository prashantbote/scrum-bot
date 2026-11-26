"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { User } from "@/lib/api/types";
import { Avatar } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";

/** Search the org directory (synced from Entra ID) and add people to a team. */
export function MemberPicker({ excludeIds, onAdd }: { excludeIds: string[]; onAdd: (u: User) => void }) {
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 200);
    return () => clearTimeout(t);
  }, [search]);

  const users = useQuery({ queryKey: qk.users.list(debounced), queryFn: () => api.users({ search: debounced }) });
  const results = (users.data?.items ?? []).filter((u) => !excludeIds.includes(u.id) && u.role !== "viewer").slice(0, 6);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search people in your directory"
          aria-label="Search people to add"
          className="h-control w-full rounded-control border border-border-strong bg-surface pl-8 pr-2 text-body placeholder:text-fg-subtle focus-visible:border-blue-600"
        />
      </div>
      <ul className="flex flex-col divide-y divide-border rounded-card border border-border" aria-label="Directory results">
        {results.length === 0 ? (
          <li className="px-3 py-2 text-meta text-fg-muted">{users.isPending ? "Searching…" : "No one else matches."}</li>
        ) : (
          results.map((u) => (
            <li key={u.id} className="flex items-center gap-2 px-3 py-1.5">
              <Avatar name={u.display_name} size={24} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-meta font-medium">{u.display_name}</span>
                <span className="block truncate text-caption text-fg-muted">
                  {u.department ?? "—"} · {u.email}
                </span>
              </span>
              <Button type="button" size="sm" variant="secondary" onClick={() => onAdd(u)} aria-label={`Add ${u.display_name}`}>
                <Plus /> Add
              </Button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
