import type { Attendance, MemberUpdate } from "@/lib/api/types";
import { longDate } from "@/lib/format";

/** Mirrors the backend's Jinja2 digest: inline CSS, Enterprise Minimal colors. */
export function renderDigestHtml(opts: {
  teamName: string;
  date: string;
  attendance: Attendance[];
  updates: MemberUpdate[];
}): string {
  const { teamName, date, attendance, updates } = opts;
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  const chip = (k: string) =>
    `<span style="font-family:ui-monospace,Consolas,monospace;font-size:12px;border:1px solid #e2e6ea;background:#f9fafb;border-radius:4px;padding:0 4px">${esc(k)}</span>`;
  const present = attendance.filter((a) => a.status !== "absent").length;
  const blockers = updates.flatMap((u) => u.blockers.map((b) => ({ who: u.display_name, ...b })));

  const memberBlocks = updates
    .map((u) => {
      const list = (title: string, items: { summary: string; ticket_keys: string[] }[]) =>
        items.length
          ? `<div style="margin-top:6px"><div style="font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:#5f6b7a">${title}</div><ul style="margin:2px 0 0;padding-left:18px">${items
              .map((i) => `<li>${esc(i.summary)} ${i.ticket_keys.map(chip).join(" ")}</li>`)
              .join("")}</ul></div>`
          : "";
      return `<div style="border:1px solid #e2e6ea;border-radius:6px;padding:12px 14px;margin-bottom:10px;background:#fff">
        <div style="font-weight:600">${esc(u.display_name)} <span style="font-weight:500;font-size:12px;color:${
          u.source === "async" ? "#1d4ed8" : "#0a655d"
        }">${u.source === "async" ? "Async" : "Present"}</span></div>
        ${list("Done", u.completed)}${list("Today", u.planned)}
        ${u.blockers.length ? list("Blockers", u.blockers.map((b) => ({ summary: b.description, ticket_keys: b.ticket_keys }))) : ""}
      </div>`;
    })
    .join("");

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(teamName)} standup</title></head>
<body style="margin:0;background:#f4f6f8;font:14px/20px Inter,Segoe UI,system-ui,sans-serif;color:#1f2933">
<div style="max-width:640px;margin:0 auto;padding:24px 16px">
  <div style="font-size:12px;color:#5f6b7a">Scrum Bot · Daily standup report</div>
  <h1 style="font-size:20px;line-height:28px;margin:4px 0 2px">${esc(teamName)}</h1>
  <div style="color:#5f6b7a">${longDate(date)} · ${present}/${attendance.length} attended</div>
  ${
    blockers.length
      ? `<div style="margin:16px 0;border:1px solid #f5c2bd;background:#fdecea;border-radius:6px;padding:12px 14px">
      <div style="font-weight:600;color:#b42318">Blockers (${blockers.length})</div>
      <ul style="margin:6px 0 0;padding-left:18px">${blockers
        .map(
          (b) =>
            `<li><b>${esc(b.who)}</b>: ${esc(b.description)}${b.blocked_on_raw ? ` — waiting on ${esc(b.blocked_on_raw)}` : ""} ${b.ticket_keys
              .map(chip)
              .join(" ")}</li>`,
        )
        .join("")}</ul></div>`
      : `<div style="margin:16px 0;border:1px solid #e2e6ea;background:#e6f4f2;border-radius:6px;padding:10px 14px;color:#0a655d">No blockers reported.</div>`
  }
  ${memberBlocks}
  <div style="margin-top:16px;font-size:12px;color:#5f6b7a">Every line links back to the transcript in Scrum Bot. Reply to this email to reach your scrum lead.</div>
</div></body></html>`;
}
