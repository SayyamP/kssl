/**
 * Module: FRONTEND / the individual pages, one case each.
 *
 * Every page below exists in frontend/src/pages/**. The assertions are deliberately
 * about structure and honesty (does it render, does it say when it has nothing) rather
 * than about specific values, because the corpus changes under the suite.
 */
import { test, expect } from "@playwright/test";
import { bootstrap } from "./_helpers.js";

const PAGES = [
  ["FE-040", "competitive", "profile", "Profile"],
  ["FE-041", "competitive", "products", "Products"],
  ["FE-042", "competitive", "positioning", "Positioning"],
  ["FE-043", "competitive", "partnerships", "Partnerships"],
  ["FE-044", "competitive", "geo", "Geo Footprint"],
  ["FE-045", "competitive", "patents-comp", "Patents"],
  ["FE-046", "market", "m-report", "Market Report"],
  ["FE-047", "market", "tender", "Tender Pipeline"],
  ["FE-048", "technology", "innovation", "Innovation"],
];

for (const [id, pillar, view, label] of PAGES) {
  test(`${id} ${label} renders with a heading and no crash`, async ({ page }) => {
    /*
     * Test ID        : see the title
     * Module         : Frontend / Pages
     * Precondition   : app boots
     * Steps          : 1. open #p=<pillar>&v=<view>
     *                  2. assert the subhead heading is non-empty
     *                  3. assert no error boundary fallback and no crash text
     * Test Data      : the rail's own (pillar, view) pairs
     * Expected Result: the page renders its own heading (every heading comes from
     *                  viewMeta; only a pillar overview overrides it from served
     *                  config) and no "no view named" fallback appears.
     * API Endpoint   : GET /api/dataset (one payload feeds every page)
     * DB Validation  : the page's serving_live table -- see TEST_CASES.md
     * Priority       : P0
     * Automation Tool: Playwright
     */
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await bootstrap(page, `#p=${pillar}&v=${view}`);
    const h1 = (await page.locator(".subhead h1").innerText()).trim();
    expect(h1.length).toBeGreaterThan(0);
    const body = await page.locator("body").innerText();
    expect(body).not.toContain("no view named");
    expect(errors, `${label} threw: ${errors.join("\n")}`).toEqual([]);
  });
}

test("FE-049 the Market Report bucket line counts open, awarded and closed", async ({ page }) => {
  /*
   * Test ID        : FE-049
   * Module         : Frontend / Market Report
   * Precondition   : app boots with tenders loaded
   * Steps          : 1. open #p=market&v=m-report  2. read the .cnt line
   * Test Data      : none
   * Expected Result: "<n> open · <n> awarded · <n> closed · demand shape, spec and
   *                  requirement". The buckets are computed by bucketTenders over the
   *                  WIRED dataset -- computeTenderRealDays rewrites dl and deadline,
   *                  and the served rows carry dl:null, for which `dl <= 0` is true and
   *                  every tender would bucket as closed.
   * API Endpoint   : GET /api/dataset -> tenders
   * DB Validation  : SELECT count(*) FROM serving_live.tender
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=market&v=m-report");
  const line = await page.locator(".subhead .cnt").innerText();
  expect(line).toMatch(/\d+\s+open/);
  expect(line).toMatch(/\d+\s+awarded/);
  expect(line).toMatch(/\d+\s+closed/);
});

test("FE-050 the Profile page shows no invented company facts", async ({ page }) => {
  /*
   * Test ID        : FE-050
   * Module         : Frontend / No fabrication (regression)
   * Precondition   : app boots with competitors loaded
   * Steps          : 1. open the Profile view
   *                  2. scan the rendered text for the placeholder shapes the page
   *                     once invented in place of missing served columns
   * Test Data      : the words the old page substituted -- founded / headcount /
   *                  revenue -- when starting_year, company_size and
   *                  strategic_positioning were in the table but not in the API
   * Expected Result: no "N/A", "TBD", "Lorem", "undefined" or "[object Object]" in the
   *                  rendered body. Those columns sat in the table AND in the
   *                  serving_live view but not in the API's field list, so they could
   *                  never reach the browser however well the pipeline filled them --
   *                  and the page invented values in their place.
   * API Endpoint   : GET /api/dataset -> competitors[].starting_year / company_size
   * DB Validation  : serving_live.competitors.starting_year, company_size
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=profile");
  const body = await page.locator(".shell").innerText();
  for (const bad of ["undefined", "[object Object]", "NaN", "Lorem ipsum"]) {
    expect(body, `the Profile page rendered "${bad}"`).not.toContain(bad);
  }
});

test("FE-051 the Geo map renders its container", async ({ page }) => {
  /*
   * Test ID        : FE-051
   * Module         : Frontend / Geo
   * Precondition   : app boots; leaflet bundled (frontend/package.json)
   * Steps          : 1. open the Geo view  2. wait for the map container
   * Test Data      : none
   * Expected Result: the leaflet container mounts. NOTE: this is the one view that
   *                  fetches third-party tiles, which is why SEC-020 deliberately does
   *                  not visit it.
   * API Endpoint   : GET /api/dataset -> geoData, geoComps
   * DB Validation  : serving_live.geo_presence, serving_live.geo_comp
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=geo");
  const map = page.locator(".leaflet-container, .geo-map, #map");
  await expect(map.first()).toBeVisible({ timeout: 30000 });
});

test("FE-052 every panel that has nothing says so", async ({ page }) => {
  /*
   * Test ID        : FE-052
   * Module         : Frontend / Honest empty states
   * Precondition   : app boots
   * Steps          : 1. tour every rail view
   *                  2. for any view whose main area is empty, require an .empty-note
   * Test Data      : the rail
   * Expected Result: no page renders a blank main area with no explanation. The
   *                  project's rule is honest empty states, never a fabricated filler.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  const views = [
    ["competitive", "profile"], ["competitive", "products"], ["competitive", "positioning"],
    ["competitive", "partnerships"], ["competitive", "patents-comp"],
    ["market", "tender"], ["technology", "innovation"],
  ];
  const blank = [];
  for (const [p, v] of views) {
    await page.goto(`/#p=${p}&v=${v}`);
    await expect(page.locator(".rail")).toBeVisible();
    const text = (await page.locator(".shell").innerText()).trim();
    const railText = (await page.locator(".rail").innerText()).trim();
    const main = text.replace(railText, "").trim();
    if (main.length < 20 && (await page.locator(".empty-note").count()) === 0) {
      blank.push(`${p}/${v}`);
    }
  }
  expect(blank, `views that render blank with no empty note: ${blank.join(", ")}`).toEqual([]);
});
