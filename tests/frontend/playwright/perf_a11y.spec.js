/**
 * Module: FRONTEND / basic performance and baseline accessibility.
 *
 * "Basic" is meant literally: load timings from the browser's own Navigation Timing and
 * a handful of structural a11y checks. No lighthouse, no axe -- neither is in this
 * repository's dependency set and neither is needed to catch the regressions that have
 * actually happened here.
 */
import { test, expect } from "@playwright/test";
import { bootstrap } from "./_helpers.js";

const BUDGET_PAINT_MS = Number(process.env.KSSL_TEST_BUDGET_PAINT_S || 45) * 1000;

test("PERF-010 the dashboard is interactive inside its own timeout", async ({ page }) => {
  /*
   * Test ID        : PERF-010
   * Module         : Performance / First meaningful render
   * Precondition   : app served, API up
   * Steps          : 1. start a timer  2. open /  3. wait for the rail
   * Test Data      : budget = KSSL_TEST_BUDGET_PAINT_S (default 45s)
   * Expected Result: the shell renders inside the budget. The app's own abort is 30s on
   *                  the dataset fetch (client.js) plus render time -- past this the
   *                  user sees an error page, not a slow one.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  const t0 = Date.now();
  await bootstrap(page);
  const dt = Date.now() - t0;
  expect(dt, `the shell took ${dt}ms to render`).toBeLessThan(BUDGET_PAINT_MS);
});

test("PERF-011 the bootstrap is ONE dataset round trip, not N", async ({ page }) => {
  /*
   * Test ID        : PERF-011
   * Module         : Performance / Request shape
   * Precondition   : app served
   * Steps          : 1. count requests to /api/dataset during a cold load
   * Test Data      : none
   * Expected Result: exactly one. datasetService fetches "every global in one round
   *                  trip" and DataProvider memoises the derived objects on the dataset
   *                  identity, so a re-render must not refetch. Two calls means the
   *                  memo broke and every navigation re-downloads the corpus.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  let n = 0;
  page.on("request", (r) => { if (r.url().includes("/api/dataset")) n++; });
  await bootstrap(page);
  await page.goto("/#p=market&v=m-overview");
  await expect(page.locator(".rail")).toBeVisible();
  await page.goto("/#p=technology&v=innovation");
  await expect(page.locator(".rail")).toBeVisible();
  expect(n, `/api/dataset was fetched ${n} times across three views`).toBe(1);
});

test("PERF-012 navigating between views does not refetch", async ({ page }) => {
  /*
   * Test ID        : PERF-012
   * Module         : Performance / Client-side navigation
   * Precondition   : app booted
   * Steps          : 1. boot  2. click through five rail items in one session
   *                  3. count API requests made after the first paint
   * Test Data      : the competitive rail
   * Expected Result: zero further API calls -- all routing is client-side over the one
   *                  loaded payload.
   * API Endpoint   : none after bootstrap
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const after = [];
  page.on("request", (r) => { if (r.url().includes("/api/")) after.push(r.url()); });
  const items = page.locator(".rail .svc");
  const n = Math.min(await items.count(), 5);
  for (let i = 0; i < n; i++) {
    await items.nth(i).click();
    await page.waitForTimeout(300);
  }
  expect(after, `client-side navigation issued API calls: ${after.join(", ")}`).toEqual([]);
});

test("PERF-013 navigation timing is recorded for the report", async ({ page }) => {
  /*
   * Test ID        : PERF-013
   * Module         : Performance / Measurement
   * Precondition   : app served
   * Steps          : 1. load /  2. read performance.getEntriesByType("navigation")[0]
   * Test Data      : none
   * Expected Result: domContentLoaded and loadEventEnd are recorded and printed into
   *                  the run's output, so the report carries measured numbers rather
   *                  than an impression.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  const t = await page.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    return n ? { dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd),
                 ttfb: Math.round(n.responseStart) } : null;
  });
  expect(t).not.toBeNull();
  console.log(`PERF-013 timings: TTFB=${t.ttfb}ms DCL=${t.dcl}ms load=${t.load}ms`);
});

test("FE-070 the page declares a language and a title", async ({ page }) => {
  /*
   * Test ID        : FE-070
   * Module         : Frontend / Accessibility baseline
   * Precondition   : app served
   * Steps          : 1. read <html lang> and document.title
   * Test Data      : none
   * Expected Result: both present and non-empty. A missing lang makes every screen
   *                  reader guess the pronunciation of a page that carries multiple
   *                  languages of source material.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  expect((await page.getAttribute("html", "lang")) || "").not.toBe("");
  expect((await page.title()).trim().length).toBeGreaterThan(0);
});

test("FE-071 interactive chrome is reachable by keyboard", async ({ page }) => {
  /*
   * Test ID        : FE-071
   * Module         : Frontend / Accessibility baseline
   * Precondition   : app booted
   * Steps          : 1. Tab through the first 20 focusable elements
   *                  2. assert focus actually moves and lands on real controls
   * Test Data      : none
   * Expected Result: focus moves. The rail rows are divs with role="button" and
   *                  tabIndex=0 for exactly this reason; a regression to a plain
   *                  onClick div makes the whole navigation unreachable.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  const seen = new Set();
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("Tab");
    const tag = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? `${el.tagName}.${el.className}`.slice(0, 60) : "";
    });
    if (tag) seen.add(tag);
  }
  expect(seen.size, "Tab never moved focus -- nothing in the chrome is keyboard reachable")
    .toBeGreaterThan(1);
});

test("FE-072 the layout does not scroll horizontally at a narrow viewport", async ({ page }) => {
  /*
   * Test ID        : FE-072
   * Module         : Frontend / Responsive layout
   * Precondition   : app booted
   * Steps          : 1. set the viewport to 1280x800 and to 390x844
   *                  2. compare scrollWidth to clientWidth on the document element
   * Test Data      : desktop and phone widths
   * Expected Result: no horizontal overflow of the page body. Wide content (tables,
   *                  the graph) must scroll inside its own container.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(vp);
    await page.waitForTimeout(400);
    const over = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over, `horizontal overflow of ${over}px at ${vp.width}px`).toBeLessThanOrEqual(2);
  }
});
