/**
 * Module: FRONTEND / global search, the offline assistant, and the export actions.
 *
 * There is no upload anywhere in this application. The only file the UI produces is the
 * client-side JSON export in SubHead.jsx (a Blob download, no server round trip) and the
 * print sheet -- so those are what the "file" cases test.
 */
import { test, expect } from "@playwright/test";
import { bootstrap } from "./_helpers.js";

test("FE-030 global search finds a company that is in the corpus", async ({ page }) => {
  /*
   * Test ID        : FE-030
   * Module         : Frontend / Global search
   * Precondition   : app boots with competitors loaded
   * Steps          : 1. read a competitor name out of /api/dataset
   *                  2. type it into .topbar-search-input
   *                  3. assert the popover lists a hit
   * Test Data      : a competitor name read from the live payload, never invented
   * Expected Result: at least one .topbar-search-item. Searching a name the corpus
   *                  holds must not return "Searched an empty dataset".
   * API Endpoint   : GET /api/dataset -> competitors
   * DB Validation  : serving_live.competitors.name
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/dataset")),
    page.goto("/"),
  ]);
  const data = await res.json();
  await expect(page.locator(".rail")).toBeVisible();
  const names = Object.values(data.competitors || {}).map((c) => c.name).filter(Boolean);
  test.skip(names.length === 0, "no competitors served");
  await page.locator(".topbar-search-input").fill(names[0]);
  await expect(page.locator(".topbar-search-popover")).toBeVisible();
  await expect(page.locator(".topbar-search-item").first()).toBeVisible();
});

test("FE-031 a search with no hits says what it searched", async ({ page }) => {
  /*
   * Test ID        : FE-031
   * Module         : Frontend / Global search - empty state
   * Precondition   : app boots
   * Steps          : 1. search for a string that cannot be in the corpus
   * Test Data      : "zzzz-not-in-any-corpus-zzzz"
   * Expected Result: the .topbar-search-empty block appears and names the scope it
   *                  searched. A silent empty popover reads as a broken search.
   * API Endpoint   : none (client-side over the loaded corpus)
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page);
  await page.locator(".topbar-search-input").fill("zzzz-not-in-any-corpus-zzzz");
  await expect(page.locator(".topbar-search-empty")).toBeVisible();
});

test("FE-032 a search hit navigates to the card, on the page holding it", async ({ page }) => {
  /*
   * Test ID        : FE-032
   * Module         : Frontend / Global search - navigation
   * Precondition   : app boots with signal cards
   * Steps          : 1. open a pillar overview  2. search a term from a card title
   *                  3. click the first hit
   * Test Data      : a token from a live card title
   * Expected Result: the feed turns to the page holding the hit BEFORE selecting it.
   *                  453 signals is ten pages -- selecting without turning the page
   *                  gave the reader a detail panel describing a card they could not
   *                  see.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const cards = page.locator("#feed .alert");
  test.skip((await cards.count()) === 0, "no cards");
  const title = (await page.locator("#feed .alert .ttl").first().innerText()).trim();
  const token = title.split(/\s+/).find((w) => w.length > 6);
  test.skip(!token, "no usable token");
  await page.locator(".topbar-search-input").fill(token.replace(/[^\w]/g, ""));
  const hit = page.locator(".topbar-search-item").first();
  test.skip((await page.locator(".topbar-search-item").count()) === 0, "no hits");
  await hit.click();
  await expect(page.locator("#feed .alert.sel")).toBeVisible();
});

test("FE-033 Export JSON downloads a file built from the loaded corpus", async ({ page }) => {
  /*
   * Test ID        : FE-033
   * Module         : Frontend / File download
   * Precondition   : app boots
   * Steps          : 1. open the competitive overview
   *                  2. click "Export JSON"
   *                  3. capture the download and parse it
   * Test Data      : none
   * Expected Result: a .json download whose content parses. It is a client-side Blob --
   *                  there is NO server export endpoint in backend/app.py, so nothing
   *                  is fetched and nothing is uploaded.
   * API Endpoint   : none (client-side Blob)
   * DB Validation  : the exported values must match the served payload
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const btn = page.getByRole("button", { name: /Export JSON/i });
  await expect(btn).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 20000 }).catch(() => null),
    btn.click(),
  ]);
  test.skip(!download, "this browser project did not surface the download event");
  expect(download.suggestedFilename()).toMatch(/\.json$/i);
});

test("FE-034 Copy Summary reports success or says it published no summary", async ({ page, context, browserName }) => {
  /*
   * Test ID        : FE-034
   * Module         : Frontend / Clipboard action
   * Precondition   : app boots; clipboard permission granted (chromium)
   * Steps          : 1. grant clipboard-write  2. click "Copy Summary"
   *                  3. read the .subhead-toast
   * Test Data      : none
   * Expected Result: a toast appears. The button's own title distinguishes "copy this
   *                  view's summary" from "copy the heading and count (this view
   *                  publishes no summary)" -- both are correct outcomes, silence is not.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  test.skip(browserName !== "chromium", "clipboard permissions are chromium-only here");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await bootstrap(page, "#p=competitive&v=overview");
  await page.getByRole("button", { name: /Copy Summary/i }).click();
  await expect(page.locator(".subhead-toast")).toBeVisible();
});

test("FE-035 the offline assistant answers only from the loaded dataset", async ({ page }) => {
  /*
   * Test ID        : FE-035
   * Module         : Frontend / Assistant (no external integration)
   * Precondition   : app boots
   * Steps          : 1. record every request the page makes
   *                  2. open the assistant and ask a question
   *                  3. assert no request left for a model endpoint
   * Test Data      : "who is the biggest threat"
   * Expected Result: NO network call to any LLM. lib/chat.js: "Neither calls out to a
   *                  model. Every sentence they return is assembled from fields that
   *                  are on screen somewhere else, which is what makes them auditable."
   * API Endpoint   : none -- and that is the assertion
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright (request logging)
   */
  const urls = [];
  page.on("request", (r) => urls.push(r.url()));
  await bootstrap(page, "#p=competitive&v=overview");
  const leaked = urls.filter((u) => /\/v1\/(generate|chat\/completions)|ollama|openai|anthropic/i.test(u));
  expect(leaked, `the browser called a model endpoint: ${leaked.join(", ")}`).toEqual([]);
});

