/* Two answer engines, both offline and both grounded only in the loaded dataset.

   scopedAnswer  — the per-panel bar. Answers ONLY about the item selected in that
                   panel, so it cannot drift into a different pillar's data.
   groundedAnswer— the floating cross-pillar assistant. Resolves a company, country
                   or kVA band out of the question and answers from the whole corpus.

   Neither calls out to a model. Every sentence they return is assembled from fields
   that are on screen somewhere else, which is what makes them auditable. */
import { edgeVerdict } from "./edge.js";
import { stripTags } from "./html.js";

const MAT_LAB = {
  lab: "Lab / research",
  dev: "In development",
  prod: "In production",
  fielded: "Fielded",
};

const fmtList = (arr) => arr.filter(Boolean).map((x) => `• ${x}`).join("<br>");
const clean = stripTags;

/* ---- answer engine: answers ONLY from the given scoped context object ---- */
export function scopedAnswer(d, ctx, question) {
  if (!ctx) return "Select an item in this panel first, then ask me about it.";
  const clientName = (d && d.client && (d.client.short || d.client.name)) || "KSSL";
  const q = question.toLowerCase().trim();
  const has = (...ks) => ks.some((k) => q.includes(k));
  const T = ctx.type;

  // POSITIONING matchup
  if (T === "matchup") {
    const m = ctx.data;
    if (has("spec", "compare", "difference", "gap", "range", "weight", "rate", "number"))
      return (
        `Spec comparison — ${m.comp} vs ${m.bf}:<br>` +
        m.specs
          .map((s) => {
            if (s.cn == null || s.kn == null) return `• ${s.l}: ${s.cv} vs ${clientName} ${s.kv}`;
            const lead =
              s.cn === s.kn
                ? "parity"
                : s.hi
                  ? s.kn > s.cn
                    ? `${clientName} leads`
                    : "competitor leads"
                  : s.kn < s.cn
                    ? `${clientName} leads`
                    : "competitor leads";
            return `• ${s.l} — ${s.cv} vs ${clientName} ${s.kv}${s.u ? ` ${s.u}` : ""} (${lead})`;
          })
          .join("<br>")
      );
    if (has("edge", "who is winning", "who wins", "ahead", "behind", "stand"))
      return (
        (m.edge == null
          ? `${clientName} spec undisclosed for this pairing — competitor data is real and sourced; no edge index computed.<br>`
          : `Competitive edge index: <b>${m.edge}/100</b> — ${edgeVerdict(m.edge, clientName).phrase}.<br>`) +
        clean(m.verdict)
      );
    if (has("advantage", "strength", "kssl", "kalyani"))
      return (
        `<b>${clientName} advantages:</b><br>${fmtList((m.advBf || []).map(clean))}` +
        `<br><br><b>${m.compBy.split(" ")[0]} advantages:</b><br>${fmtList((m.advComp || []).map(clean))}`
      );
    if (has("verdict", "summary", "bottom line", "should", "recommend", "action"))
      return clean(m.verdict);
    if (has("who", "what", "make", "competitor", "company"))
      return `${m.comp} (by ${m.compBy}), matched against ${clientName}'s ${m.bf} in ${m.cat}.`;
    return `This matchup pits <b>${m.comp}</b> against ${clientName}'s <b>${m.bf}</b>. Ask about specs, the edge index, ${clientName} advantages, or the verdict. ${clean(m.verdict).slice(0, 200)}…`;
  }

  // TENDER assessment
  if (T === "tender") {
    const t = ctx.data;
    if (has("require", "spec", "need", "criteria", "ask"))
      return `<b>${t.title}</b> requires:<br>${t.req.map((r) => `• ${r[0]}: ${r[1]}`).join("<br>")}`;
    if (has("fit", "match", "kssl", "kalyani", "product", "bid", "win", "chance"))
      return (
        `${clientName} match for this tender:<br>${t.matches.map((mt) => `• ${mt.n} — ${mt.pct} fit`).join("<br>")}` +
        `<br><br>Bid lean: <b>${t.lean}</b>. ${clean(t.leanTxt)}`
      );
    if (has("value", "worth", "size", "money", "cost"))
      return `${t.title} — value ${t.value}, issued by ${t.issuer} (${t.country}). ${t.timing || t.deadline}.`;
    if (has("country", "where", "who", "issuer"))
      return `${t.title} is issued by ${t.issuer} in ${t.country}.`;
    if (has("should", "recommend", "assessment", "lean", "go", "pass"))
      return `Bid assessment: <b>${t.lean}</b>. ${clean(t.leanTxt)}`;
    return `<b>${t.title}</b> (${t.country}, ${t.value}). Ask about the requirements, ${clientName} fit, value, or the bid assessment.`;
  }

  // TECHNOLOGY innovation
  if (T === "tech") {
    const iv = ctx.data;
    if (has("matter", "why", "impact", "important", "so what")) return clean(iv.impact);
    if (has("position", "ahead", "behind", "parity", "stand", "where"))
      return `${clientName} is <b>${{ behind: "BEHIND", parity: "AT PARITY", ahead: "AHEAD" }[iv.gap]}</b> here. ${clean(iv.compNote)}`;
    if (has("new", "latest", "recent", "update", "happening")) return clean(iv.whatsNew);
    if (has("action", "should", "recommend", "do"))
      return `${clean(iv.whatsNew)} ${clean(iv.body)}`;
    if (has("what is", "what it", "describe", "explain", "background")) return clean(iv.body);
    if (has("mature", "stage", "status", "fielded", "ready"))
      return `${iv.t} — maturity: ${(MAT_LAB[iv.mat] || iv.mat).toLowerCase()}, horizon ${iv.horizon}.`;
    if (has("source", "sourced")) return `Sources: ${clean(iv.sources)}`;
    return `<b>${iv.t}</b>. Ask why it matters, ${clientName}'s position, or what's new. ${clean(iv.impact).slice(0, 180)}…`;
  }

  // PARTNERSHIP (competitor or partner)
  if (T === "partner") {
    const c = ctx.comp;
    const p = ctx.partner;
    if (p) {
      if (has("what", "deal", "scope", "value", "programme", "detail", "country", "when", "date"))
        return (
          `<b>${p.label}</b> (${p.country || "—"}) — ${p.ptype || ""}. ${p.note}` +
          `${p.deal && p.deal !== "n/d" ? `<br>Deal/scale: ${p.deal}` : ""}<br>Timeline: ${p.date}`
        );
      if (has("mean", "matter", "impact", "kssl", "kalyani", "so what", "why")) return clean(p.mean);
      if (has("happening", "insight", "now", "update")) return clean(p.insight || p.mean);
      return `<b>${c.name} ↔ ${p.label}</b> (${p.country || "—"}). ${p.note}. ${clean(p.mean)}`;
    }
    if (has("partner", "alliance", "ally", "who", "relationship", "tie"))
      return (
        `${c.name} has ${c.partners.length} tracked relationships:<br>` +
        c.partners.map((pp) => `• ${pp.label} (${pp.country || "—"}) — ${pp.ptype || ""}`).join("<br>")
      );
    if (has("update", "latest", "recent", "new")) return clean(c.updates);
    if (has("threat", "mean", "matter", "assess", "kssl", "kalyani", "should")) return clean(c.assess);
    if (has("country", "where", "based", "hq"))
      return `${c.name} is based in ${c.hq || "—"}. Partner nationalities: ${[
        ...new Set(c.partners.map((pp) => pp.country).filter(Boolean)),
      ].join(", ")}.`;
    return `<b>${c.name}</b> — ${c.partners.length} alliances. Ask about its partners, latest updates, or the threat assessment. ${clean(c.assess).slice(0, 180)}…`;
  }

  // GEO product
  if (T === "geo") {
    const p = ctx.data;
    const comp = ctx.comp;
    const country = ctx.country;
    const kc = ctx.counter;
    const actLabel = d.actLabel || {};
    if (has("kssl", "kalyani", "counter", "compete", "match", "our product"))
      return kc
        ? `${clientName} counters with <b>${kc.p}</b>. ${kc.note}`
        : `${clientName} has no direct like-for-like product for this — a portfolio gap rather than a contested bid.`;
    if (has("value", "worth", "quantity", "how many", "deal"))
      return `${p.name} — quantity: ${p.qty}, value: ${p.val}, stage: ${p.stage}.`;
    if (has("activity", "local", "export", "produce", "make"))
      return `${p.name} in ${country}: ${actLabel[p.c] || p.c}. ${p.note}`;
    if (has("what", "describe", "about", "detail"))
      return `<b>${p.name}</b> (${comp} → ${country}): ${p.note}`;
    if (has("mean", "matter", "impact", "so what", "threat"))
      return p.c === "lp"
        ? `Local production gives full local-content credit in ${country}, disadvantaging ${clientName}'s import-based bids.`
        : p.c === "ex"
          ? "Export/supply only — weaker local-content standing than a domestic producer."
          : "Partnership/sustainment presence that can precede platform competition.";
    return `<b>${p.name}</b> — ${comp} in ${country}. ${kc ? `${clientName} counters with ${kc.p}.` : `No direct ${clientName} counterpart.`} Ask about value, activity, or the ${clientName} counter.`;
  }

  // OVERVIEW signal
  if (T === "signal") {
    const sig = ctx.data;
    if (has("matter", "why", "impact", "so what", "relevance", "exposed", "expose"))
      return clean(sig.why);
    if (has("value", "worth", "quantity", "how many", "category", "market", "actor", "fact", "detail", "data"))
      return (sig.facts || []).map((f) => `• ${f[0]}: ${f[1]}`).join("<br>");
    if (has("what happened", "happen", "what is", "about", "describe")) return clean(sig.what);
    return `<b>${sig.title}</b><br>${clean(sig.what)}<br><br><b>Why it matters:</b> ${clean(sig.why)}`;
  }

  return `I can only answer about the item shown in this panel. Try asking about its specs, value, ${clientName} relevance, or what it means.`;
}

