"use client";

import { useParams } from "next/navigation";
import { ScheduleEditor } from "@/features/teams/ScheduleEditor";

export default function TeamSchedulePage() {
  const { teamId } = useParams<{ teamId: string }>();
  return <ScheduleEditor teamId={teamId} />;
}