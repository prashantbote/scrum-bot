"use client";

import { useParams } from "next/navigation";
import { QuestionsEditor } from "@/features/teams/QuestionsEditor";

export default function TeamQuestionsPage() {
  const { teamId } = useParams<{ teamId: string }>();
  return <QuestionsEditor teamId={teamId} />;
}