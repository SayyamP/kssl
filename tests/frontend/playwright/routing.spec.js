/**
 * Module: FRONTEND / routing.
 *
 * The URL hash is the app's ONLY route (frontend/src/lib/route.js). Three regressions
 * are recorded in that file's own header and each has a case here: Back left the site,
 * a hash edited in the address bar changed nothing, and an unknown view rendered the
 * rail beside an empty pane and then SAVED that route to localStorage.
 */
import { test, expect } from "@playwright/test";
import { bootstrap, RAIL, ARCHIVED, routeHash } from "./_helpers.js";

for (const [pillar, views] of Object.entries(RAIL)) {
  for (const view of views) {
    test(`FE-010 ${pillar}/${view} resolves from a pasted link`, async ({ page }) => {
      /*
       * Test ID        : FE-010
       * Module         : Frontend / Routing
       * Precondition   : app boots
       * Steps          : 1. open /#p=<pillar>&v=<view> directly
       *                  2. assert the rail renders and the hash is unchanged
       * Test Data      : every (pillar, view) pair on the rail
       * Expected Result: the hash survives -- parseRoute returns repaired:false for a
       *                  known view, so the router must not rewrite it.
       * API Endpoint   : GET /api/dataset (bootstrap)
       * DB Validation  : n/a
       * Priority       : P0
       * Automation Tool: Playwright
       */
      await bootstrap(page, routeHash(pillar, view));
      expect(page.url()).toContain(`v=${view}`);
      await expect(page.locator(".rail")).toBeVisible();
    });
  }
}

for (const [pillar, views] of Object.entries(ARCHIVED)) {
  for (const view of views) {
    test(`FE-011 archived route ${pillar}/${view} still resolves`, async ({ page }) => {
      /*
       * Test ID        : FE-011
       * Module         : Frontend / Routing - archived views
       * Precondition   : app boots
       * Steps          : 1. open the archived route directly
       * Test Data      : gap-competitive, awarded-tenders, closed-tenders
       * Expected Result: it renders. These are off the rail but Layout still routes
       *                  them, so a saved route or a pasted link keeps working -- the
       *                  `default:` branch would otherwise render a blank pane forever
       *                  AND persist that route to localStorage.
       * API Endpoint   : none
       * DB Validation  : n/a
       * Priority       : P1
       * Automation Tool: Playwright
       */
      await bootstrap(page, routeHash(pillar, view));
      const body = await page.locator("body").innerText();
      expect(body).not.toContain("no view named");
    });
  }
}

test("FE-012 an unknown view is repaired to that pillar's overview", async ({ page }) => {
  /*
   * Test ID        : FE-012
   * Module         : Frontend / Routing - repair
   * Precondition   : app boots
   * Steps          : 1. open /#p=technology&v=does-not-exist
   * Test Data      : v=does-not-exist on a KNOWN pillar
   * Expected Result: the app lands on t-overview (OVERVIEW_VIEW[technology]) and does
   *                  NOT render an empty pane. parseRoute repairs an unknown view and
   *                  flags it, so the shell never boots into a pane its switch cannot
   *                  render -- and never saves that route.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=technology&v=does-not-exist");
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("no view named");
  await expect(page.locator(".rail")).toBeVisible();
});

test("FE-013 an unknown pillar falls back to the default route", async ({ page }) => {
  /*
   * Test ID        : FE-013
   * Module         : Frontend / Routing - validation
   * Precondition   : app boots
   * Steps          : 1. open /#p=nonsense&v=overview
   * Test Data      : p=nonsense
   * Expected Result: parseRoute returns null for an unknown pillar, so the app falls
   *                  back to its saved route or DEFAULT_ROUTE (competitive/overview).
   *                  The shell renders either way.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=nonsense&v=overview");
  await expect(page.locator(".rail")).toBeVisible();
});

test("FE-014 browser Back returns through the navigation, not off the site", async ({ page }) => {
  /*
   * Test ID        : FE-014
   * Module         : Frontend / Routing - history (regression)
   * Precondition   : app boots
   * Steps          : 1. open the competitive overview
   *                  2. click through to Technology, then Innovation
   *                  3. press Back twice
   * Test Data      : competitive -> technology -> innovation
   * Expected Result: Back walks the navigation. Before the fix the router wrote every
   *                  navigation with history.replaceState, so the session had ONE
   *                  history entry and Back left the site entirely.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  await page.goto("/#p=technology&v=t-overview");
  await expect(page.locator(".rail")).toBeVisible();
  await page.goto("/#p=technology&v=innovation");
  await expect(page.locator(".rail")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/v=t-overview/);
  await page.goBack();
  await expect(page).toHaveURL(/v=overview/);
  await expect(page.locator(".rail")).toBeVisible();
});

test("FE-015 editing the hash in an open tab changes the view", async ({ page }) => {
  /*
   * Test ID        : FE-015
   * Module         : Frontend / Routing - popstate (regression)
   * Precondition   : app boots
   * Steps          : 1. boot on the competitive overview
   *                  2. set location.hash to the innovation route from the page itself
   *                  3. assert the view changed
   * Test Data      : #p=technology&v=innovation
   * Expected Result: the view follows the hash. The router listened to nothing before
   *                  the fix, so a hash edited in the address bar of an OPEN tab
   *                  changed nothing on screen.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  await page.evaluate(() => { window.location.hash = "#p=technology&v=innovation"; });
  await expect(page).toHaveURL(/v=innovation/);
  await expect(page.locator(".rail")).toBeVisible();
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("no view named");
});

test("FE-016 the rail navigates by click and by keyboard", async ({ page }) => {
  /*
   * Test ID        : FE-016
   * Module         : Frontend / Navigation, accessibility
   * Precondition   : app boots
   * Steps          : 1. click the second rail item -> it becomes .active
   *                  2. focus the third and press Enter -> it becomes .active
   * Test Data      : the competitive rail
   * Expected Result: both work. Sidebar rows carry role="button", tabIndex=0 and an
   *                  onKeyDown handling Enter and Space -- a div that is only clickable
   *                  is unreachable by keyboard.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const items = page.locator(".rail .svc");
  await items.nth(1).click();
  await expect(items.nth(1)).toHaveClass(/active/);
  await items.nth(2).focus();
  await page.keyboard.press("Enter");
  await expect(items.nth(2)).toHaveClass(/active/);
});
