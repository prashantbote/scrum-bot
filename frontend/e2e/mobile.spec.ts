import { expect, test } from "@playwright/test";
import { resetDemo, signInAs } from "./helpers";

test("action page and navigation drawer work at phone width", async ({ page }) => {
  await resetDemo(page);
  await page.goto("/a/demo-priya-review");
  const resolve = page.getByRole("button", { name: "Mark as resolved" });
  await expect(resolve).toBeVisible();
  const box = await resolve.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(40); // touch target

  await signInAs(page, "Neha Kapoor");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("navigation", { name: "Primary mobile" }).getByRole("link", { name: "Blockers" }).click();
  await expect(page.getByRole("heading", { name: "Blockers" })).toBeVisible();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const viewport = page.viewportSize()!.width;
  expect(scrollWidth).toBeLessThanOrEqual(viewport);
});
