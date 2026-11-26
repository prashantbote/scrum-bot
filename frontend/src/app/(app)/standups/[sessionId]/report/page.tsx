"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Send } from "lucide-react";
import { toast } from "sonner";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { QueryState } from "@/components/feedback/states";
import { api } from "@/lib/api/endpoints";
import { qk } from "@/lib/api/queryKeys";
import { dateTimeInZone } from "@/lib/format";
import { Can } from "@/lib/rbac/Can";

export default function ReportPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const session = useQuery({ queryKey: qk.sessions.detail(sessionId), queryFn: () => api.session(sessionId) });
  const report = useQuery({ queryKey: qk.sessions.report(sessionId), queryFn: () => api.report(sessionId) });
  const iframe = React.useRef<HTMLIFrameElement>(null);
  const resend = useMutation({
    mutationFn: () => api.resendDigest(sessionId),
    onSuccess: (r) => toast.success(`Digest re-queued for ${r.queued} recipients`),
  });

  const downloadPdf = () => {
    if (report.data?.pdf_url) {
      window.open(report.data.pdf_url, "_blank", "noopener");
      return;
    }
    // No stored PDF (mock / not yet rendered): print the digest to PDF from the browser.
    iframe.current?.contentWindow?.print();
  };

  return (
    <Card>
      <CardHeader
        title="Daily report"
        description={
          report.data?.sent_at
            ? `Emailed ${dateTimeInZone(report.data.sent_at, Intl.DateTimeFormat().resolvedOptions().timeZone)} to ${report.data.recipients.join(", ")}`
            : "Not sent yet"
        }
        action={
          <>
            <Button size="sm" variant="secondary" onClick={downloadPdf} disabled={!report.data}>
              <Download /> PDF
            </Button>
            <Can action="team.configure" team={session.data?.team_id}>
              <Button size="sm" variant="secondary" onClick={() => resend.mutate()} loading={resend.isPending}>
                <Send /> Resend
              </Button>
            </Can>
          </>
        }
      />
      <QueryState query={report}>
        {(r) => (
          <iframe
            ref={iframe}
            title="Daily report email preview"
            srcDoc={r.html}
            sandbox="allow-same-origin allow-modals"
            className="h-[70vh] w-full rounded-b-card border-0 bg-bg"
          />
        )}
      </QueryState>
    </Card>
  );
}