/* ---- build a compact, grounded knowledge base from the platform's real datasets ---- */
export function buildKnowledgeBase(d) {
  if (!d) return { competitors: {}, matchups: [], geo: [], tenders: [], technology: [] };
  const clientName = (d && d.client && (d.client.short || d.client.name)) || "KSSL";
  const matchupsList = Array.isArray(d.matchups) ? d.matchups : Object.values(d.matchups || {});
  const geoList = Array.isArray(d.geoRows) ? d.geoRows : Object.values(d.geoRows || {});
  const tendersList = Array.isArray(d.tenders) ? d.tenders : Object.values(d.tenders || {});
  const techList = Array.isArray(d.techItems) ? d.techItems : Object.values(d.techItems || {});

  const matchups = matchupsList.map((m) => ({
    id: m.id,
    category: m.cat || m.category || "",
    competitor: `${m.comp || m.competitor || ""} (${m.compBy || ""})`,
    koelProduct: m.bf,
    edge: m.edge,
    verdict: m.verdict,
  }));
  const geo = geoList.map((g) => ({
    country: g.country,
    company: g.comp || g.company || "",
    product: g.name || g.product || "",
    category: g.c || g.category || "",
  }));
  const tenders = tendersList.map((t) => ({
    id: t.id,
    title: t.title,
    country: t.country,
    category: t.cat || t.category || "",
    value: t.value,
    lean: t.lean,
    match: (t.matches && t.matches[0] && t.matches[0].n) || "—",
  }));
  const technology = techList.map((t) => ({
    innovation: t.t || t.innovation || "",
    domain: t.dom || t.domain || "",
    koelPosition: t.gap || t.koelPosition || "",
    maturity: t.mat || t.maturity || "",
  }));
  return {
    competitors: d.competitors || {},
    matchups,
    geo,
    tenders,
    technology,
  };
}

