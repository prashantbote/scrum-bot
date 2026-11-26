"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";
import { ApiError, setExtraHeaders, setTokenProvider } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import type { Me } from "@/lib/api/types";
import { config } from "@/lib/config";

export type AuthStatus = "loading" | "signed-out" | "signed-in";

interface AuthContextValue {
  status: AuthStatus;
  me: Me | null;
  /** Mock/api mode: persona key (e.g. "u-neha"). Live mode: ignored (MSAL redirect). */
  signIn: (personaUserId?: string) => Promise<void>;
  signOut: () => void;
  mode: typeof config.mode;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Convenience for components that only render when signed in. */
export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("useMe called while signed out");
  return me;
}

/* ------------------------------------------------------------------ */
/* Mock & api modes: persona stored locally, sent as X-Mock-User       */
/* (to MSW in mock mode, to the backend's dev auth in api mode).       */
/* ------------------------------------------------------------------ */

const PERSONA_KEY = "scrumbot.persona";

function readPersona(): string | null {
  try {
    return window.localStorage.getItem(PERSONA_KEY);
  } catch {
    return null;
  }
}

function MockAuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [persona, setPersona] = React.useState<string | null | undefined>(undefined);

  React.useEffect(() => {
    setPersona(readPersona());
  }, []);

  React.useEffect(() => {
    setExtraHeaders((): Record<string, string> => {
      const id = readPersona();
      return id ? { "X-Mock-User": id } : {};
    });
    setTokenProvider(async () => null);
  }, []);

  const meQuery = useQuery({
    queryKey: [...qk.me, persona],
    queryFn: api.me,
    enabled: !!persona,
    retry: false,
    staleTime: Infinity,
  });

  const value = React.useMemo<AuthContextValue>(() => {
    const status: AuthStatus =
      persona === undefined || (persona && meQuery.isPending)
        ? "loading"
        : persona && meQuery.data
          ? "signed-in"
          : "signed-out";
    return {
      status,
      me: meQuery.data ?? null,
      mode: config.mode,
      signIn: async (id) => {
        if (!id) return;
        try {
          window.localStorage.setItem(PERSONA_KEY, id);
        } catch {
          /* private mode: persona lives in memory only */
        }
        queryClient.clear();
        setPersona(id);
      },
      signOut: () => {
        try {
          window.localStorage.removeItem(PERSONA_KEY);
        } catch {
          /* ignore */
        }
        queryClient.clear();
        setPersona(null);
      },
    };
  }, [persona, meQuery.isPending, meQuery.data, queryClient]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/* ------------------------------------------------------------------ */
/* Live mode: Microsoft Entra ID via MSAL (lazy-loaded)                 */
/* ------------------------------------------------------------------ */

const LiveAuthProvider = React.lazy(() => import("./LiveAuthProvider"));

export function AuthProvider({ children }: { children: React.ReactNode }) {
  if (config.mode === "live") {
    return (
      <React.Suspense fallback={null}>
        <LiveAuthProvider Context={AuthContext}>{children}</LiveAuthProvider>
      </React.Suspense>
    );
  }
  return <MockAuthProvider>{children}</MockAuthProvider>;
}

export type { AuthContextValue };
export { ApiError };
