/* Shared helpers. Selectors are the class names the components actually render
   (frontend/src/components/**), not test ids -- the app ships none. */
import { expect } from "@playwright/test";

export const PILLARS = ["competitive", "market", "technology"];

/* frontend/src/lib/route.js RAIL -- the views each pillar can render. */
export const RAIL = {
  competitive: ["overview", "profile", "products", "positioning", "partnerships", "geo", "patents-comp"],
  market: ["m-overview", "m-report", "tender"],
  technology: ["t-overview", "innovation"],
};

/* Off the rail, still routed (ARCHIVED_VIEWS). A saved or pasted link must resolve. */
export const ARCHIVED = {
  competitive: ["gap-competitive"],
  market: ["awarded-tenders", "closed-tenders"],
  technology: [],
};

export const routeHash = (pillar, view) => `#p=${pillar}&v=${view}`;

/* The app boots only after DataProvider resolves /api/dataset; before that there is no
   rail at all. Waiting on the rail is waiting on a real successful bootstrap. */
export async function bootstrap(page, hash = "") {
  await page.goto("/" + hash);
  await expect(page.locator(".rail")).toBeVisible();
  return page;
}

/* DataProvider renders its own error text when the API fails -- fail loudly and
   readably rather than timing out on a selector. */
export async function assertNoLoadError(page) {
  const body = await page.locator("body").innerText();
  expect(body, "the dashboard is showing a dataset load error").not.toContain(
    "did not return a usable dataset");
  expect(body).not.toContain("is the backend running on port 8600");
}

export async function goToView(page, pillar, view) {
  await page.goto("/" + routeHash(pillar, view));
  await expect(page.locator(".rail")).toBeVisible();
}
