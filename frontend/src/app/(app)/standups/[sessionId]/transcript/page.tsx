"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Avatar } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/badge";
import { EmptyState, QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import { offset } from "@/lib/format";
import { useAuth } from "@/lib/auth/AuthProvider";
import { cn } from "@/lib/utils";

export default function TranscriptPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { me } = useAuth();
  const transcript = useQuery({ queryKey: qk.sessions.transcript(sessionId), queryFn: () => api.transcript(sessionId) });
  const [speaker, setSpeaker] = React.useState("");
  const [question, setQuestion] = React.useState("");
  const [hash, setHash] = React.useState("");

  React.useEffect(() => {
    const read = () => setHash(window.location.hash.slice(1));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  // Scroll the evidence segment into view once loaded.
  React.useEffect(() => {
    if (!hash || !transcript.data) return;
    document.getElementById(hash)?.scrollIntoView({ block: "center" });
  }, [hash, transcript.data]);

  const segs = transcript.data ?? [];
  const speakers = [...new Set(segs.map((s) => s.speaker_label))];
  const questions = [...new Map(segs.filter((s) => s.question_id).map((s) => [s.question_id!, s.question_text!])).entries()];
  const shown = segs.filter((s) => (!speaker || s.speaker_label === speaker) && (!question || s.question_id === question));

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <label className="sr-only" htmlFor="tr-speaker">Filter by speaker</label>
        <Select id="tr-speaker" className="w-44" value={speaker} onChange={(e) => setSpeaker(e.target.value)}>
          <option value="">All speakers</option>
          {speakers.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
        <label className="sr-only" htmlFor="tr-question">Filter by question</label>
        <Select id="tr-question" className="w-64" value={question} onChange={(e) => setQuestion(e.target.value)}>
          <option value="">All questions</option>
          {questions.map(([id, text]) => (
            <option key={id} value={id}>{text}</option>
          ))}
        </Select>
        {me?.role === "member" && <Badge tone="outline">Showing your own answers only</Badge>}
        <span className="ml-auto text-caption text-fg-muted">{shown.length} segments</span>
      </div>
      <QueryState
        query={transcript}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No transcript" description="This standup has no recorded transcript (async-only or retention expired)." />}
      >
        {() => (
          <ol className="divide-y divide-border">
            {shown.map((s) => {
              const isBot = !s.speaker_user_id;
              const highlighted = s.id === hash;
              return (
                <li
                  key={s.id}
                  id={s.id}
                  className={cn("flex gap-3 px-4 py-2.5 scroll-mt-20", highlighted && "bg-blue-50 ring-1 ring-inset ring-blue-600")}
                  aria-current={highlighted ? "location" : undefined}
                >
                  <span className="tabular w-11 shrink-0 pt-0.5 text-caption text-fg-muted">{offset(s.start_ms)}</span>
                  {isBot ? (
                    <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-teal-50 text-teal-700" aria-hidden>
                      <Bot className="size-4" />
                    </span>
                  ) : (
                    <Avatar name={s.speaker_label} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("text-meta font-medium", isBot && "text-teal-700")}>{s.speaker_label}</span>
                      {s.question_text && <Badge tone="outline">{s.question_text}</Badge>}
                      {!isBot && s.confidence < 0.9 && <span className="text-caption text-fg-muted">STT {Math.round(s.confidence * 100)}%</span>}
                    </div>
                    <p className={cn("text-body", isBot && "text-fg-muted")}>{s.text}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </QueryState>
    </Card>
  );
}
