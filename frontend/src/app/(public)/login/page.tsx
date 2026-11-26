"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Bot, ChevronRight, ExternalLink, ShieldCheck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_LABEL } from "@/lib/rbac/roles";
import { PERSONAS, userById } from "@mocks/data/people";
import { apiFetch } from "@/lib/api/client";

function MicrosoftMark() {
  // Four-square mark drawn with token colors (no brand hex in components).
  return (
    <span aria-hidden className="grid size-4 grid-cols-2 gap-px">
      <span className="bg-danger" />
      <span className="bg-teal-600" />
      <span className="bg-blue-600" />
      <span className="bg-warning" />
    </span>
  );
}

const DEMO_LINKS = [
  { href: "/a/demo-priya-review", label: "Blocker alert link (Arjun → Priya's review)" },
  { href: "/a/demo-rahul-sandbox", label: "Already-resolved link (Amit → Rahul)" },
  { href: "/a/demo-expired", label: "Expired link" },
  { href: "/a/demo-checkin-karan?type=checkin", label: "Async check-in (Karan)" },
];

/** In api mode the backend mints fresh signed links into its seeded story (dev auth only). */
function useDemoLinks(mode: string) {
  const live = useQuery({
    queryKey: ["dev", "demo-links"],
    queryFn: () => apiFetch<{ label: string; href: string }[]>("/dev/demo-links", { anonymous: true }),
    enabled: mode === "api",
    staleTime: 60_000,
    retry: false,
  });
  return mode === "mock" ? DEMO_LINKS : (live.data ?? []);
}

function LoginInner() {
  const { status, signIn, mode } = useAuth();
  const demoLinks = useDemoLinks(mode);
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const [pending, setPending] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (status === "signed-in") router.replace(next.startsWith("/") ? next : "/dashboard");
  }, [status, next, router]);

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="flex w-full max-w-md flex-col gap-4">
        <div className="flex items-center gap-2">
          <span className="inline-flex size-9 items-center justify-center rounded-card bg-teal-600 text-white">
            <Bot className="size-5" aria-hidden />
          </span>
          <div>
            <h1 className="text-title font-semibold">Scrum Bot</h1>
            <p className="text-meta text-fg-muted">AI standups for Microsoft Teams</p>
          </div>
        </div>

        <Card className="p-5">
          <h2 className="text-section font-semibold">Sign in</h2>
          <p className="mt-1 text-meta text-fg-muted">Use your work account. Scrum Bot uses Microsoft Entra ID single sign-on.</p>

          {mode === "live" ? (
            <Button variant="secondary" className="mt-4 w-full" onClick={() => signIn()} loading={status === "loading"}>
              <MicrosoftMark /> Sign in with Microsoft
            </Button>
          ) : (
            <>
              <div className="mt-4 flex items-center gap-2">
                <span className="label-caps">Demo personas</span>
                <Badge tone="outline">{mode === "api" ? "Dev sign-in" : "Mock mode"}</Badge>
              </div>
              <ul className="mt-2 flex flex-col gap-2">
                {PERSONAS.map((p) => {
                  const u = userById(p.userId);
                  return (
                    <li key={p.userId}>
                      <button
                        type="button"
                        disabled={!!pending}
                        onClick={async () => {
                          setPending(p.userId);
                          await signIn(p.userId);
                        }}
                        className="flex w-full items-center gap-3 rounded-card border border-border bg-surface px-3 py-2 text-left transition-colors hover:border-teal-600 hover:bg-teal-50 disabled:opacity-60"
                      >
                        <Avatar name={u.display_name} size={32} />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2 text-body font-medium">
                            {u.display_name}
                            <span className="text-caption font-normal text-fg-muted">{ROLE_LABEL[u.role]}</span>
                          </span>
                          <span className="block truncate text-caption text-fg-muted">{p.blurb}</span>
                        </span>
                        <ChevronRight className="size-4 text-fg-subtle" aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          <div className="mt-4 flex items-start gap-2 rounded-control bg-surface-muted p-3 text-caption text-fg-muted">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-teal-600" aria-hidden />
            <p>
              First sign-in for your organization? A tenant admin must grant consent for the Teams meeting and mail permissions
              Scrum Bot uses. Standups are announced and marked as recorded for every attendee.
            </p>
          </div>
        </Card>

        {demoLinks.length > 0 && (
          <Card className="p-4">
            <h2 className="label-caps">Email links (no sign-in needed)</h2>
            <ul className="mt-2 flex flex-col gap-1">
              {demoLinks.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="link inline-flex items-center gap-1 text-meta">
                    {l.label} <ExternalLink className="size-3" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginInner />
    </React.Suspense>
  );
}
