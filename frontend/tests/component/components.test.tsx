import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { KpiCard } from "@/components/cards/KpiCard";
import { BlockerCard } from "@/components/cards/BlockerCard";
import { BlockerStatusBadge } from "@/components/ui/badge";
import { DEFAULT_QUESTIONS, QuestionListEditor, type TemplateForm } from "@/components/forms/QuestionListEditor";
import { TooltipProvider } from "@/components/ui/primitives";
import type { Blocker } from "@/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const blocker: Blocker = {
  id: "b1",
  team_id: "t",
  team_name: "Payments",
  description: "Waiting on code review for the Payment UI",
  reporter_user_id: "u-priya",
  reporter_name: "Priya Nair",
  blocked_on_user_id: "u-arjun",
  blocked_on_name: "Arjun Patel",
  blocked_on_raw: "Arjun",
  ticket_keys: ["PROJ-150"],
  severity: "medium",
  status: "open",
  days_open: 4,
  escalated: true,
  first_seen_at: "2026-11-09T10:36:00+05:30",
  resolved_at: null,
};

describe("KpiCard", () => {
  it("renders value, sub-label and an accessible delta", () => {
    render(
      <TooltipProvider>
        <KpiCard label="Attendance" value="96%" sub="Present or async" delta={{ value: 2, label: "+2 pts", goodWhenUp: true }} info="How it's computed" />
      </TooltipProvider>,
    );
    expect(screen.getByText("96%")).toBeInTheDocument();
    expect(screen.getByText("Present or async")).toBeInTheDocument();
    expect(screen.getByLabelText("Up +2 pts versus previous period")).toHaveClass("text-teal-700");
  });

  it("colors a rising 'bad' metric as danger", () => {
    render(<KpiCard label="Avg time to resolve" value="1.6 d" delta={{ value: 0.4, label: "+0.4 d", goodWhenUp: false }} />);
    expect(screen.getByLabelText("Up +0.4 d versus previous period")).toHaveClass("text-danger");
  });
});

describe("status never relies on color alone", () => {
  it("badges carry text", () => {
    render(<BlockerStatusBadge status="acknowledged" />);
    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
  });
});

describe("BlockerCard", () => {
  it("shows reporter → blocked-on, ticket, escalation and actions", async () => {
    const onStatus = vi.fn();
    render(<BlockerCard blocker={blocker} canUpdate onStatus={onStatus} />);
    expect(screen.getByText("Priya Nair")).toBeInTheDocument();
    expect(screen.getByText("Arjun Patel")).toBeInTheDocument();
    expect(screen.getByText("PROJ-150")).toBeInTheDocument();
    expect(screen.getByText(/Escalated · 4 days/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "medium severity" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /acknowledge/i }));
    expect(onStatus).toHaveBeenCalledWith("acknowledged");
  });

  it("hides actions for users who can't update", () => {
    render(<BlockerCard blocker={blocker} />);
    expect(screen.queryByRole("button", { name: /resolve/i })).not.toBeInTheDocument();
  });
});

function EditorHarness() {
  const form = useForm<TemplateForm>({ defaultValues: { questions: DEFAULT_QUESTIONS } });
  const qs = form.watch("questions");
  return (
    <>
      <QuestionListEditor control={form.control} register={form.register} />
      <output data-testid="order">{qs.map((q) => q.text).join(" | ")}</output>
    </>
  );
}

describe("QuestionListEditor", () => {
  it("reorders with keyboard-accessible buttons and announces the move", async () => {
    render(<EditorHarness />);
    await userEvent.click(screen.getByRole("button", { name: "Move question 3 up" }));
    expect(screen.getByTestId("order").textContent).toBe(
      "What did you complete yesterday? | Any blockers or dependencies? | What will you work on today?",
    );
    expect(screen.getByText("Question moved to position 2 of 3")).toBeInTheDocument();
  });

  it("adds and removes questions", async () => {
    render(<EditorHarness />);
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    const first = screen.getAllByRole("listitem")[0]!;
    await userEvent.click(within(first).getByRole("button", { name: "Remove question 1" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});
