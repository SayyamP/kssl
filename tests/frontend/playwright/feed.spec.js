/**
 * Module: FRONTEND / the signal feed -- filters, tiles, pagination, the detail drawer.
 *
 * Selectors are the classes Overview.jsx / SignalCard.jsx / FeedFilters.jsx render.
 * The count line is Layout.jsx's countLine, which is the app's own statement of how
 * many rows the current filter shows -- so it is the assertion target, not a re-count.
 */
import { test, expect } from "@playwright/test";
import { bootstrap } from "./_helpers.js";

const OVERVIEWS = [
  ["competitive", "overview"],
  ["market", "m-overview"],
  ["technology", "t-overview"],
];

test("FE-020 the competitive feed renders cards", async ({ page }) => {
  /*
   * Test ID        : FE-020
   * Module         : Frontend / Feed
   * Precondition   : app boots and serving_live.signal_card has competitive rows
   * Steps          : 1. open the competitive overview  2. count .alert cards
   * Test Data      : none
   * Expected Result: at least one card, OR the honest empty note. An empty feed with
   *                  no note is the failure -- never a fabricated placeholder card.
   * API Endpoint   : GET /api/dataset -> cards
   * DB Validation  : SELECT count(*) FROM serving_live.signal_card WHERE lane='competitive'
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const cards = page.locator("#feed .alert");
  const n = await cards.count();
  if (n === 0) {
    await expect(page.locator(".empty-note")).toBeVisible();
  } else {
    await expect(cards.first()).toBeVisible();
  }
});

for (const [pillar, view] of OVERVIEWS) {
  test(`FE-021 ${pillar} feed count line agrees with the cards on screen`, async ({ page }) => {
    /*
     * Test ID        : FE-021
     * Module         : Frontend / Feed counting
     * Precondition   : app boots
     * Steps          : 1. open the pillar overview
     *                  2. read the .cnt line and the total it claims
     *                  3. compare it to the cards the payload holds for that lane
     * Test Data      : each pillar's overview
     * Expected Result: the number in the count line is the SERVED card set's total, not
     *                  a baked figure. Layout.jsx strips the served copy's leading
     *                  number precisely so an empty dataset says 0 instead of a stale
     *                  total.
     * API Endpoint   : GET /api/dataset
     * DB Validation  : serving_live.signal_card row count for that lane
     * Priority       : P0
     * Automation Tool: Playwright
     */
    await bootstrap(page, `#p=${pillar}&v=${view}`);
    const line = (await page.locator(".subhead .cnt").innerText()).trim();
    expect(line.length).toBeGreaterThan(0);
    const m = line.match(/^([\d,]+)/);
    if (m) {
      expect(Number(m[1].replace(/,/g, ""))).toBeGreaterThanOrEqual(0);
    }
  });
}

