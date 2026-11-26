"use client";

import { useParams } from "next/navigation";
import { MembersEditor } from "@/features/teams/MembersEditor";

export default function TeamMembersPage() {
  const { teamId } = useParams<{ teamId: string }>();
  return <MembersEditor teamId={teamId} />;
}