/* ---- cross-pillar answer engine: answers across all loaded pillars ---- */
export function groundedAnswer(d, question, ctx) {
  if (!d) return "No data loaded yet.";
  const clientName = (d && d.client && (d.client.short || d.client.name)) || "KSSL";
  const q = question.toLowerCase().trim();
  const kb = buildKnowledgeBase(d);
  const sel = ctx && ctx.data ? ctx.data.title || ctx.data.comp || ctx.data.t || ctx.data.name || null : null;
  const selPillar = ctx ? ctx.pillar : null;

  const matchCategory = (str) => {
    const cats = [...new Set(kb.matchups.map((m) => m.category))];
    return cats.find((c) => str.includes(c.toLowerCase()));
  };
  /* Competitors are keyed by short code (MIL, LT, ZEN), and a bare substring
     test against those codes answered "…in the military market?" with a full
     dossier on Munitions India, "what is the resu(lt)" with L&T, and "citi(zen)"
     with Zen. Match the company NAME on a word boundary, and only accept a code
     when it is written as its own word. */
  const matchCompany = (str) => {
    const cos = Object.keys(kb.competitors);
    const wordIn = (needle) =>
      needle.length > 1 && new RegExp(`(^|[^a-z0-9])${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`, "i").test(str);
    const byName = cos.find((c) => {
      const nm = ((kb.competitors[c] && kb.competitors[c].name) || "").toLowerCase();
      return nm && (wordIn(nm) || wordIn(nm.split(/\s+/)[0]));
    });
    return byName || cos.find((c) => wordIn(c.toLowerCase()));
  };
  const matchCountry = (str) => {
    const countries = [...new Set(kb.geo.map((g) => g.country))];
    return countries.find((c) => str.includes(c.toLowerCase()));
  };

  const li = (arr) => arr.map((x) => `• ${x}`).join("<br>");
  const vague = /(who|what|where|how|tell me|explain|describe|show|which)/.test(q) && q.split(" ").length <= 4;

  // INTENT: competitors in <country>
  const country = matchCountry(q);
  if (country && /(who|competitors?|players?|active|present|brands?|companies)/.test(q)) {
    const inCountry = kb.geo.filter((g) => g.country.toLowerCase() === country.toLowerCase());
    const comps = [...new Set(inCountry.map((g) => `${g.company} (${g.product})`))];
    if (comps.length) {
      return `Competitor presence in <b>${country}</b> (Geo Footprint pillar):<br><br>${li(comps)}<span class="src">Source · Geo Footprint pillar</span>`;
    }
    const selT = kb.tenders.find((x) => sel && sel.includes(x.title));
    if (selT) {
      const inCat = kb.matchups.filter((m) =>
        m.category.toLowerCase().includes((selT.category.split(" ")[0] || "").toLowerCase()),
      );
      const comps = [...new Set(inCat.map((m) => m.competitor.split(" · ")[0]))];
      if (comps.length) {
        return `No dedicated footprint is tracked for <b>${country}</b> yet, but the competitors ${clientName} faces in <b>${selT.category}</b> (this tender's category) are:<br><br>${li(comps)}<br><br><i>Regional incumbents in ${country} would be confirmed once market-level data is ingested.</i><span class="src">Inferred · Positioning + Tender pillars</span>`;
      }
    }
    return `No competitor footprint is recorded for <b>${country}</b> in the current data. The Geo Footprint pillar currently tracks: ${[
      ...new Set(kb.geo.map((g) => g.country)),
    ].join(", ")}.`;
  }

  // INTENT: who competes in <category>
  const cat = matchCategory(q);
  if (cat && /(who|which|competes|competitors?|players?|rivals?)/.test(q)) {
    const inCat = kb.matchups.filter((m) => m.category.toLowerCase().includes(cat.toLowerCase()));
    const comps = [...new Set(inCat.map((m) => m.competitor))];
    if (comps.length) {
      return `In <b>${cat}</b>, ${clientName} faces these competitor products (Positioning pillar):<br><br>${li(comps)}<br><br>${clientName} counterpart: <b>${inCat[0].koelProduct || "—"}</b>.<span class="src">Source · Positioning pillar</span>`;
    }
    const geoCompNames = [...new Set(kb.geo.map((g) => g.company))];
    return `In <b>${cat}</b>, the tracked competitors are ${geoCompNames.join(", ")}. Select a product in Positioning for a head-to-head against ${clientName}.`;
  }

  // INTENT: which tenders fit / best tenders / opportunities
  if (/(tender|opportunit|bid|rfp|fit)/.test(q)) {
    let list = kb.tenders.slice();
    if (cat) list = list.filter((t) => t.category === cat);
    if (country) list = list.filter((t) => t.country === country);
    const go = list.filter((t) => t.lean === "go");
    const maybe = list.filter((t) => t.lean === "maybe");
    if (list.length) {
      const fmt = (t) => `<b>${t.title}</b> (${t.country}, ${t.value}) — ${t.match}, lean: ${t.lean}`;
      let ans = "";
      if (go.length)
        ans += `Strong-fit tenders${cat ? ` in ${cat}` : ""}${country ? ` in ${country}` : ""}:<br>${go.slice(0, 5).map(fmt).join("<br>")}`;
      if (maybe.length)
        ans += `${ans ? "<br><br>" : ""}Selective:<br>${maybe.slice(0, 4).map(fmt).join("<br>")}`;
      return `${ans}<span class="src">Source · Market › Tender Pipeline</span>`;
    }
    return `No tenders match${cat ? ` in ${cat}` : ""}${country ? ` in ${country}` : ""} in the current pipeline. The pipeline tracks ${kb.tenders.length} tenders across ${[...new Set(kb.tenders.map((t) => t.country))].length} countries.`;
  }

  // INTENT: tell me about <company> / company profile
  const company = matchCompany(q) || (vague && selPillar === "Partnerships" ? sel : null);
  if (company && kb.competitors[company]) {
    const c = kb.competitors[company];
    const prods = [...new Set(c.products)].slice(0, 8);
    const markets = [...new Set(kb.geo.filter((g) => g.company === company).map((g) => g.country))];
    const mu = kb.matchups.filter((m) =>
      m.competitor.toLowerCase().includes(company.split(" ")[0].toLowerCase()),
    );
    let ans = `<b>${company}</b>`;
    if (c.sector) ans += ` · ${c.sector}`;
    if (prods.length) ans += `<br><br>Products tracked: ${prods.join(", ")}`;
    if (markets.length) ans += `<br><br>Markets: ${markets.join(", ")}`;
    if (mu.length)
      ans += `<br><br>Competes with ${clientName} in: ${[...new Set(mu.map((m) => m.category))].join(", ")}`;
    if (c.threatNote) ans += `<br><br>${c.threatNote}`;
    return `${ans}<span class="src">Source · Competitive pillars</span>`;
  }

  // INTENT: cross-pillar mapping for current selection
  if (/(map|connect|cross|other pillar|related|link)/.test(q) && sel) {
    const parts = [];
    const selCat = matchCategory(sel) || cat;
    if (selCat) {
      const t = kb.tenders.filter((x) => x.category === selCat);
      const tech = kb.technology.filter((x) =>
        x.domain.toLowerCase().includes((selCat.split(" ")[0] || "").toLowerCase()),
      );
      const mu = kb.matchups.filter((m) => m.category.toLowerCase().includes(selCat.toLowerCase()));
      if (mu.length)
        parts.push(`<b>Competitive:</b> ${[...new Set(mu.map((m) => m.competitor))].join(", ")}`);
      if (t.length)
        parts.push(
          `<b>Market:</b> ${t.length} open tender(s) — ${t.slice(0, 3).map((x) => `${x.title} (${x.country})`).join("; ")}`,
        );
      if (tech.length)
        parts.push(
          `<b>Technology:</b> ${tech.slice(0, 2).map((x) => `${x.innovation} (${clientName} ${x.koelPosition})`).join("; ")}`,
        );
    }
    if (parts.length)
      return `Cross-pillar view for <b>${sel}</b>:<br><br>${parts.join("<br><br>")}<span class="src">Source · all pillars</span>`;
  }

  // INTENT: what should client do — the platform is descriptive, not prescriptive
  if (/(what should|recommend|advice|should kssl|should kalyani|strategy|do about)/.test(q)) {
    if (sel) {
      const mu = kb.matchups.find(
        (m) => `${m.competitor} vs ${m.koelProduct}` === sel || sel.includes(m.competitor),
      );
      if (mu && mu.verdict)
        return `${mu.verdict}<span class="src">Source · Positioning verdict</span>`;
      const t = kb.tenders.find((x) => sel.includes(x.title));
      if (t)
        return `On <b>${t.title}</b>: the matched ${clientName} product is ${t.match}. Open the tender for the full descriptive assessment.<span class="src">Source · Tender assessment</span>`;
    }
    return "This platform reports the competitive picture descriptively — positions, verdicts and structural reads — rather than prescribing moves. Select a matchup, competitor or tender and I'll surface what the data shows about it.";
  }

  // INTENT: technology / who is ahead/behind
  if (/(technolog|innovation|ahead|behind|parity|r&d|emerging)/.test(q)) {
    let tech = kb.technology.slice();
    if (cat) {
      const cs = (cat.split(" ")[0] || "").toLowerCase().slice(0, 4);
      tech = tech.filter((t) => {
        const dom = t.domain.toLowerCase();
        return dom.slice(0, 4) === cs || dom.includes(cs) || cs.includes(dom.slice(0, 4));
      });
    }
    if (tech.length) {
      return `Technology landscape${cat ? ` · ${cat}` : ""}:<br><br>${tech
        .slice(0, 6)
        .map((t) => `<b>${t.innovation}</b> — ${clientName} ${t.koelPosition}, ${t.maturity}`)
        .join("<br>")}<span class="src">Source · Technology pillar</span>`;
    }
  }

  // vague reference but we have a selection: describe it
  if (vague && sel) {
    return `You're looking at <b>${sel}</b> (${selPillar}). Ask me who competes here, how it maps to tenders, or the technology landscape.`;
  }

  // fallback: orient the user with what IS answerable
  return (
    "I can answer from the platform's intelligence across all three pillars. Try:<br><br>" +
    '• "Who are the competitors in <i>India</i>?" (or any market)<br>' +
    '• "Who competes in <i>Artillery</i>?" (or any category)<br>' +
    `• "Which tenders fit ${clientName} best?"<br>`
  );
}
