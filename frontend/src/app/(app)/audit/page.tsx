"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { AuditEntry } from "@/lib/api/types";
import { dateTimeInZone } from "@/lib/format";

const ENTITIES = ["", "team", "schedule", "question_template", "integration", "user", "blocker", "notification", "review_item", "organization"];
const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

const columns: ColumnDef<AuditEntry, unknown>[] = [
  { accessorKey: "at", header: "When", cell: ({ getValue }) => <span className="tabular">{dateTimeInZone(getValue<string>(), tz(), "d MMM yyyy, HH:mm")}</span> },
  { accessorKey: "actor_name", header: "Actor" },
  { accessorKey: "action", header: "Action", cell: ({ getValue }) => <code className="font-mono text-[12px]">{getValue<string>()}</code> },
  { accessorKey: "entity_type", header: "Entity", cell: ({ row }) => <Badge tone="outline">{row.original.entity_type}</Badge> },
  { accessorKey: "entity_id", header: "ID", cell: ({ getValue }) => <span className="text-fg-muted">{getValue<string>()}</span> },
];

export default function AuditPage() {
  const [entity, setEntity] = React.useState("");
  const [actor, setActor] = React.useState("");
  const [debouncedActor, setDebouncedActor] = React.useState("");
  const [open, setOpen] = React.useState<AuditEntry | null>(null);
  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedActor(actor.trim()), 250);
    return () => clearTimeout(t);
  }, [actor]);
  const q = { entity: entity || undefined, actor: debouncedActor || undefined };
  const log = useQuery({ queryKey: qk.audit.list(q), queryFn: () => api.auditLog(q) });

  return (
    <>
      <PageHeader title="Audit log" description="Every configuration change and every outbound email. Append-only." />
      <Card>
        <div className="flex flex-wrap gap-2 border-b border-border px-4 py-2">
          <label className="sr-only" htmlFor="a-entity">Entity type</label>
          <Select id="a-entity" className="w-48" value={entity} onChange={(e) => setEntity(e.target.value)}>
            {ENTITIES.map((e) => (
              <option key={e} value={e}>{e ? e.replace("_", " ") : "All entities"}</option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="a-actor">Actor</label>
          <Input id="a-actor" className="w-48" placeholder="Filter by actor" value={actor} onChange={(e) => setActor(e.target.value)} />
        </div>
        <QueryState query={log}>
          {(d) => (
            <DataTable
              caption="Audit log"
              columns={columns}
              data={d.items}
              getRowId={(a) => a.id}
              onRowClick={setOpen}
              empty="No entries match these filters."
            />
          )}
        </QueryState>
      </Card>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        {open && (
          <DialogContent side="right" title={open.action} description={`${open.actor_name} · ${dateTimeInZone(open.at, tz(), "d MMM yyyy, HH:mm:ss")}`}>
            <dl className="mb-3 grid grid-cols-[80px_1fr] gap-y-1 text-meta">
              <dt className="text-fg-muted">Entity</dt>
              <dd>{open.entity_type}</dd>
              <dt className="text-fg-muted">ID</dt>
              <dd className="break-all">{open.entity_id}</dd>
            </dl>
            <p className="label-caps mb-1">Change</p>
            <pre className="overflow-x-auto rounded-control border border-border bg-surface-muted p-3 font-mono text-[12px] leading-5">
              {JSON.stringify(open.diff, null, 2)}
            </pre>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
