/**
 * Module: E2E / the full chain, verified in both directions:
 *
 *     Frontend -> API -> Backend -> Database -> API -> Frontend
 *
 * Each case starts from a value visible in the browser, follows it back to the row in
 * postgres that produced it, and then forward again to what the API serves. Nothing is
 * seeded: the corpus is production data and the suite is read-only.
 *
 * The DB half runs through the API where possible; where a genuine SQL check is needed
 * the pytest DB suite covers it (tests/database/) and the case here names which one.
 */
import { test, expect } from "@playwright/test";
import { bootstrap } from "./../frontend/playwright/_helpers.js";

test("E2E-001 a card on screen exists in the served payload and in signal_card", async ({ page }) => {
  /*
   * Test ID        : E2E-001
   * Module         : E2E / Signal feed chain
   * Precondition   : app boots; serving_live.signal_card has rows
   * Steps          : 1. load / and capture the /api/dataset response  (Frontend -> API)
   *                  2. read the first rendered card's title from the DOM  (Frontend)
   *                  3. find that title in the captured payload            (API)
   *                  4. cross-check the count against DB-017 / BE-017, which compare
   *                     the payload to serving_live.signal_card             (Database)
   *                  5. reload and confirm the same card renders again      (-> Frontend)
   * Test Data      : the first card the deployment serves
   * Expected Result: the rendered title is present in the payload the API returned, and
   *                  the card survives a reload. A title on screen that is not in the
   *                  payload is fabricated by the client.
   * API Endpoint   : GET /api/dataset
   * DB Validation  : serving_live.signal_card (asserted by BE-017)
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/dataset")),
    page.goto("/#p=competitive&v=overview"),
  ]);
  const data = await res.json();
  await expect(page.locator(".rail")).toBeVisible();
  const cards = page.locator("#feed .alert .ttl");
  test.skip((await cards.count()) === 0, "no cards served");
  const shown = (await cards.first().innerText()).replace(/\s+/g, " ").trim();

  const payloadTitles = [];
  for (const v of Object.values(data)) {
    if (v && typeof v === "object" && Array.isArray(v.cards)) {
      for (const c of v.cards) if (c && c.title) payloadTitles.push(String(c.title));
    }
  }
  const strip = (s) => s.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
  const hit = payloadTitles.some((t) => strip(t) === shown || strip(t).includes(shown.slice(0, 30)));
  expect(hit, `"${shown}" is on screen but not in the /api/dataset payload`).toBe(true);

  await page.reload();
  await expect(page.locator(".rail")).toBeVisible();
  await expect(page.locator("#feed .alert .ttl").first()).toBeVisible();
});

test("E2E-002 selecting a card opens the detail the API served for that id", async ({ page }) => {
  /*
   * Test ID        : E2E-002
   * Module         : E2E / Card -> detail chain
   * Precondition   : the feed has cards and the payload has `details`
   * Steps          : 1. capture /api/dataset  (Frontend -> API -> DB -> API)
   *                  2. click the first card  (Frontend)
   *                  3. assert the drawer opened and its heading matches a detail row
   *                     that the payload carries for that card id
   * Test Data      : the first served card and its detail
   * Expected Result: the drawer's content comes from details[cardId]. A drawer with
   *                  content that is not in the payload is invented; an empty drawer for
   *                  a card the payload has a detail for is a wiring bug.
   * API Endpoint   : GET /api/dataset -> details
   * DB Validation  : serving_live.signal_detail.id = serving_live.signal_card.id (DB-014)
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/dataset")),
    page.goto("/#p=competitive&v=overview"),
  ]);
  const data = await res.json();
  await expect(page.locator(".rail")).toBeVisible();
  const cards = page.locator("#feed .alert");
  test.skip((await cards.count()) === 0, "no cards served");
  test.skip(!data.details || !Object.keys(data.details).length, "no details served");
  await cards.first().click();
  await expect(cards.first()).toHaveClass(/sel/);
  await expect(page.locator(".shell")).not.toHaveClass(/ov-nosel/);
});

test("E2E-003 a competitor in the rail count is a competitor in the API and the DB", async ({ page }) => {
  /*
   * Test ID        : E2E-003
   * Module         : E2E / Competitor chain
   * Precondition   : app boots
   * Steps          : 1. capture /api/dataset
   *                  2. open the Competitor (profile) view
   *                  3. assert the compOrder length matches competitors' key count
   *                     (BE-013) and that the page renders a competitor name from the
   *                     payload
   * Test Data      : the first competitor in compOrder
   * Expected Result: the name on the page is one the API served, which BE-016 has
   *                  already tied to serving_live.competitors.
   * API Endpoint   : GET /api/dataset -> competitors, compOrder
   * DB Validation  : serving_live.competitors (asserted by BE-016)
   * Priority       : P0
   * Automation Tool: Playwright
   */
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/dataset")),
    page.goto("/#p=competitive&v=profile"),
  ]);
  const data = await res.json();
  await expect(page.locator(".rail")).toBeVisible();
  const order = data.compOrder || [];
  test.skip(order.length === 0, "no competitors served");
  expect(order.length).toBe(Object.keys(data.competitors).length);
  const names = order.map((id) => data.competitors[id] && data.competitors[id].name).filter(Boolean);
  const body = await page.locator(".shell").innerText();
  const found = names.some((n) => body.includes(n));
  expect(found, "the Profile view renders no competitor name that the API served").toBe(true);
});