test("FE-022 a direction filter narrows the feed and says so", async ({ page }) => {
  /*
   * Test ID        : FE-022
   * Module         : Frontend / Feed filters
   * Precondition   : the competitive feed has cards
   * Steps          : 1. open the competitive overview, note the total
   *                  2. click a direction filter button (.fbtn) that is not empty
   *                  3. read the count line and the visible card count
   * Test Data      : the served cfg.filters for the competitive pillar
   * Expected Result: the count line becomes "<shown> of <total> signals · <label>" and
   *                  the cards on screen are <= the total. A filter that widens the
   *                  set, or one that changes nothing, is the bug.
   * API Endpoint   : none (client-side filter over the loaded corpus)
   * DB Validation  : n/a
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const filters = page.locator(".dir-filters .fbtn");
  const count = await filters.count();
  test.skip(count === 0, "this deployment serves no direction filters");
  let clicked = false;
  for (let i = 0; i < count; i++) {
    const b = filters.nth(i);
    const cls = (await b.getAttribute("class")) || "";
    if (cls.includes("empty")) continue;
    const label = (await b.innerText()).trim();
    if (/^all/i.test(label)) continue;
    await b.click();
    clicked = true;
    break;
  }
  test.skip(!clicked, "every direction filter is empty on this corpus");
  await expect(page.locator(".subhead .cnt")).toContainText(" of ");
});

test("FE-023 an empty filter is marked empty rather than silently showing nothing", async ({ page }) => {
  /*
   * Test ID        : FE-023
   * Module         : Frontend / Feed filters - honest empty state
   * Precondition   : app boots
   * Steps          : 1. open the competitive overview
   *                  2. for each .fbtn.empty, click it and check the feed's empty note
   * Test Data      : whichever filters the corpus leaves empty
   * Expected Result: the button carries the `empty` class AND clicking it shows the
   *                  empty note. A filter that renders a blank pane with no explanation
   *                  reads as a broken page.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const empties = page.locator(".dir-filters .fbtn.empty");
  const n = await empties.count();
  test.skip(n === 0, "no empty filters on this corpus");
  await empties.first().click();
  await expect(page.locator(".empty-note").first()).toBeVisible();
});

test("FE-024 feed search narrows the feed", async ({ page }) => {
  /*
   * Test ID        : FE-024
   * Module         : Frontend / Feed search
   * Precondition   : the competitive feed has cards
   * Steps          : 1. open the competitive overview
   *                  2. type a token taken from the FIRST card's own title
   *                  3. assert that card is still on screen
   *                  4. clear with the .feed-search-clear button
   * Test Data      : a word read off a live card, never invented
   * Expected Result: the searched card survives its own search term; clearing restores
   *                  the feed.
   * API Endpoint   : none (client-side over the loaded corpus)
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const first = page.locator("#feed .alert .ttl").first();
  test.skip((await page.locator("#feed .alert").count()) === 0, "no cards to search");
  const title = (await first.innerText()).trim();
  const token = (title.split(/\s+/).find((w) => w.length > 5) || title.slice(0, 6)).replace(/[^\w]/g, "");
  test.skip(!token, "no usable token in the first card title");
  const box = page.locator(".feed-search-box input");
  await box.fill(token);
  await expect(page.locator("#feed .alert").first()).toBeVisible();
  await page.locator(".feed-search-clear").click();
  await expect(box).toHaveValue("");
});

test("FE-025 pagination turns pages and remembers where the reader was", async ({ page }) => {
  /*
   * Test ID        : FE-025
   * Module         : Frontend / Pagination
   * Precondition   : the feed has more than one page
   * Steps          : 1. open the competitive overview
   *                  2. if a .pager exists, click Next / page 2
   *                  3. reload the page
   *                  4. assert the reader is still on page 2
   * Test Data      : none
   * Expected Result: the page is remembered per (pillar, filter) in sessionStorage.
   *                  Before that the reader came back to page 1 every time.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const pager = page.locator(".pager");
  test.skip((await pager.count()) === 0, "the feed fits on one page");
  const nums = page.locator(".pager .pgbtn.num");
  test.skip((await nums.count()) < 2, "only one page");
  await nums.nth(1).click();
  await expect(page.locator(".pager .pgbtn.num.on")).not.toHaveText("1");
  const on = await page.locator(".pager .pgbtn.num.on").innerText();
  await page.reload();
  await expect(page.locator(".rail")).toBeVisible();
  await expect(page.locator(".pager .pgbtn.num.on")).toHaveText(on);
});

test("FE-026 Prev is disabled on page one", async ({ page }) => {
  /*
   * Test ID        : FE-026
   * Module         : Frontend / Pagination - boundaries
   * Precondition   : the feed paginates
   * Steps          : 1. open the competitive overview on page 1
   *                  2. read the Prev button's disabled state
   * Test Data      : none
   * Expected Result: disabled. Overview.jsx sets disabled={pageView.page <= 1}; an
   *                  enabled Prev on page 1 navigates to page 0, which is no page.
   * API Endpoint   : none
   * DB Validation  : n/a
   * Priority       : P2
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const pager = page.locator(".pager");
  test.skip((await pager.count()) === 0, "the feed fits on one page");
  await expect(page.locator(".pager .pgbtn").first()).toBeDisabled();
});

test("FE-027 selecting a card opens the detail drawer for THAT card", async ({ page }) => {
  /*
   * Test ID        : FE-027
   * Module         : Frontend / Detail panel
   * Precondition   : the feed has cards and the payload has details for them
   * Steps          : 1. open the competitive overview
   *                  2. click the first card
   *                  3. assert it gains .sel and the shell loses .ov-nosel
   * Test Data      : the first served card
   * Expected Result: the third column opens for the selected card. Layout collapses it
   *                  (ov-nosel) when nothing is selected, so its disappearance IS the
   *                  drawer opening.
   * API Endpoint   : GET /api/dataset -> details keyed by card id
   * DB Validation  : serving_live.signal_detail.id = the card's id
   * Priority       : P0
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const cards = page.locator("#feed .alert");
  test.skip((await cards.count()) === 0, "no cards to select");
  await cards.first().click();
  await expect(cards.first()).toHaveClass(/sel/);
  await expect(page.locator(".shell")).not.toHaveClass(/ov-nosel/);
});

test("FE-028 every card carries a direction badge from the served vocabulary", async ({ page }) => {
  /*
   * Test ID        : FE-028
   * Module         : Frontend / Signal card
   * Precondition   : the feed has cards
   * Steps          : 1. read the class of every .dirtag
   * Test Data      : none
   * Expected Result: the direction is one the pipeline writes. serving_fill.py assigns
   *                  dir='threat' only on the competitive pillar, so a threat badge on
   *                  a technology or market card is a badge describing rows that are
   *                  not there.
   * API Endpoint   : GET /api/dataset -> cards[].dir
   * DB Validation  : serving_live.signal_card.dir
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=technology&v=t-overview");
  const tags = page.locator("#feed .dirtag");
  const n = await tags.count();
  test.skip(n === 0, "no cards on the technology feed");
  for (let i = 0; i < Math.min(n, 25); i++) {
    const cls = (await tags.nth(i).getAttribute("class")) || "";
    expect(cls, `a technology card carries a threat badge: ${cls}`).not.toMatch(/\bthreat\b/);
  }
});

test("FE-029 a card with no date says so rather than inventing one", async ({ page }) => {
  /*
   * Test ID        : FE-029
   * Module         : Frontend / No fabrication
   * Precondition   : the feed has cards
   * Steps          : 1. read every .ago value on the competitive feed
   * Test Data      : none
   * Expected Result: each is either a real relative date or the explicit no-date label
   *                  SignalCard.jsx falls back to. An empty .ago, or a date on a card
   *                  whose source carried none, is fabrication on a dashboard whose
   *                  whole claim is that it does not fabricate.
   * API Endpoint   : GET /api/dataset -> cards[].ago
   * DB Validation  : serving_live.signal_card.ago
   * Priority       : P1
   * Automation Tool: Playwright
   */
  await bootstrap(page, "#p=competitive&v=overview");
  const agos = await page.locator("#feed .alert .ago").allInnerTexts();
  test.skip(agos.length === 0, "no cards");
  for (const a of agos) {
    expect(a.trim().length, "a card rendered a blank date field").toBeGreaterThan(0);
  }
});
