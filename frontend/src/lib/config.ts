/**
 * mock — MSW serves a seeded API in the browser; persona sign-in. No backend needed.
 * api  — the real backend (SCRUM_AUTH_MODE=dev) with the same persona sign-in (X-Mock-User).
 * live — the real backend with OIDC bearer tokens (MSAL / Entra ID).
 */
export type AppMode = "mock" | "api" | "live";

const rawMode = process.env.NEXT_PUBLIC_APP_MODE;

export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "/api/v1",
  mode: (rawMode === "live" || rawMode === "api" ? rawMode : "mock") as AppMode,
  entra: {
    clientId: process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID ?? "",
    authority: process.env.NEXT_PUBLIC_ENTRA_AUTHORITY ?? "https://login.microsoftonline.com/organizations",
    apiScope: process.env.NEXT_PUBLIC_ENTRA_API_SCOPE ?? "",
  },
} as const;
