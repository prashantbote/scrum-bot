"use client";

import * as React from "react";
import Link from "next/link";
import { Play } from "lucide-react";
import { Card } from "@/components/ui/card";
import { AttendanceBadge, Badge, SeverityDot, TicketChip } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/primitives";
import type { AttendanceStatus, MemberUpdate, TranscriptSegment, WorkItem } from "@/lib/api/types";
import { offset } from "@/lib/format";

const PREVIEW = 3;

function EvidenceLink({
  ids,
  sessionId,
  segments,
}: {
  ids: string[];
  sessionId: string;
  segments?: Map<string, TranscriptSegment>;
}) {
  const first = ids[0];
  if (!first) return null;
  const seg = segments?.get(first);
  return (
    <Link
      href={`/standups/${sessionId}/transcript#${first}`}
      className="link inline-flex items-center gap-0.5 text-caption"
      aria-label={`Play evidence${seg ? ` at ${offset(seg.start_ms)}` : ""} in transcript`}
    >
      <Play className="size-3" aria-hidden />
      {seg ? offset(seg.start_ms) : "source"}
    </Link>
  );
}

function MiniList({
  title,
  items,
  sessionId,
  segments,
}: {
  title: string;
  items: { text: string; tickets: string[]; evidence: string[]; dot?: React.ReactNode }[];
  sessionId: string;
  segments?: Map<string, TranscriptSegment>;
}) {
  const [open, setOpen] = React.useState(false);
  if (items.length === 0) return null;
  const shown = open ? items : items.slice(0, PREVIEW);
  return (
    <div>
      <div className="label-caps mb-1">{title}</div>
      <ul className="flex flex-col gap-1">
        {shown.map((i, idx) => (
          <li key={idx} className="text-meta leading-6">
            {i.dot && <span className="mr-1.5 inline-flex align-middle">{i.dot}</span>}
            <span>{i.text}</span>
            {i.tickets.map((t) => (
              <span key={t} className="ml-1.5 inline-flex align-middle">
                <TicketChip ticketKey={t} />
              </span>
            ))}
            <span className="ml-1.5 inline-flex align-middle">
              <EvidenceLink ids={i.evidence} sessionId={sessionId} segments={segments} />
            </span>
          </li>
        ))}
      </ul>
      {items.length > PREVIEW && (
        <button type="button" className="link mt-1 text-caption" onClick={() => setOpen((v) => !v)}>
          {open ? "Show less" : `${items.length - PREVIEW} more`}
        </button>
      )}
    </div>
  );
}

const toItems = (xs: WorkItem[]) =>
  xs.map((x) => ({ text: x.summary, tickets: x.ticket_keys, evidence: x.evidence_segment_ids }));

/** One member's update: Done / Today / Blockers, ticket chips and evidence links into the transcript. */
export function MemberUpdateCard({
  update,
  sessionId,
  segments,
}: {
  update: MemberUpdate | { member_id: string; display_name: string; attendance: AttendanceStatus; missing: true };
  sessionId: string;
  segments?: Map<string, TranscriptSegment>;
}) {
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2">
        <Avatar name={update.display_name} />
        <span className="min-w-0 flex-1 truncate text-body font-medium">{update.display_name}</span>
        <AttendanceBadge status={update.attendance} />
      </div>
      {"missing" in update ? (
        <p className="text-meta text-fg-muted">No update — didn&apos;t join and didn&apos;t answer the async check-in.</p>
      ) : (
        <>
          <MiniList title="Done" items={toItems(update.completed)} sessionId={sessionId} segments={segments} />
          <MiniList title="Today" items={toItems(update.planned)} sessionId={sessionId} segments={segments} />
          <MiniList
            title="Blockers"
            sessionId={sessionId}
            segments={segments}
            items={update.blockers.map((b) => ({
              text: b.blocked_on_raw ? `${b.description} — waiting on ${b.blocked_on_raw}` : b.description,
              tickets: b.ticket_keys,
              evidence: b.evidence_segment_ids,
              dot: <SeverityDot severity={b.severity} />,
            }))}
          />
          {update.dependencies.length > 0 && (
            <MiniList
              title="Dependencies"
              sessionId={sessionId}
              segments={segments}
              items={update.dependencies.map((d) => ({
                text: `${d.description} — on ${d.on_raw}`,
                tickets: d.ticket_keys,
                evidence: d.evidence_segment_ids,
              }))}
            />
          )}
          {update.challenges.length > 0 && (
            <div>
              <div className="label-caps mb-1">Notes</div>
              <ul className="list-disc pl-4 text-meta">
                {update.challenges.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {update.source === "async" && (
            <Badge tone="blue" className="self-start">
              Answered via async check-in
            </Badge>
          )}
        </>
      )}
    </Card>
  );
}
