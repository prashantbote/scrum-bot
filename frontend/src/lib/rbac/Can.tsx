"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { can, type Action, type Scope } from "./roles";

/** Renders children only when the signed-in user may perform `action` (optionally scoped). */
export function Can({
  action,
  team,
  user,
  fallback = null,
  children,
}: {
  action: Action;
  team?: string;
  user?: string;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { me } = useAuth();
  return <>{can(me, action, { teamId: team, userId: user }) ? children : fallback}</>;
}

export function useCan(action: Action, scope?: Scope): boolean {
  const { me } = useAuth();
  return can(me, action, scope);
}
