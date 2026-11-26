"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/lib/auth/AuthProvider";
import { canVisit } from "@/lib/rbac/roles";

/**
 * Authenticated area. Tokens live client-side (MSAL), so the guard runs on the client:
 * signed-out users go to /login, users without the route's capability go to /dashboard.
 * The API enforces the same rules server-side.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { status, me } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const allowed = canVisit(me, pathname);

  React.useEffect(() => {
    if (status === "signed-out") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (status === "signed-in" && !allowed) {
      toast.info("You don't have access to that page.");
      router.replace("/dashboard");
    }
  }, [status, allowed, pathname, router]);

  if (status !== "signed-in" || !allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-meta text-fg-muted" aria-busy="true">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Loading…
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
