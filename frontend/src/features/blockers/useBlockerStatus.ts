"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import type { Blocker, BlockerStatus, Paginated } from "@/lib/api/types";

/** Optimistic blocker status change, rolled back with a toast on failure (plan §6). */
export function useBlockerStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: BlockerStatus }) => api.patchBlocker(id, { status }),
    meta: { silent: true },
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: qk.blockers.all });
      const snapshots = qc.getQueriesData<Paginated<Blocker>>({ queryKey: ["blockers", "list"] });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        qc.setQueryData<Paginated<Blocker>>(key, {
          ...data,
          items: data.items.map((b) => (b.id === id ? { ...b, status } : b)),
        });
      }
      return { snapshots };
    },
    onError: (err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
      toast.error(err instanceof Error ? `Couldn't update blocker: ${err.message}` : "Couldn't update blocker");
    },
    onSuccess: (_b, { status }) => {
      toast.success(status === "resolved" ? "Blocker resolved" : status === "acknowledged" ? "Blocker acknowledged" : "Blocker reopened");
    },
    onSettled: (_d, _e, { id }) => {
      qc.invalidateQueries({ queryKey: qk.blockers.all });
      qc.invalidateQueries({ queryKey: qk.blockers.detail(id) });
      qc.invalidateQueries({ queryKey: qk.metrics.all });
    },
  });
}
