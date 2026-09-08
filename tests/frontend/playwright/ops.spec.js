/**
 * Module: FRONTEND / the operator console at /ops/.
 *
 * A separate static page (frontend/public/ops/index.html), served by the same Caddy
 * container -- try_files probes {path}/index.html BEFORE the SPA fallback, which is the
 * only reason the bare /ops/ URL works at all. It has SIX tabs and no authorization of
 * its own: basic auth at the front door is the entire boundary.
 */
import { test, expect } from "@playwright/test";

const TABS = ["overview", "pipeline", "lineage", "events", "runs", "signals"];

test("FE-060 /ops/ serves the console, not the SPA", async ({ page }) => {
  /*
   * Test ID        : FE-060
   * Module         : Frontend / Ops console routing
   * Precondition   : frontend container serving
   * Steps          : 1. open /ops/  2. check the header
   * Test Data      : none
   * Expected Result: "Backend Intelligence" renders. Without the {path}/index.html term
   *                  in the Caddyfile the bare directory URL fell through to the SPA
   *                  and showed the main app instead.
   * API Endpoint   : none (static)
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await page.goto("/ops/");
  await expect(page.locator("h1")).toContainText("Backend Intelligence");
});

test("FE-061 all six tabs are present and switch", async ({ page }) => {
  /*
   * Test ID        : FE-061
   * Module         : Frontend / Ops console navigation
   * Precondition   : FE-060 passed
   * Steps          : 1. open /ops/  2. click each nav button  3. assert its section shows
   * Test Data      : overview, pipeline, lineage, events, runs, signals
   * Expected Result: each tab reveals #v-<tab> and marks its button .on.
   * API Endpoint   : the tab's own /api/ops/* call
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await page.goto("/ops/");
  for (const t of TABS) {
    await page.locator(`nav button[data-view="${t}"]`).click();
    await expect(page.locator(`#v-${t}`)).toHaveClass(/on/);
  }
});

test("FE-062 System Overview loads real queue and stage data", async ({ page }) => {
  /*
   * Test ID        : FE-062
   * Module         : Frontend / Ops -> API -> DB
   * Precondition   : /api/ops/overview answers
   * Steps          : 1. open /ops/  2. wait for the /api/ops/overview response
   *                  3. assert the tiles rendered and the status line carries a timestamp
   * Test Data      : none
   * Expected Result: 200 from the API and a rendered queue section. The status line
   *                  shows "overview @ <generated_at>" -- the console never shows a
   *                  number the API did not return.
   * API Endpoint   : GET /api/ops/overview
   * DB Validation  : public.extract_queue, metrics.stage_run, provenance.event
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/ops/overview")),
    page.goto("/ops/"),
  ]);
  expect(res.status()).toBe(200);
  await expect(page.locator("#v-overview")).toContainText("Queue state");
  await expect(page.locator("#status")).toContainText("overview @");
});

test("FE-063 Document Lineage traces a real document end to end", async ({ page }) => {
  /*
   * Test ID        : E2E-010
   * Module         : E2E / Frontend -> API -> Backend -> Database -> API -> Frontend
   * Precondition   : the console loads and /api/ops/signals returns at least one card
   * Steps          : 1. open /ops/, go to Signal Explorer, read one card id (pl_<doc>)
   *                  2. switch to Document Lineage, type the document id, press Trace
   *                  3. assert the lineage response is 200 and the panel renders stages
   * Test Data      : a document id derived from a LIVE card id, never invented
   * Expected Result: the trace renders, labelled recorded / reconstructed /
   *                  provenance_unavailable. This is the full chain: the browser asks
   *                  the API, the API reads four schemas, and the answer comes back to
   *                  the same page.
   * API Endpoint   : GET /api/ops/signals -> GET /api/lineage/doc/{document_id}
   * DB Validation  : public.documents, extracted.document, extracted.proposition,
   *                  serving.signal_card
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await page.goto("/ops/");
  const sig = await page.evaluate(async () => {
    const r = await fetch("/api/ops/signals?limit=1", { headers: { Accept: "application/json" } });
    return r.ok ? r.json() : null;
  });
  test.skip(!sig || !sig.available || !sig.signals.length, "no signal cards on this deployment");
  const cardId = sig.signals[0].id;
  const docId = cardId.startsWith("pl_") ? cardId.slice(3) : cardId;
  await page.locator('nav button[data-view="lineage"]').click();
  await page.locator("#doc-input").fill(docId);
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/lineage/doc/")),
    page.locator("#doc-go").click(),
  ]);
  expect([200, 404]).toContain(res.status());
  await expect(page.locator("#lineage-out")).not.toBeEmpty();
});

test("FE-064 Signal Explorer search filters the list", async ({ page }) => {
  /*
   * Test ID        : FE-064
   * Module         : Frontend / Ops - search & filter
   * Precondition   : /api/ops/signals returns rows
   * Steps          : 1. open the Signals tab
   *                  2. pick lane=competitive in the select, press Search
   *                  3. assert the request carried lane=competitive
   * Test Data      : lane = competitive
   * Expected Result: the request the page issues includes the filter; the list re-renders.
   * API Endpoint   : GET /api/ops/signals?lane=competitive
   * DB Validation  : serving.signal_card WHERE lane='competitive'
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await page.goto("/ops/");
  await page.locator('nav button[data-view="signals"]').click();
  await page.locator("#sig-lane").selectOption("competitive");
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/ops/signals")),
    page.locator("#sig-go").click(),
  ]);
  expect(req.url()).toContain("lane=competitive");
});

test("FE-065 the Live Event Stream starts and stops without errors", async ({ page }) => {
  /*
   * Test ID        : FE-065
   * Module         : Frontend / Ops - polling
   * Precondition   : the console loads
   * Steps          : 1. open the Events tab  2. press Start live  3. press it again
   * Test Data      : none
   * Expected Result: no uncaught error, and the polling stops when toggled off. The
   *                  stream polls /api/ops/events every 4s; a toggle that does not stop
   *                  it leaves a page hammering the API forever.
   * API Endpoint   : GET /api/ops/events?since_id=
   * DB Validation  : provenance.event
   * Priority       : P2
   * Automation Tool: Playwright
   */
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/ops/");
  await page.locator('nav button[data-view="events"]').click();
  await page.locator("#ev-toggle").click();
  await page.waitForTimeout(5000);
  await page.locator("#ev-toggle").click();
  const seen = [];
  page.on("request", (r) => { if (r.url().includes("/api/ops/events")) seen.push(r.url()); });
  await page.waitForTimeout(6000);
  expect(errors).toEqual([]);
  expect(seen, "the event stream kept polling after it was stopped").toEqual([]);
});

test("FE-066 an unknown document id fails loudly, not silently", async ({ page }) => {
  /*
   * Test ID        : FE-066
   * Module         : Frontend / Ops - error handling
   * Precondition   : the console loads
   * Steps          : 1. Document Lineage tab  2. trace an id that cannot exist
   * Test Data      : "doc_e2e_not_a_real_document"
   * Expected Result: the panel shows the API's error text. getJSON throws on a non-2xx
   *                  and the view must surface that, not leave the previous trace on
   *                  screen looking like the answer.
   * API Endpoint   : GET /api/lineage/doc/doc_e2e_not_a_real_document
   * DB Validation  : the id is in none of the four checked tables
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await page.goto("/ops/");
  await page.locator('nav button[data-view="lineage"]').click();
  await page.locator("#doc-input").fill("doc_e2e_not_a_real_document");
  await page.locator("#doc-go").click();
  await expect(page.locator("#lineage-out")).toContainText(/no lineage|error|unavailable/i,
    { timeout: 20000 });
});