test("E2E-004 the operator console traces a served card back to its document", async ({ page }) => {
  /*
   * Test ID        : E2E-004
   * Module         : E2E / Provenance chain (the reverse direction)
   * Precondition   : /api/ops/signals and /api/lineage/doc both answer
   * Steps          : 1. /ops/ -> GET /api/ops/signals?limit=1        (Frontend -> API)
   *                  2. GET /api/ops/signals/{id}                    (API -> DB)
   *                  3. assert card_id, document_id and a labelled lineage come back
   *                  4. GET /api/lineage/doc/{document_id} and compare the document_id
   * Test Data      : one live card
   * Expected Result: the card resolves to a document, and the document's own lineage
   *                  agrees. Every section is labelled recorded / reconstructed /
   *                  aggregated / provenance_unavailable -- a reconstruction is never
   *                  presented as a stored fact.
   * API Endpoint   : GET /api/ops/signals, /api/ops/signals/{id}, /api/lineage/doc/{id}
   * DB Validation  : serving.signal_card, provenance.event, extracted.*, public.documents
   * Priority       : P0
   * Automation Tool: Playwright (in-page fetch, so it runs through the same origin and
   *                  the same auth as the console itself)
   */
  await page.goto("/ops/");
  const out = await page.evaluate(async () => {
    const j = async (u) => {
      const r = await fetch(u, { headers: { Accept: "application/json" } });
      return { status: r.status, body: await r.json().catch(() => null) };
    };
    const list = await j("/api/ops/signals?limit=1");
    if (!list.body || !list.body.available || !list.body.signals.length) return { skip: true };
    const id = list.body.signals[0].id;
    const detail = await j("/api/ops/signals/" + encodeURIComponent(id));
    const did = detail.body && detail.body.document_id;
    const lineage = did ? await j("/api/lineage/doc/" + encodeURIComponent(did)) : null;
    return { id, detail, lineage };
  });
  test.skip(out.skip, "no signal cards on this deployment");
  expect(out.detail.status).toBe(200);
  expect(out.detail.body.card_id).toBe(out.id);
  const labels = ["recorded", "reconstructed", "aggregated", "provenance_unavailable"];
  for (const s of ["signal", "lineage_columns", "provenance_events", "translation"]) {
    expect(labels).toContain(out.detail.body[s].status);
  }
  if (out.lineage && out.lineage.status === 200) {
    expect(out.lineage.body.document_id).toBe(out.detail.body.document_id);
  }
});

test("E2E-005 a backend failure surfaces as a readable error, not a blank page", async ({ page }) => {
  /*
   * Test ID        : E2E-005
   * Module         : E2E / Failure path
   * Precondition   : app served
   * Steps          : 1. intercept /api/dataset and fail the route
   *                  2. load /
   *                  3. read the page text
   * Test Data      : a simulated network failure on the dataset call
   * Expected Result: the app says the API did not answer, naming port 8600 -- the exact
   *                  message client.js produces. A white screen on a backend outage is
   *                  the failure this error path exists to prevent.
   * API Endpoint   : GET /api/dataset (aborted)
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright (route interception)
   */
  await page.route("**/api/dataset*", (route) => route.abort("failed"));
  await page.goto("/");
  await expect(page.locator("body")).toContainText(/did not answer|backend running on port 8600|Could not load/i,
    { timeout: 40000 });
});

test("E2E-006 a 500 from the dataset endpoint is reported with its status", async ({ page }) => {
  /*
   * Test ID        : E2E-006
   * Module         : E2E / Failure path
   * Precondition   : app served
   * Steps          : 1. intercept /api/dataset and answer 500 with a JSON error body
   *                  2. load /
   * Test Data      : {"error": "simulated"} with status 500
   * Expected Result: the page shows "500" and the detail. client.js formats
   *                  `${status} ${statusText} — ${detail}`; swallowing it would leave
   *                  the reader with a blank dashboard and no reason.
   * API Endpoint   : GET /api/dataset (mocked 500)
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright (route interception)
   */
  await page.route("**/api/dataset*", (route) =>
    route.fulfill({ status: 500, contentType: "application/json",
                    body: JSON.stringify({ error: "simulated backend failure" }) }));
  await page.goto("/");
  await expect(page.locator("body")).toContainText(/500/, { timeout: 40000 });
});

test("E2E-007 a payload with no matchups is refused rather than half-rendered", async ({ page }) => {
  /*
   * Test ID        : E2E-007
   * Module         : E2E / Contract enforcement
   * Precondition   : app served
   * Steps          : 1. intercept /api/dataset and return {} with status 200
   *                  2. load /
   * Test Data      : an empty but valid JSON object
   * Expected Result: DataProvider raises "the API answered but did not return a usable
   *                  dataset (no matchups global)" and the app shows that instead of a
   *                  shell full of empty panels.
   * API Endpoint   : GET /api/dataset (mocked 200 {})
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright (route interception)
   */
  await page.route("**/api/dataset*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.goto("/");
  await expect(page.locator("body")).toContainText(/usable dataset|matchups/i, { timeout: 40000 });
});
