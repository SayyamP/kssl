/* Layout audit of the RENDERED dashboard. Fails on real geometry, not on pixels.
 *
 *     node ui_audit.mjs                      # against http://127.0.0.1:5179 (vite preview)
 *     node ui_audit.mjs https://host         # against a deployment
 *     UI_USER=... UI_PASS=... node ui_audit.mjs https://host      # behind basic auth
 *
 * Needs a browser, so it is NOT part of the Dockerfile's hermetic chain. CI installs
 * playwright + chromium and runs it against `npm run preview`.
 *
 * WHY THIS EXISTS
 * ---------------
 * The 32 test_*.mjs files assert data-shape and logic. Not one of them renders anything,
 * so a class name that matches no CSS rule is invisible to every gate in the build. That
 * is what shipped: `.lh-note` was written as `.tech-list-h .lh-note`, the domain notice
 * below the header is a SIBLING of that header, and it rendered 14px Archivo across 1368px
 * beside an 11px mono note -- on all eight Technology tabs. The build was green.
 *
 * WHY NOT SCREENSHOT DIFFING
 * --------------------------
 * A pixel differ needs a baseline, and the baseline would have been taken from the broken
 * page. Every check below is an INVARIANT: wrong on its own terms, on a first run, with
 * nothing to compare against. (Surveyed first: axe-core, Pa11y and Lighthouse have no rule
 * for overflow, clipping, truncation or overlap and would all report these pages clean.)
 *
 * THE CHECKS
 *   1  same-class-two-renderings   two elements share a class but render at different
 *                                  font-size/family -- the descendant-only-rule signature
 *   2  text-truncated              scrollWidth > clientWidth where text-overflow:ellipsis
 *   3  content-clipped             the same, where nothing asked for a scroller
 *   4  escapes-parent              a child's rect outside its parent's padding box
 *   5  page-scrolls-sideways       documentElement.scrollWidth > clientWidth
 *   +  console errors and failed requests
 *
 * THE CANARY (--canary, and CI runs it)
 * -------------------------------------
 * Breaks the page on purpose and requires checks 1 and 2 to fire. A harness that has
 * quietly stopped asserting looks exactly like a harness with nothing to report, and this
 * repo has shipped that before: 16 crawler test files ran zero assertions and reported
 * green for weeks. The canary is the difference between "clean" and "asleep".
 */
import { chromium } from "playwright";

const BASE = process.argv.find((a) => a.startsWith("http")) || "http://127.0.0.1:5179";
const CANARY_ONLY = process.argv.includes("--canary");
const VIEWPORT = { width: 1600, height: 1000 };

/* Deliberate exceptions. Each carries its reason, and a rule that matches NOTHING is a
   failure in its own right -- a stale allowance silently un-suppresses nothing and hides
   the next real finding. */
const ALLOW = [
  { sel: ".topbar", check: "content-clipped",
    why: "the .topbar::after scan sweep animates to translateX(100vw+140px); it is a "
       + "decorative pseudo-element on an infinite animation, so its width is a function "
       + "of when the probe ran, not of the layout" },
  { sel: ".leaflet-container", check: "content-clipped",
    why: "Leaflet sizes its own tile pane wider than the viewport on purpose" },
  { sel: ".statusbox", check: "same-class-two-renderings",
    why: "chrome.css deliberately renders `.statusbox.client .v` as 14px sans and "
       + "`.statusbox .v` as 12px mono -- the client chip and the live-status chip are "
       + "different widgets that happen to share a one-letter class name" },
  /* State MODIFIERS, not styles. `threat`/`fav`/`watch` mark severity, and the same word
     is put on a 6px severity dot and on a 9px mono badge label. A modifier is expected to
     look different on different elements -- that is what makes it a modifier -- so the
     one-class-two-renderings rule does not apply to these four. */
  { token: "threat", check: "same-class-two-renderings", why: "severity modifier" },
  { token: "fav", check: "same-class-two-renderings", why: "severity modifier" },
  { token: "watch", check: "same-class-two-renderings", why: "severity modifier" },
  { sel: ".ln-trend-txt", check: "text-truncated",
    why: "headline cells in the profile's trend list are a fixed narrow column; the full "
       + "text is one click away on the card" },
];

