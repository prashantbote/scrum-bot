"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";
import { qk, STALE } from "@/lib/api/queryKeys";
import type { Team } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";

interface CurrentTeam {
  teamId: string | null;
  team: Team | null;
  teams: Team[];
  isLoading: boolean;
  setTeamId: (id: string) => void;
}

const Ctx = React.createContext<CurrentTeam | null>(null);
const KEY = "scrumbot.team";

/** The team switcher's selection, shared by Dashboard, Standups and Blockers. */
export function CurrentTeamProvider({ children }: { children: React.ReactNode }) {
  const { me, status } = useAuth();
  const teamsQuery = useQuery({
    queryKey: qk.teams.list(),
    queryFn: api.teams,
    enabled: status === "signed-in",
    staleTime: STALE.config,
  });
  const [selected, setSelected] = React.useState<string | null>(null);

  React.useEffect(() => {
    try {
      setSelected(window.localStorage.getItem(KEY));
    } catch {
      /* ignore */
    }
  }, []);

  const teams = React.useMemo(() => teamsQuery.data?.items ?? [], [teamsQuery.data]);
  const fallback = teams.find((t) => me?.lead_team_ids.includes(t.id)) ?? teams[0] ?? null;
  const team = teams.find((t) => t.id === selected) ?? fallback;

  const value = React.useMemo<CurrentTeam>(
    () => ({
      teamId: team?.id ?? null,
      team: team ?? null,
      teams,
      isLoading: teamsQuery.isPending,
      setTeamId: (id) => {
        setSelected(id);
        try {
          window.localStorage.setItem(KEY, id);
        } catch {
          /* ignore */
        }
      },
    }),
    [team, teams, teamsQuery.isPending],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCurrentTeam(): CurrentTeam {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useCurrentTeam must be used inside <CurrentTeamProvider>");
  return ctx;
}
