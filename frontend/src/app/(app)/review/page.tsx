"use client";

import * as React from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBar, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { Paginated, ReviewItem, ReviewKind } from "@/lib/api/types";
import { dateTimeInZone } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS: { kind: ReviewKind; label: string; help: string }[] = [
  { kind: "person_match", label: "Person matches", help: "The bot wasn't sure who a name referred to. Nothing is emailed until you confirm." },
  { kind: "blocker_match", label: "Blocker matches", help: "Possibly the same as an existing blocker. Confirm to avoid duplicate alerts." },
  { kind: "pm_writeback", label: "Jira updates", help: "Proposed ticket changes from what people said. Nothing is written to Jira without approval." },
];

function ReviewRow({ item }: { item: ReviewItem }) {
  const qc = useQueryClient();
  const [choice, setChoice] = React.useState(item.candidates[0]?.id ?? "");

  const removeOptimistically = async () => {
    await qc.cancelQueries({ queryKey: qk.review.all });
    const snapshots = qc.getQueriesData<Paginated<ReviewItem>>({ queryKey: qk.review.all });
    snapshots.forEach(([key, data]) => data && qc.setQueryData(key, { ...data, items: data.items.filter((r) => r.id !== item.id) }));
    return { snapshots };
  };
  const rollback = (_e: unknown, _v: unknown, ctx?: { snapshots: [readonly unknown[], Paginated<ReviewItem> | undefined][] }) =>
    ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
  const settle = () => {
    qc.invalidateQueries({ queryKey: qk.review.all });
    qc.invalidateQueries({ queryKey: qk.blockers.all });
  };

  const approve = useMutation({
    mutationFn: () => api.approveReview(item.id, choice),
    onMutate: removeOptimistically,
    onError: rollback,
    onSuccess: () => toast.success("Approved"),
    onSettled: settle,
  });
  const reject = useMutation({
    mutationFn: () => api.rejectReview(item.id),
    onMutate: removeOptimistically,
    onError: rollback,
    onSuccess: () => toast.success("Rejected"),
    onSettled: settle,
  });
  const busy = approve.isPending || reject.isPending;

  return (
    <li className="flex flex-col gap-3 px-4 py-3 lg:flex-row lg:items-start">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-body font-medium">“{item.raw_phrase}”</span>
          <Badge tone="outline">{item.team_name}</Badge>
          <span className="text-caption text-fg-muted">{dateTimeInZone(item.created_at, Intl.DateTimeFormat().resolvedOptions().timeZone)}</span>
        </div>
        <blockquote className="mt-1 border-l-2 border-border-strong pl-3 text-meta text-fg-muted">
          {item.evidence_speaker}: “{item.evidence_quote}”
          {item.session_id && (
            <>
              {" "}
              <Link href={`/standups/${item.session_id}`} className="link">
                open standup
              </Link>
            </>
          )}
        </blockquote>
      </div>
      <fieldset className="flex w-full flex-col gap-1.5 lg:w-96">
        <legend className="sr-only">Choose a match for “{item.raw_phrase}”</legend>
        {item.candidates.map((c) => (
          <label
            key={c.id}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-control border px-2.5 py-1.5",
              choice === c.id ? "border-teal-600 bg-teal-50" : "border-border hover:bg-surface-muted",
            )}
          >
            <input type="radio" name={`cand-${item.id}`} value={c.id} checked={choice === c.id} onChange={() => setChoice(c.id)} className="accent-[var(--teal-600)]" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-meta font-medium">{c.label}</span>
              {c.sublabel && <span className="block truncate text-caption text-fg-muted">{c.sublabel}</span>}
            </span>
            <ConfidenceBar value={c.confidence} />
          </label>
        ))}
        <div className="flex justify-end gap-2 pt-1">
          <Button size="sm" variant="ghost" onClick={() => reject.mutate()} disabled={busy}>
            Reject
          </Button>
          <Button size="sm" variant="primary" onClick={() => approve.mutate()} disabled={busy || !choice} loading={approve.isPending}>
            Approve
          </Button>
        </div>
      </fieldset>
    </li>
  );
}

export default function ReviewPage() {
  const items = useQuery({ queryKey: qk.review.list(), queryFn: () => api.reviewItems() });
  const count = (k: ReviewKind) => items.data?.items.filter((i) => i.kind === k).length ?? 0;

  return (
    <>
      <PageHeader title="Review queue" description="Low-confidence decisions wait here so the wrong person is never emailed." />
      <Tabs defaultValue="person_match">
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.kind} value={t.kind}>
              {t.label}
              {count(t.kind) > 0 && <span className="tabular rounded-control bg-warning-bg px-1.5 text-caption text-warning">{count(t.kind)}</span>}
            </TabsTrigger>
          ))}
        </TabsList>
        {TABS.map((t) => (
          <TabsContent key={t.kind} value={t.kind}>
            <p className="mb-2 text-meta text-fg-muted">{t.help}</p>
            <Card>
              <QueryState query={items}>
                {(d) => {
                  const list = d.items.filter((i) => i.kind === t.kind);
                  return list.length === 0 ? (
                    <EmptyState icon={CheckCheck} title="All caught up" description="Nothing needs your review." />
                  ) : (
                    <ul className="divide-y divide-border">
                      {list.map((i) => (
                        <ReviewRow key={i.id} item={i} />
                      ))}
                    </ul>
                  );
                }}
              </QueryState>
            </Card>
          </TabsContent>
        ))}
      </Tabs>
    </>
  );
}