/* Every pillar and view the router serves. */
const ROUTES = [
  ["competitive", "overview"], ["competitive", "profile"], ["competitive", "products"],
  ["competitive", "positioning"], ["competitive", "partnerships"], ["competitive", "geo"],
  ["competitive", "patents"],
  ["market", "overview"], ["market", "tenders"], ["market", "matchups"],
  ["technology", "overview"], ["technology", "innovation"],
];

const PROBE = (allow) => {
  const px = (v) => Math.round(parseFloat(v) * 10) / 10;
  const out = { sameClass: [], truncated: [], clipped: [], escaped: [], allowHit: [] };
  const byClass = new Map();

  const allowed = (el, check) => {
    for (const a of allow) {
      if (a.check !== check || !a.sel) continue;
      if (el.closest(a.sel)) { out.allowHit.push(a.sel + "|" + a.check); return true; }
    }
    return false;
  };
  const allowedToken = (tok, check) => {
    for (const a of allow) {
      if (a.check !== check || a.token !== tok) continue;
      out.allowHit.push(a.token + "|" + a.check);
      return true;
    }
    return false;
  };
  const label = (el) => {
    const c = String(el.className || "").trim();
    return el.tagName.toLowerCase() + (c ? "." + c.split(/\s+/).join(".") : "");
  };
  const text = (el) => (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 62);

  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (cs.visibility === "hidden" || cs.display === "none") continue;
    if (parseFloat(cs.opacity) < 0.05) continue;

    /* 1: one class, two renderings. Bucket by each class TOKEN, not by the whole
       className string. The two `.lh-note` elements stopped sharing a string the moment
       one gained a `tech-list-note` modifier, and a whole-string check went blind to the
       very bug it was written for -- which is exactly what the canary reported. */
    const cls = String(el.className || "").trim();
    if (cls) {
      const rec = {
        fs: px(cs.fontSize),
        ff: cs.fontFamily.split(",")[0].replace(/["']/g, "").trim(),
        w: Math.round(r.width), t: text(el),
        ok: allowed(el, "same-class-two-renderings"),
      };
      for (const tok of new Set(cls.split(/\s+/))) {
        if (!tok) continue;
        if (!byClass.has(tok)) byClass.set(tok, []);
        byClass.get(tok).push(rec);
      }
    }

    /* 2 and 3: content wider than its box */
    const over = el.scrollWidth - el.clientWidth;
    if (over > 2 && el.clientWidth > 0 && !/(auto|scroll)/.test(cs.overflowX)) {
      const ell = cs.textOverflow === "ellipsis";
      const check = ell ? "text-truncated" : "content-clipped";
      if (!allowed(el, check)) {
        (ell ? out.truncated : out.clipped).push({
          el: label(el), need: el.scrollWidth, has: el.clientWidth, t: text(el),
        });
      }
    }

    /* 4: outside the parent's padding box. Positioned elements are exempt -- being
       outside the parent is what position:absolute is for -- and so is any parent that
       scrolls, where sticking out is the normal state of a scrolled child. */
    const p = el.parentElement;
    if (p && p !== document.body && !/(absolute|fixed|sticky)/.test(cs.position)) {
      const pcs = getComputedStyle(p);
      if (!/(auto|scroll)/.test(pcs.overflowX) && !/(auto|scroll)/.test(pcs.overflowY)) {
        const pr = p.getBoundingClientRect();
        const l = pr.left + parseFloat(pcs.borderLeftWidth || 0);
        const rt = pr.right - parseFloat(pcs.borderRightWidth || 0);
        if (pr.width > 0 && (l - r.left > 2 || r.right - rt > 2)) {
          out.escaped.push({
            el: label(el), parent: label(p),
            outLeft: Math.round(l - r.left), outRight: Math.round(r.right - rt), t: text(el),
          });
        }
      }
    }
  }

  /* A class rendering at 10.5px in one section and 12px in another is a deliberate
     scale step; a class rendering as 11px mono in one place and 14px sans in another is a
     rule that did not apply. Report a DIFFERENT FAMILY, or a size ratio of 1.25 or more --
     the reported bug was both (11px mono vs 14px Archivo, ratio 1.27). Under that
     threshold the check would fire on every considered typographic variation and be
     switched off within a week, which is the same as not having it. */
  for (const [key, seen] of byClass) {
    if (seen.length < 2) continue;
    if (seen.every((v) => v.ok)) continue;          // every instance is an allowed one
    if (allowedToken(key, "same-class-two-renderings")) continue;
    const variants = [...new Map(seen.map((s) => [s.fs + "|" + s.ff, s])).values()];
    if (variants.length < 2) continue;
    const sizes = variants.map((v) => v.fs);
    const ratio = Math.max(...sizes) / Math.min(...sizes);
    const families = new Set(variants.map((v) => v.ff));
    if (families.size < 2 && ratio < 1.25) continue;
    out.sameClass.push({ cls: key, n: seen.length, ratio: Math.round(ratio * 100) / 100,
                         variants });
  }

  out.page = {
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  };
  return out;
};

async function settle(page) {
  await page.evaluate(() => document.fonts && document.fonts.ready);
  // Finite animations only: .topbar::after runs forever by design, so waiting on every
  // animation would hang. The panel slides are ~.42s and the grid transition ~.26s.
  await page.waitForTimeout(1000);
}

const browser = await chromium.launch(
  process.env.PW_CHROME ? { executablePath: process.env.PW_CHROME } : {});
const ctx = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: 1,
  httpCredentials: process.env.UI_USER
    ? { username: process.env.UI_USER, password: process.env.UI_PASS || "" }
    : undefined,
});
const page = await ctx.newPage();

