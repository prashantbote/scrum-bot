/**
 * E2E of the "A day with Scrum Bot" narrative (FRONTEND_IMPLEMENTATION_PLAN §8), against the
 * production build + MSW mock API.
 */
import { expect, test } from "@playwright/test";
import { resetDemo, signInAs, tue } from "./helpers";

test.beforeEach(async ({ page }) => {
  await resetDemo(page);
});

test("Neha reviews the week: dashboard → Tuesday standup → evidence → blockers", async ({ page }) => {
  await signInAs(page, "Neha Kapoor");

  // Friday dashboard KPIs
  await expect(page.getByRole("heading", { name: "Team health" })).toBeVisible();
  await expect(page.getByText("96%")).toBeVisible();
  await expect(page.getByText("4 raised")).toBeVisible();
  await expect(page.getByText("3 resolved · 1 open now")).toBeVisible();
  await expect(page.getByText("1.2 d")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Sneha Joshi" })).toBeVisible();

  // Tuesday's standup summary
  await page.getByRole("link", { name: "Standups" }).first().click();
  await expect(page.getByRole("heading", { name: "Standups" })).toBeVisible();
  await page.goto(`/standups/ses-payments-${tue}`);
  await expect(page.getByRole("heading", { name: "Payments standup" })).toBeVisible();
  await expect(page.getByText("Needs sandbox credentials to test the refund API").first()).toBeVisible();
  await expect(page.getByText("Answered via async check-in")).toBeVisible(); // Karan

  // Evidence link → highlighted transcript segment
  const rahulCard = page.locator("div", { has: page.getByText("Rahul Verma", { exact: true }) }).filter({ hasText: "Blockers" }).last();
  await rahulCard.getByRole("link", { name: /play evidence/i }).last().click();
  await expect(page).toHaveURL(/\/transcript#seg-/);
  await expect(page.locator('li[aria-current="location"]')).toContainText("sandbox credentials from Amit");

  // Report preview
  await page.getByRole("link", { name: "Report" }).click();
  await expect(page.frameLocator('iframe[title="Daily report email preview"]').getByText("Blockers (3)")).toBeVisible();

  // Blockers board: Priya's repeat blocker escalated, not duplicated
  await page.goto("/blockers");
  const open = page.getByRole("region", { name: "Open blockers" });
  await expect(open.getByText("Waiting on code review for the Payment UI")).toHaveCount(1);
  await expect(open.getByText(/Escalated · 4 days/)).toBeVisible();
});

test("Arjun resolves Priya's blocker from the email link; the board and dashboard update", async ({ page }) => {
  // Public signed link — no sign-in
  await page.goto("/a/demo-priya-review");
  await expect(page.getByRole("heading", { name: "Waiting on code review for the Payment UI" })).toBeVisible();
  await page.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByRole("heading", { name: "Acknowledged" })).toBeVisible();
  await page.getByRole("button", { name: "Mark as resolved" }).click();
  await expect(page.getByRole("heading", { name: "Marked as resolved" })).toBeVisible();

  // Re-opening the link shows the already-done state
  await page.reload();
  await expect(page.getByRole("heading", { name: "Already resolved" })).toBeVisible();

  await signInAs(page, "Neha Kapoor");
  await expect(page.getByText("4 resolved · 0 open now")).toBeVisible();
  await page.goto("/blockers");
  await expect(page.getByRole("region", { name: "Resolved blockers" }).getByText("Waiting on code review for the Payment UI")).toBeVisible();
  await page.goto("/blockers/blk-priya-review");
  await expect(page.getByText("From email link").last()).toBeVisible();
});

test("expired and unknown links explain what to do", async ({ page }) => {
  await page.goto("/a/demo-expired");
  await expect(page.getByRole("heading", { name: "This link has expired" })).toBeVisible();
  await page.goto("/a/not-a-token");
  await expect(page.getByRole("heading", { name: "Link not recognised" })).toBeVisible();
});

test("Karan answers the async check-in from the web fallback", async ({ page }) => {
  await page.goto("/a/demo-checkin-karan?type=checkin");
  await page.getByRole("button", { name: "Send update" }).click();
  await expect(page.getByText("This answer is required").first()).toBeVisible();
  await page.getByLabel("What did you complete yesterday?").fill("Payout dashboard PROJ-158");
  await page.getByLabel("What will you work on today?").fill("Payout alerts");
  await page.getByLabel("Any blockers or dependencies?").fill("None");
  await page.getByRole("button", { name: "Send update" }).click();
  await expect(page.getByRole("heading", { name: "Update sent" })).toBeVisible();
});

test("Neha configures questions and schedule", async ({ page }) => {
  await signInAs(page, "Neha Kapoor");
  await page.goto("/teams/team-payments/questions");
  await expect(page.getByText("Questions · version 2")).toBeVisible();
  await page.getByRole("button", { name: "Add question" }).click();
  await page.getByRole("textbox", { name: "Question 4" }).fill("Anything to celebrate?");
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText("Saved as version 3")).toBeVisible();
  await expect(page.getByText("Questions · version 3")).toBeVisible();

  await page.goto("/teams/team-payments/schedule");
  await page.getByRole("button", { name: "Fri", pressed: true }).click();
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("Schedule updated")).toBeVisible();
  await expect(page.getByText("Mon, Tue, Wed, Thu at 10:30 · Asia/Kolkata")).toBeVisible();

  // Audit trail visible to the org admin
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("menuitem", { name: "Switch persona" }).click();
  await page.getByRole("button", { name: /Deepa Iyer/ }).click();
  await page.goto("/audit");
  await expect(page.getByRole("cell", { name: "schedule.updated" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "template.created" }).first()).toBeVisible();
});

test("role-based access: viewer sees aggregates only and can't open admin pages", async ({ page }) => {
  await signInAs(page, "Vikram Rao");
  await expect(page.getByText(/Individual details are visible to the team's scrum lead/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit" })).toHaveCount(0);
  await page.goto("/audit");
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto(`/standups/ses-payments-${tue}`);
  await expect(page.getByRole("link", { name: "Transcript" })).toHaveCount(0);
});
