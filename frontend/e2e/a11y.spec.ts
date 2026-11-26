/** Automated WCAG 2.2 AA checks on key screens (plan §4.8, §9 F3.6: 0 serious issues). */
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { resetDemo, signInAs, tue } from "./helpers";

const PAGES = [
  "/dashboard",
  "/standups",
  `/standups/ses-payments-${tue}`,
  `/standups/ses-payments-${tue}/transcript`,
  "/blockers",
  "/blockers/blk-priya-review",
  "/review",
  "/teams",
  "/teams/team-payments/members",
  "/teams/team-payments/questions",
  "/teams/team-payments/schedule",
];

test("key screens have no serious or critical axe violations", async ({ page }) => {
  await resetDemo(page);
  await signInAs(page, "Neha Kapoor");
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .exclude(".react-flow__attribution")
      .analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${path}: ${v.id} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  }
});

test("public pages are accessible", async ({ page }) => {
  for (const path of ["/login", "/a/demo-priya-review", "/a/demo-checkin-karan?type=checkin"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${path}: ${v.id} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  }
});