const consoleErrs = [];
const netFails = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrs.push(m.text().slice(0, 180)); });
page.on("requestfailed", (r) => netFails.push(`failed ${r.url().slice(0, 110)}`));
page.on("response", (r) => { if (r.status() >= 400) netFails.push(`${r.status()} ${r.url().slice(0, 110)}`); });

const findings = [];
const add = (route, kind, d) => findings.push({ route, kind, ...d });
const allowSeen = new Set();

async function auditRoute(pillar, view, extra = "") {
  const route = `${pillar}/${view}${extra ? " " + extra : ""}`;
  const r = await page.evaluate(PROBE, ALLOW);
  for (const h of r.allowHit) allowSeen.add(h);

  if (r.page.scrollWidth > r.page.clientWidth + 2) {
    add(route, "page-scrolls-sideways", { over: r.page.scrollWidth - r.page.clientWidth });
  }
  for (const s of r.sameClass) {
    add(route, "same-class-two-renderings", {
      cls: s.cls, n: s.n,
      variants: s.variants.map((v) => `${v.fs}px ${v.ff} w=${v.w} :: "${v.t}"`),
    });
  }
  for (const t of r.truncated.slice(0, 6)) add(route, "text-truncated", t);
  for (const c of r.clipped.slice(0, 6)) add(route, "content-clipped", c);
  for (const e of r.escaped.slice(0, 6)) add(route, "escapes-parent", e);
  return r;
}

async function goto(pillar, view) {
  const url = `${BASE}/#p=${pillar}&v=${view}`;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
  } catch {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  }
  await settle(page);
}

if (!CANARY_ONLY) {
  console.log(`auditing ${BASE} at ${VIEWPORT.width}x${VIEWPORT.height}\n`);
  for (const [pillar, view] of ROUTES) {
    await goto(pillar, view);
    const body = (await page.textContent("body")) || "";
    if (body.trim().length < 200) {
      add(`${pillar}/${view}`, "blank-page", { chars: body.trim().length });
    }
    await auditRoute(pillar, view);
  }

  /* A view is not one screen. The Technology notice only renders in a domain where no
     innovation carries a dated development, so a harness that never clicks a tab cannot
     see the bug that prompted this file. */
  await goto("technology", "innovation");
  const tabs = await page.locator(".tech-cat").count();
  for (let i = 0; i < tabs; i++) {
    await page.locator(".tech-cat").nth(i).click();
    await page.waitForTimeout(500);
    const name = (await page.locator(".tech-cat").nth(i).innerText()).replace(/\s+/g, " ").trim();
    await auditRoute("technology", "innovation", `[${name}]`);
  }
  console.log(`  walked ${ROUTES.length} view(s) and ${tabs} Technology domain tab(s)`);
}