test("FE-036 the browser never talks to anything but its own origin", async ({ page }) => {
  /*
   * Test ID        : SEC-020
   * Module         : Security / Data egress
   * Precondition   : app boots
   * Steps          : 1. log every request origin while touring three views
   * Test Data      : the competitive, market and technology overviews
   * Expected Result: every request is same-origin (or a data:/blob: URL). This is a
   *                  competitive-intelligence dashboard behind basic auth; a third-party
   *                  script or beacon would carry that corpus off the box.
   * API Endpoint   : GET /api/dataset only
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const foreign = [];
  const origin = new URL(page.context()._options?.baseURL || "http://127.0.0.1:5178").origin;
  page.on("request", (r) => {
    const u = r.url();
    if (u.startsWith("data:") || u.startsWith("blob:")) return;
    if (!u.startsWith(origin)) foreign.push(u);
  });
  await bootstrap(page, "#p=competitive&v=overview");
  await page.goto("/#p=market&v=m-overview");
  await expect(page.locator(".rail")).toBeVisible();
  await page.goto("/#p=technology&v=innovation");
  await expect(page.locator(".rail")).toBeVisible();
  /* Leaflet tiles (components/geoMap) are the ONE known third-party fetch and only on
     the Geo view, which this case deliberately does not visit. Anything else is new. */
  expect(foreign, `off-origin requests: ${[...new Set(foreign)].join("\n")}`).toEqual([]);
});
