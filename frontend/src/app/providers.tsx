"use client";

import * as React from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster, toast } from "sonner";
import { Loader2 } from "lucide-react";
import { TooltipProvider } from "@/components/ui/primitives";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { ApiError } from "@/lib/api/client";
import { config } from "@/lib/config";
import { CurrentTeamProvider } from "@/features/teams/current-team";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      },
    },
    mutationCache: new MutationCache({
      onError: (err, _vars, _ctx, mutation) => {
        // Mutations with their own onError (forms mapping field errors) opt out via meta.
        if (mutation.meta?.silent) return;
        toast.error(err instanceof Error ? err.message : "Something went wrong");
      },
    }),
  });
}

/** In mock mode, start MSW before anything fetches. */
function MockGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(config.mode !== "mock");
  React.useEffect(() => {
    if (config.mode !== "mock") return;
    let cancelled = false;
    import("@mocks/browser")
      .then(({ worker }) =>
        worker.start({ onUnhandledRequest: "bypass", quiet: true, serviceWorker: { url: "/mockServiceWorker.js" } }),
      )
      .then(() => !cancelled && setReady(true))
      .catch((err) => {
        console.error("Failed to start mock API", err);
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-meta text-fg-muted" aria-busy="true">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Starting Scrum Bot…
      </div>
    );
  }
  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <MockGate>
        <AuthProvider>
          <CurrentTeamProvider>
            <TooltipProvider>{children}</TooltipProvider>
          </CurrentTeamProvider>
        </AuthProvider>
      </MockGate>
      <Toaster
        position="bottom-right"
        toastOptions={{
          className: "!rounded-card !border !border-border !bg-surface !text-body !text-fg !shadow-popover",
        }}
      />
    </QueryClientProvider>
  );
}