/* ---- the canary ---------------------------------------------------------------- */
await goto("technology", "innovation");
await page.addStyleTag({
  content: ".tech-list-h .lh-note{font-size:37px !important}"
         + " .svc .nm{max-width:24px !important}",
});
await page.waitForTimeout(400);
const broken = await page.evaluate(PROBE, ALLOW);
const canary = [
  ["same-class-two-renderings fires on a class rendered two ways",
    broken.sameClass.some((s) => s.cls === "lh-note")],
  ["text-truncated fires on a clamped nav label",
    broken.truncated.some((t) => /\.nm\b/.test(t.el))],
];

/* ---- report --------------------------------------------------------------------- */
await browser.close();
let bad = 0;

if (!CANARY_ONLY) {
  const byKind = {};
  for (const f of findings) (byKind[f.kind] ||= []).push(f);
  console.log(`\n${findings.length} layout finding(s)`);
  for (const kind of Object.keys(byKind).sort()) {
    console.log(`\n### ${kind} (${byKind[kind].length})`);
    for (const f of byKind[kind].slice(0, 10)) {
      const { route, kind: _k, variants, ...rest } = f;
      console.log(`  [${route}] ${JSON.stringify(rest)}`);
      for (const v of variants || []) console.log(`        ${v}`);
    }
    if (byKind[kind].length > 10) console.log(`  ... and ${byKind[kind].length - 10} more`);
  }
  bad += findings.length;

  const stale = ALLOW.filter((a) => !allowSeen.has((a.sel || a.token) + "|" + a.check));
  if (stale.length) {
    console.log(`\n### stale allowance (${stale.length}) -- matched nothing, so it is `
              + `suppressing nothing and hiding whatever replaces it`);
    for (const a of stale) console.log(`  ${a.sel || "." + a.token}  (${a.check})`);
    bad += stale.length;
  }

  /* One console error is the app reporting a DATA fact about itself, not a fault in the
     page: geo.js runs an overlap self-check on load and says the served data holds no
     spec-confirmed overlap at all. That is true, and it is what the client portfolio load
     and revive_matchups.py exist to fill. Recorded rather than silenced -- and the moment
     it stops happening the exception is itself a failure, so nobody has to remember to
     come back and delete it. */
  const KNOWN_CONSOLE = [
    { rx: /geo-overlap self-check FAILED/,
      why: "serving.matchup carries no spec-confirmed KSSL/rival overlap yet; "
         + "revive_matchups.py --apply is what fills it" },
  ];
  const errs = [...new Set(consoleErrs)];
  const known = errs.filter((e) => KNOWN_CONSOLE.some((k) => k.rx.test(e)));
  const fresh = errs.filter((e) => !known.includes(e));
  if (known.length) {
    console.log(`\n### known console error (${known.length}) -- recorded, not failing`);
    known.forEach((e) => console.log("  " + e));
  }
  for (const k of KNOWN_CONSOLE) {
    if (!errs.some((e) => k.rx.test(e))) {
      console.log(`\n### a known console error stopped happening: ${k.rx}`);
      console.log(`  ${k.why}`);
      console.log("  delete it from KNOWN_CONSOLE -- a stale exception hides the next one");
      bad += 1;
    }
  }
  if (fresh.length) {
    console.log(`\n### console errors (${fresh.length})`);
    fresh.slice(0, 8).forEach((e) => console.log("  " + e));
    bad += fresh.length;
  }
  const nets = [...new Set(netFails)];
  if (nets.length) {
    console.log(`\n### failed requests (${nets.length})`);
    nets.slice(0, 8).forEach((e) => console.log("  " + e));
    bad += nets.length;
  }
}

console.log("\ncanary -- these MUST fire on a deliberately broken page");
for (const [what, ok] of canary) {
  console.log(`  ${ok ? "ok  " : "DEAD"}  ${what}`);
  if (!ok) bad += 1;
}

if (bad) {
  console.log(`\n${bad} problem(s)`);
  process.exit(1);
}
console.log("\nok - every view and every Technology tab is clean, and the checks can still fail");
