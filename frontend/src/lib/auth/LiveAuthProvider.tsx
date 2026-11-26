"use client";

import * as React from "react";
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
} from "@azure/msal-browser";
import { MsalProvider, useMsal } from "@azure/msal-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";
import { setTokenProvider } from "@/lib/api/client";
import { qk } from "@/lib/api/queryKeys";
import { config } from "@/lib/config";
import type { AuthContextValue } from "./AuthProvider";

const scopes = config.entra.apiScope ? [config.entra.apiScope] : [];

let pca: PublicClientApplication | null = null;
function getPca() {
  pca ??= new PublicClientApplication({
    auth: {
      clientId: config.entra.clientId,
      authority: config.entra.authority,
      redirectUri: typeof window !== "undefined" ? `${window.location.origin}/login` : undefined,
      postLogoutRedirectUri: typeof window !== "undefined" ? `${window.location.origin}/login` : undefined,
    },
    cache: { cacheLocation: "sessionStorage" },
  });
  return pca;
}

function Bridge({
  Context,
  children,
}: {
  Context: React.Context<AuthContextValue | null>;
  children: React.ReactNode;
}) {
  const { instance, accounts, inProgress } = useMsal();
  const queryClient = useQueryClient();
  const account: AccountInfo | undefined = accounts[0];

  React.useEffect(() => {
    setTokenProvider(async () => {
      const active = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
      if (!active) return null;
      try {
        const res = await instance.acquireTokenSilent({ scopes, account: active });
        return res.accessToken;
      } catch (err) {
        if (err instanceof InteractionRequiredAuthError) {
          await instance.acquireTokenRedirect({ scopes, account: active });
        }
        throw err;
      }
    });
  }, [instance]);

  React.useEffect(() => {
    if (account && !instance.getActiveAccount()) instance.setActiveAccount(account);
  }, [account, instance]);

  const meQuery = useQuery({
    queryKey: [...qk.me, account?.homeAccountId],
    queryFn: api.me,
    enabled: !!account && inProgress === "none",
    retry: false,
    staleTime: Infinity,
  });

  const value = React.useMemo<AuthContextValue>(
    () => ({
      status:
        inProgress !== "none" || (account && meQuery.isPending)
          ? "loading"
          : account && meQuery.data
            ? "signed-in"
            : "signed-out",
      me: meQuery.data ?? null,
      mode: "live",
      signIn: async () => {
        await instance.loginRedirect({ scopes });
      },
      signOut: () => {
        queryClient.clear();
        void instance.logoutRedirect();
      },
    }),
    [inProgress, account, meQuery.isPending, meQuery.data, instance, queryClient],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export default function LiveAuthProvider({
  Context,
  children,
}: {
  Context: React.Context<AuthContextValue | null>;
  children: React.ReactNode;
}) {
  const instance = getPca();
  const [ready, setReady] = React.useState(false);
  React.useEffect(() => {
    instance
      .initialize()
      .then(() => instance.handleRedirectPromise())
      .finally(() => setReady(true));
  }, [instance]);
  if (!ready) return null;
  return (
    <MsalProvider instance={instance}>
      <Bridge Context={Context}>{children}</Bridge>
    </MsalProvider>
  );
}
