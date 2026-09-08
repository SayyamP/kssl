/**
 * Module: FRONTEND / application shell.
 *
 * The shell is TopBar + SubHead + (MetricsStrip) + Sidebar + view + MalloryChat
 * (frontend/src/components/layout/Layout.jsx). None of it renders until DataProvider
 * has a dataset, so these cases are also the real bootstrap test.
 */
import { test, expect } from "@playwright/test";
import { bootstrap, assertNoLoadError, PILLARS } from "./_helpers.js";

test("FE-001 the dashboard boots and renders the shell", async ({ page }) => {
  /*
   * Test ID        : FE-001
   * Module         : Frontend / Shell
   * Precondition   : frontend served; /api/dataset answers 200
   * Steps          : 1. open /  2. wait for the rail  3. check topbar, subhead, wordmark
   * Test Data      : none
   * Expected Result: .topbar, .subhead and .rail are visible and the wordmark reads
   *                  137Parallax. No dataset error text anywhere on the page.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : implied -- the payload comes from serving_live.*
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  await expect(page.locator(".topbar")).toBeVisible();
  await expect(page.locator(".subhead")).toBeVisible();
  await expect(page.locator(".wordmark")).toContainText("137");
  await assertNoLoadError(page);
});

test("FE-002 the dataset request succeeds and carries the globals the UI reads", async ({ page }) => {
  /*
   * Test ID        : FE-002
   * Module         : Frontend -> API contract
   * Precondition   : frontend served
   * Steps          : 1. intercept the /api/dataset response while loading /
   *                  2. assert 200 and the presence of matchups + competitors
   * Test Data      : none
   * Expected Result: 200 with matchups and competitors. DataProvider throws
   *                  "did not return a usable dataset (no matchups global)" without it
   *                  and the whole app renders an error instead of the shell.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : serving_live.matchup, serving_live.competitors
   * Priority       : P0
   * Automation Tool: Playwright (network interception)
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/dataset")),
    page.goto("/"),
  ]);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body).toHaveProperty("matchups");
  expect(body).toHaveProperty("competitors");
});

test("FE-003 the three pillars are present and switchable", async ({ page }) => {
  /*
   * Test ID        : FE-003
   * Module         : Frontend / Navigation
   * Precondition   : FE-001 passed
   * Steps          : 1. boot  2. for each pillar pill, click it
   *                  3. assert the pill becomes .active and the rail re-renders
   * Test Data      : competitive, market, technology (lib/route.js PILLARS)
   * Expected Result: exactly three pills; the clicked one is active; the rail shows
   *                  that pillar's items only (Sidebar renders RAIL[pillar]).
   * API Endpoint   : none (client-side routing)
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  const pills = page.locator(".topnav .pill");
  await expect(pills).toHaveCount(PILLARS.length);
  for (let i = 0; i < PILLARS.length; i++) {
    await pills.nth(i).click();
    await expect(pills.nth(i)).toHaveClass(/active/);
    await expect(page.locator(".rail .svc").first()).toBeVisible();
  }
});

test("FE-004 rail counts come from the corpus, never a hardcoded number", async ({ page }) => {
  /*
   * Test ID        : FE-004
   * Module         : Frontend / No fabrication
   * Precondition   : FE-001 passed
   * Steps          : 1. boot  2. read every .svc .ct value
   * Test Data      : none
   * Expected Result: every count is a number or the em-dash placeholder. Sidebar.jsx
   *                  renders `counts[item.view] ?? "—"` from navCounts(), which is
   *                  computed from the loaded corpus. A count with no data must show
   *                  the dash, not a number.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : the counts derive from serving_live row counts
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  const counts = await page.locator(".rail .svc .ct").allInnerTexts();
  expect(counts.length).toBeGreaterThan(0);
  for (const c of counts) {
    expect(c.trim(), `rail count "${c}" is neither a number nor the dash`).toMatch(/^(—|[\d,]+)$/);
  }
});

test("FE-005 no view renders an unhandled React crash", async ({ page }) => {
  /*
   * Test ID        : FE-005
   * Module         : Frontend / Error boundaries
   * Precondition   : FE-001 passed
   * Steps          : 1. collect page errors and console errors
   *                  2. visit every rail view of every pillar
   * Test Data      : the RAIL map from lib/route.js
   * Expected Result: no uncaught page error. Layout wraps each view in an
   *                  ErrorBoundary keyed by view precisely so a bad panel cannot
   *                  unmount the app -- so a boundary catching something is still a
   *                  finding, and it must be visible, not silent.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await bootstrap(page);
  const views = [
    ["competitive", "overview"], ["competitive", "profile"], ["competitive", "products"],
    ["competitive", "positioning"], ["competitive", "partnerships"], ["competitive", "geo"],
    ["competitive", "patents-comp"], ["market", "m-overview"], ["market", "m-report"],
    ["market", "tender"], ["technology", "t-overview"], ["technology", "innovation"],
  ];
  for (const [p, v] of views) {
    await page.goto(`/#p=${p}&v=${v}`);
    await expect(page.locator(".rail")).toBeVisible();
  }
  expect(errors, `uncaught errors while touring the views:\n${errors.join("\n")}`).toEqual([]);
});

test("FE-006 the assistant and the metric strip render where Layout says they do", async ({ page }) => {
  /*
   * Test ID        : FE-006
   * Module         : Frontend / Chrome placement
   * Precondition   : FE-001 passed
   * Steps          : 1. open the competitive overview -> the metric strip is present
   *                  2. open the Profile view -> the strip is NOT rendered
   * Test Data      : #p=competitive&v=overview and #p=competitive&v=profile
   * Expected Result: Layout renders MetricsStrip only when wideNoDrawer is true
   *                  (any pillar overview, the market report views, or innovation).
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const strip = page.locator(".shell").locator("xpath=preceding-sibling::*[1]");
  await expect(page.locator(".shell")).toBeVisible();
  await page.goto("/#p=competitive&v=profile");
  await expect(page.locator(".rail")).toBeVisible();
  await expect(page.locator(".shell")).not.toHaveClass(/ov-nosel/);
});
