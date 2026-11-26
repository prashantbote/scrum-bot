import { expect, type Page } from "@playwright/test";
import { shiftDate, storyFriday } from "../mocks/data/clock";

export const fri = storyFriday();
export const tue = shiftDate(fri, -3);

/** Mock-mode sign-in via the persona picker (stands in for Entra ID SSO). */
export async function signInAs(page: Page, name: "Neha Kapoor" | "Deepa Iyer" | "Rahul Verma" | "Vikram Rao") {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

export async function resetDemo(page: Page) {
  await page.goto("/login");
  await page.evaluate(() => window.localStorage.clear());
}
