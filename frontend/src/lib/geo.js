/* ===================================================================
   GEO MARKET OVERLAP
   A rival contests KSSL in a country only when all four hold:
     1. same country        — both have a footprint row there
     2. same product class  — both sell defence platforms, not components to primes
     3. same category       — their offerings share at least one product category
     4. same specs          — class-matched models compared spec for spec
   Anything weaker is reported as weaker rather than counted as a collision.

   Built as a factory over the dataset: the memo caches the original hung on
   `window` (_geoPairs, _geoOv) live in this closure instead, so a re-fetch gets
   a fresh set rather than answers computed from the previous corpus.
   =================================================================== */
import { edgeVerdict } from "./edge.js";
import { escAll } from "./html.js";

export function createGeo(d) {
  const { geoData, geoComps, matchups, competitors, CAT_META, counterRules, actLabel } = d;
  // A KEY, not a label: geoData is keyed by the client's id. Using the display
  // short name matched nothing, so every overlap test silently returned "none".
  const CLIENT_KEY = (d.client && (d.client.id || d.client.short)) || "KSSL";

  /* IS THERE A CLIENT FOOTPRINT AT ALL?

     Every one of the four overlap tests is "the rival does X where the CLIENT does X",
     so with no client footprint row on file not one of them can run -- geoOffer returns
     inScope:false for the client in every country and geoOverlap answers null
     everywhere. Null is also the answer for a rival that genuinely does not overlap,
     and the two were being read as the same thing: the page printed "meets KSSL in 0 of
     them" for every competitor and "KSSL absent" over 100% of countries. That is an
     absent input rendered as a discovered fact, and it is the loudest kind, because
     "absent" is the alarming answer.

     On the live serving tables there is no client footprint: wireDataset resolves
     d.client.id from a competitors row with dir='client' or a geoComps row with isBf,
     and serving_live.competitors carries only dir in {rival, threat} -- so geoData has
     no key for the client and this is false. Consumers branch on it to say the
     footprint is not established instead of asserting zero overlap. It becomes true
     with no further edits the moment a client row is served. */
  const clientFootprintKnown = Object.keys((geoData && geoData[CLIENT_KEY]) || {}).length > 0;

  const countriesForComp = (cid) => Object.keys(geoData[cid] || {});
  const compsInCountry = (country) =>
    geoComps.filter((c) => geoData[c.id] && geoData[c.id][country]);
  const productsFor = (cid, country) => (geoData[cid] && geoData[cid][country]) || [];
  const dirForAct = (c) =>
    c === "lp" ? "threat" : c === "pt" ? "threat" : c === "bf" ? "fav" : "watch";

  /* ---- product-category detection from the footprint row text ----
     Data-driven: CAT_META carries one keyword list per category (the same map the
     source platform's ksslCounter used). A row can hit several categories — "SH-15
     155mm / VT-series tanks" is artillery AND armour — so detection returns the set.
     No keyword hit -> null, and the UI says so honestly. */
  const GEO_BANDS = Object.keys(CAT_META || {});
  /* A KEYWORD IS A WORD, NOT A SUBSTRING.

     `includes` matched the UAV keyword "isr" inside "Israel" and the missile
     keyword "sam" inside "Samsung", so a sentence reading "…Rafael of Israel
     qualified in field trials…" gave Saab a UAV band and produced a UAV "overlap"
     with the client that no document supports. Keywords are matched on word
     boundaries now; a multi-word keyword ("air defence") still matches as a
     phrase, and a keyword ending in a letter still matches its plural. */
  const kwRx = {};
  function kwMatch(t, w) {
    if (!kwRx[w]) {
      const lit = w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      /* A keyword ending in a DIGIT keeps its unit: "155" has to match
         "155mm", and "sh-15" has to match "sh-15s". A keyword ending in a
         LETTER does not: that is how "isr" matched Israel and "sam" matched
         Samsung, giving companies bands no document supports. */
      const tail = /[0-9]$/.test(w) ? "(?![0-9])" : "(s|es)?([^a-z0-9]|$)";
      kwRx[w] = new RegExp(`(^|[^a-z0-9])${lit}${tail}`, "i");
    }
    return kwRx[w].test(t);
  }
  function geoCatsOf(txt) {
    const t = (txt || "").toLowerCase();
    if (!t) return null;
    const hits = GEO_BANDS.filter((k) =>
      (CAT_META[k].kw || []).some((w) => kwMatch(t, w)),
    );
    return hits.length ? hits : null;
  }
  function koelCounter(prod) {
    if (!counterRules) return null;
    const cats = geoCatsOf(
      `${prod.name || ""} ${prod.qty || ""} ${prod.val || ""} ${prod.note || ""}`,
    );
    if (!cats) return null;
    for (let i = 0; i < counterRules.length; i++) {
      const r = counterRules[i];
      if (cats.indexOf(r.band) >= 0) return r.product ? { p: r.product, note: r.note } : null;
    }
    return null;
  }

  /* Footprint rows that are not a competing defence platform: electronics, radar and
     C4I suites, and component or aerostructure supply into someone else's platform.
     Without this a radar row would read as a platform collision with KSSL. */
  const GEO_NOTGEN = /\bradar\b|electronic warfare|\bc4i\b|avionics|aerostructure|fuselage|components for|subsystems for/i;

  /* geoKvaSpan's defence equivalent: the "span" of an offering is the SET of product
     categories its rows reach, so category overlap needs the whole set rather than
     the single strongest hit the counter lookup uses. */
  function geoKvaSpan(txt) {
    return geoCatsOf(txt);
  }
  function geoBandsOf(span) {
    if (!span) return [];
    return GEO_BANDS.filter((k) => span.indexOf(k) >= 0);
  }
  function geoBandLabel(b) {
    const r = (counterRules || []).filter((z) => z.band === b)[0];
    return (r && r.label) || (CAT_META[b] && CAT_META[b].label) || b;
  }
  const geoBandShort = (b) =>
    ({
      art: "Artillery",
      ammo: "Ammunition",
      sa: "Small Arms",
      pav: "Armour",
      mro: "MRO",
      naval: "Naval",
      uav: "UAV",
      msl: "Missiles",
      pc: "Forgings",
    })[b] || b;

  // one company's defence offering in one country, merged across its rows
  function geoOffer(cid, country) {
    const rows = productsFor(cid, country);
    const cats = {};
    let def = false;
    const acts = {};
    rows.forEach((p) => {
      const txt = `${p.name || ""} ${p.qty || ""} ${p.val || ""} ${p.note || ""}`;
      if (GEO_NOTGEN.test(txt)) return;
      const cs = geoCatsOf(txt);
      acts[p.c] = 1;
      if (cs) {
        def = true;
        cs.forEach((c) => {
          cats[c] = 1;
        });
      }
    });
    const span = Object.keys(cats);
    return { span: span.length ? GEO_BANDS.filter((k) => span.indexOf(k) >= 0) : null, inScope: def, acts };
  }

  // class-matched Positioning pairs, indexed by rival name and product category
  let _pairs = null;
  function geoPairIndex() {
    if (_pairs) return _pairs;
    const m = {};
    Object.keys(matchups).forEach((k) => {
      const x = matchups[k];
      const key = `${x.compBy}||${x.catKey}`;
      (m[key] = m[key] || []).push(x);
    });
    _pairs = m;
    return m;
  }
  // a geo row is a rival if it is a tracked competitor OR it appears in the
  // Positioning corpus (the foreign primes are matched-up but not deep-tracked)
  let _muNames = null;
  /* "Bharat Electronics (BEL)" and "BEL" are the same company. geoComps spell
     the name out, competitors carry the trading name, and the corpus uses legal
     names ("Advanced Weapons and Equipment India Limited"). An exact-string join
     matched none of them, so 6 rivals and 17 country footprints were never
     tested for overlap and silently reported "no overlapping rival on file". */
  const coKey = (s) =>
    String(s || "")
      .toLowerCase()
      .replace(/\(.*?\)/g, " ")
      .replace(/\b(limited|ltd|pvt|private|company|co|inc|corporation|group|the|and|systems|defence|defense|aerospace)\b/g, " ")
      .replace(/[^a-z0-9]+/g, "")
      .trim();
  const nameLike = (a, b) => {
    const x = coKey(a);
    const y = coKey(b);
    return !!x && !!y && (x === y || x.includes(y) || y.includes(x));
  };
  const geoIsRival = (name, id) => {
    if (
      competitors &&
      Object.keys(competitors).some(
        (k) => (id && k === id) || competitors[k].name === name || nameLike(competitors[k].name, name),
      )
    )
      return true;
    if (!_muNames) {
      _muNames = {};
      Object.keys(matchups).forEach((k) => {
        _muNames[matchups[k].compBy] = 1;
      });
    }
    if (_muNames[name]) return true;
    return Object.keys(_muNames).some((n) => nameLike(n, name));
  };

  const _ov = {};
  function geoOverlap(cid, country) {
    const ck = `${cid}||${country}`;
    if (ck in _ov) return _ov[ck];
    const out = (() => {
      // no client footprint -> the comparison has no left-hand side; see
      // clientFootprintKnown. Stated here so the reason is at the test, not
      // three geoOffer calls away.
      if (!clientFootprintKnown) return null;
      const c = geoComps.filter((x) => x.id === cid)[0];
      if (!c || c.isBf) return null;
      // geoComps also carries customers (telecom tower, data-centre operators),
      // an alternator supplier and a propulsion-engine JV — none of them rivals
      if (!geoIsRival(c.name, c.id)) return null;
      const k = geoOffer(CLIENT_KEY, country);
      const r = geoOffer(cid, country);
      if (!k.inScope || !r.inScope || !k.span || !r.span) return null;
      const rb = geoBandsOf(r.span);
      const bands = geoBandsOf(k.span).filter((b) => rb.indexOf(b) >= 0);
      if (!bands.length) return null;
      const idx = geoPairIndex();
      const per = bands.map((b) => {
        const ms = idx[`${c.name}||${b}`] || [];
        let rival = 0;
        let koel = 0;
        let level = 0;
        ms.forEach((x) => {
          if (x.edge == null) return;
          const v = edgeVerdict(x.edge).cls;
          if (v === "behind") rival++;
          else if (v === "ahead") koel++;
          else level++;
        });
        const cr = counterRules.filter((z) => z.band === b)[0];
        // graded = pairs that actually produced an index. n>0 with graded===0 means
        // the pair exists but no dimension was measured on both sides.
        return {
          band: b,
          n: ms.length,
          graded: rival + koel + level,
          rival,
          koel,
          level,
          counter: (cr && cr.product) || null,
        };
      });
      const sum = (f) => per.reduce((a, x) => a + x[f], 0);
      // Confirmation is PER BAND, not per overlap. The band list comes from the free
      // text on the footprint row; the pairs come from the product catalogue, and the
      // two disagree. Caterpillar's row claims "13 kVA - 4000+ kVA" but its catalogue
      // here starts at 500 kVA, so three of its five bands have no model pair at all.
      const bandsSpec = per.filter((p) => p.graded > 0).map((p) => p.band);
      const bandsOnly = per.filter((p) => p.graded === 0).map((p) => p.band);
      return {
        comp: c,
        country,
        bands,
        per,
        n: sum("n"),
        graded: sum("graded"),
        bandsSpec,
        bandsOnly,
        tier: bandsSpec.length ? "spec" : "cat",
        rival: sum("rival"),
        koel: sum("koel"),
        level: sum("level"),
        koelSpan: k.span,
        rivalSpan: r.span,
        local: !!r.acts.lp,
        licence: !!r.acts.pt,
        exportOnly: !r.acts.lp && !!r.acts.ex,
      };
    })();
    _ov[ck] = out;
    return out;
  }

  // every rival that contests KSSL in one country
  function geoRivalsIn(country) {
    const ownData = geoData[CLIENT_KEY] || {};
    if (!ownData[country]) return [];
    return compsInCountry(country)
      .map((c) => geoOverlap(c.id, country))
      .filter(Boolean);
  }

  const geoSpanText = (s) => (s && s.length ? s.map(geoBandShort).join(" · ") : "not stated");
  // "in United States" reads wrong in every sentence this copy builds
  const geoThe = (ct) =>
    /^(United |Netherlands|Philippines|Czech)/.test(ct || "") ? `the ${ct}` : ct;

  // the marker that sits in front of the name
  function geoOvBadge(ov) {
    if (!ov) return "";
    if (ov.tier === "spec")
      return (
        '<span class="geo-ovb spec" title="Same country, same product class, ' +
        `${ov.bands.length} overlapping product categor${ov.bands.length === 1 ? "y" : "ies"}, and ${ov.graded}` +
        ` class-matched model pairs compared spec for spec in ${ov.bandsSpec.length} of them` +
        (ov.bandsOnly.length
          ? `. The other ${ov.bandsOnly.length} are claimed by the stated offering but hold no matched model.`
          : "") +
        '">◉ overlap</span>'
      );
    return (
      '<span class="geo-ovb cat" title="Same country, same product class and an overlapping ' +
      "category, but no class-matched model pair is on file — the collision is not confirmed " +
      'at spec level">◎ category only</span>'
    );
  }
  function geoOvBadgeCountry(country) {
    const rs = geoRivalsIn(country);
    if (!rs.length) return "";
    const spec = rs.filter((r) => r.tier === "spec").length;
    return spec
      ? `<span class="geo-ovb spec" title="${spec} rival${spec === 1 ? "" : "s"}` +
          ` contest KSSL here on class-matched models">◉ ${spec} contested</span>`
      : '<span class="geo-ovb cat" title="Rivals share a category here but no class-matched ' +
          `pair is on file">◎ ${rs.length} category only</span>`;
  }

  /* Three distinct states, previously collapsed into one misleading label:
     no pair on file · pair exists but no dimension measured on both sides · a verdict */
  function geoBandOutcome(p) {
    if (!p.n) return '<span class="gv-non">no matched model pair</span>';
    if (!p.graded) return '<span class="gv-non">pair found, no index computed</span>';
    if (p.rival > p.koel)
      return `<span class="gv-bad">rival leads ${p.rival} of ${p.graded}</span>`;
    if (p.koel > p.rival)
      return `<span class="gv-good">KSSL leads ${p.koel} of ${p.graded}</span>`;
    return `<span class="gv-mid">level — ${p.level} of ${p.graded} near parity</span>`;
  }

  function geoOvPanel(ov) {
    if (!ov) return "";
    const nm = escAll(ov.comp.name);
    const ct = escAll(geoThe(ov.country));
    const spec = ov.tier === "spec";
    const bandNames = ov.bands.map(geoBandShort).join(" · ");
    const specNames = ov.bandsSpec.map(geoBandShort).join(" · ");
    const onlyNames = ov.bandsOnly.map(geoBandShort).join(" · ");
    let h = `<div class="geo-ov ${spec ? "spec" : "cat"}">`;
    h +=
      `<div class="geo-ov-h"><span class="geo-ov-t">${spec ? "◉ Market overlap — confirmed on specs" : "◎ Market overlap — category only"}</span>` +
      `<span class="geo-ov-sp">${
        spec
          ? specNames +
            (ov.bandsOnly.length
              ? ` <span class="gv-non">+${ov.bandsOnly.length} range-only</span>`
              : "")
          : bandNames
      }</span></div>`;

    // the four tests, each with its evidence
    h +=
      '<div class="geo-ov-tests">' +
      `<span class="gt ok">Same country<i>both sell into ${ct}</i></span>` +
      '<span class="gt ok">Same product<i>both sell into this category here</i></span>' +
      `<span class="gt ok">Same category<i>${ov.bands.length} overlapping categor${ov.bands.length === 1 ? "y" : "ies"}</i></span>` +
      `<span class="gt ${spec ? (ov.bandsOnly.length ? "part" : "ok") : "no"}">Same specs<i>` +
      (spec
        ? `${ov.graded} matched pairs in ${ov.bandsSpec.length} of ${ov.bands.length} bands`
        : "no matched pair on file") +
      "</i></span>" +
      "</div>";

    h +=
      `<div class="geo-ov-spans"><b>${nm}</b> offers ${geoSpanText(ov.rivalSpan)}` +
      ` here · <b>KSSL</b> offers ${geoSpanText(ov.koelSpan)}` +
      ` · they meet in ${ov.bands.length} of ${GEO_BANDS.length} categories</div>`;

    if (spec) {
      h +=
        '<table class="geo-ov-tbl"><tr><th>Band</th><th class="n">Matched pairs</th>' +
        "<th>Datasheet outcome</th><th>KSSL’s answer in this category</th></tr>";
      ov.per.forEach((p) => {
        h +=
          `<tr${p.graded ? "" : ' class="gr-thin"'}><td>${escAll(geoBandLabel(p.band))}</td>` +
          `<td class="n">${p.n || "—"}</td><td>${geoBandOutcome(p)}</td>` +
          `<td class="gv-ctr">${p.counter ? escAll(p.counter) : '<span class="gv-non">no KSSL model on file</span>'}</td></tr>`;
      });
      h += "</table>";
    }

    // ---- what it means ----
    const mode = ov.local ? "local" : ov.licence ? "licence" : "export";
    const worst = ov.per
      .filter((p) => p.graded > 0)
      .sort((a, b) => b.rival - b.koel - (a.rival - a.koel))[0];
    h +=
      '<div class="geo-ov-why"><span class="gw-l">What this means for KSSL</span><ul>';
    h += spec
      ? `<li><b>Every enquiry in ${specNames} is a contested deal.</b> ${nm} sells the same class of equipment into ` +
        `the same country, and in ${ov.bandsSpec.length === 1 ? "this band" : "these bands"} the two catalogues have ` +
        `${ov.graded} pairs close enough in class to be compared line by line.` +
        (ov.bandsOnly.length
          ? ` <b>${onlyNames} ${ov.bandsOnly.length === 1 ? "is" : "are"} claimed by the footprint ` +
            `range but hold no matched model</b> — ${nm}’s catalogue here does not actually reach ` +
            `${ov.bandsOnly.length === 1 ? "it" : "them"}, so treat ${ov.bandsOnly.length === 1 ? "that band" : "those bands"}` +
            " as unproven."
          : "") +
        "</li>"
      : `<li><b>Probably contested in ${bandNames}, but not proven.</b> ${nm} sells the same class of equipment into ` +
        `the same country and its offering covers the same categor${ov.bands.length === 1 ? "y" : "ies"} — three of the ` +
        "four tests pass. What is missing is a model pair close enough in class to compare, so treat this as a lead " +
        "to check rather than a confirmed collision.</li>";
    if (mode === "local")
      h +=
        `<li><b>They build it in ${ct}; the hardest version of this overlap.</b> In-country manufacture ` +
        "prices in local currency and quotes local lead times, so the rival wins on landed cost, delivery and " +
        "spares turnaround before a single spec is compared. KSSL cannot answer that with a datasheet.</li>";
    else if (mode === "licence")
      h +=
        "<li><b>They reach this market through a partner or licence.</b> The rival carries less fixed cost than " +
        "a local plant but inherits its partner’s reach overnight — the position can scale faster than it was built.</li>";
    else
      h +=
        `<li><b>They export into ${ct}, as KSSL does.</b> Both sides carry freight, duty and longer lead times, ` +
        "so the contest stays closer to the datasheet and to dealer strength than to landed cost.</li>";
    if (spec && worst && worst.rival > worst.koel)
      h +=
        `<li><b>Weakest band: ${escAll(geoBandLabel(worst.band))}.</b> The rival takes the datasheet in ` +
        `${worst.rival} of ${worst.graded} matched pairs there, so KSSL is defending that category on price, ` +
        "financing or service rather than on measured specification.</li>";
    else if (spec && ov.koel > ov.rival)
      h +=
        `<li><b>KSSL leads the measured comparison</b> in ${ov.koel} of ${ov.graded} matched pairs across these categories, ` +
        "so the exposure here is commercial — reach, price and delivery — rather than technical.</li>";
    if (!spec)
      h +=
        "<li><b>Two things would explain the missing pair.</b> Either the two ranges do not actually meet at model " +
        `level — an overlapping category is not the same as an overlapping product class — or ${nm}’s catalogue is not yet in the ` +
        "Positioning dataset. Checking which one it is turns this from a lead into a decision.</li>";
    h += "</ul></div>";

    h +=
      '<div class="geo-ov-src">Country and category span from the footprint rows on this page · ' +
      "categories from the KSSL category definitions · " +
      (spec
        ? `matched pairs and datasheet outcome from the ${ov.graded} Positioning comparisons for this rival in ` +
          (ov.bandsOnly.length
            ? `the ${ov.bandsSpec.length} bands its catalogue reaches`
            : "these bands")
        : "no Positioning comparison available for this rival") +
      (ov.country !== "India"
        ? ` · Positioning compares datasheets, which are not country-specific, so the spec outcome describes the same models sold into ${ct}`
        : "") +
      ".</div>";
    return `${h}</div>`;
  }

  /* KSSL's own row in a country: who contests it here, and how hard. */
  function geoOwnPanel(country) {
    const rs = geoRivalsIn(country);
    const ct = escAll(geoThe(country));
    const k = geoOffer(CLIENT_KEY, country);
    /* Without a client footprint there is nothing to contest, so "no rival contests
       KSSL here" would be a conclusion drawn from a missing row. Say which row is
       missing. */
    if (!clientFootprintKnown) {
      return (
        '<div class="geo-ov none"><div class="geo-ov-h"><span class="geo-ov-t">◌ Overlap not assessed in ' +
        `${ct}</span></div>` +
        '<div class="geo-ov-why"><span class="gw-l">Why there is no answer here</span><ul>' +
        "<li><b>No KSSL footprint is on file.</b> Every overlap test compares a rival's offering against " +
        "KSSL's in the same country, and the served footprint tables carry no KSSL rows, so no test could run.</li>" +
        "<li><b>This is not a finding of ‘uncontested’.</b> Rivals may well overlap KSSL here; nothing " +
        "has been measured either way until a client footprint is served.</li>" +
        "</ul></div></div>"
      );
    }
    if (!rs.length) {
      return (
        '<div class="geo-ov none"><div class="geo-ov-h"><span class="geo-ov-t">○ No overlapping rival on file</span>' +
        `<span class="geo-ov-sp">${geoSpanText(k.span)}</span></div>` +
        '<div class="geo-ov-why"><span class="gw-l">What this means for KSSL</span><ul>' +
        "<li><b>Nothing here contests KSSL on a like-for-like platform.</b> No rival in the dataset sells into a category " +
        `into ${ct} that meets KSSL’s ${geoSpanText(k.span)}.</li>` +
        "<li><b>Read it as one of two things, not as a win.</b> Either the market is genuinely uncontested by the " +
        "tracked set — in which case pricing power here is higher than in India — or the rivals present are simply " +
        "not mapped for this country yet. The footprint rows are the limit of what can be said.</li>" +
        "</ul></div></div>"
      );
    }
    const spec = rs.filter((r) => r.tier === "spec");
    const local = rs.filter((r) => r.local);
    const hardest = spec
      .slice()
      .sort((a, b) => b.rival - b.koel - (a.rival - a.koel) || b.graded - a.graded)[0];
    let h =
      `<div class="geo-ov ${spec.length ? "spec" : "cat"}"><div class="geo-ov-h"><span class="geo-ov-t">` +
      `${spec.length ? "◉ " : "◎ "}${rs.length} rival${rs.length === 1 ? "" : "s"} overlap KSSL in ${ct}` +
      `${spec.length ? "" : " — none confirmed on specs"}</span>` +
      `<span class="geo-ov-sp">KSSL ${geoSpanText(k.span)}</span></div>`;
    h +=
      '<table class="geo-ov-tbl"><tr><th>Rival</th><th>Overlapping categories</th><th class="n">Matched pairs</th>' +
      "<th>Datasheet outcome</th><th>Presence</th></tr>";
    rs.slice()
      .sort((a, b) => b.graded - a.graded)
      .forEach((r) => {
        let out = '<span class="gv-non">no matched pair</span>';
        if (r.graded) {
          if (r.rival > r.koel)
            out = `<span class="gv-bad">rival leads ${r.rival} of ${r.graded}</span>`;
          else if (r.koel > r.rival)
            out = `<span class="gv-good">KSSL leads ${r.koel} of ${r.graded}</span>`;
          else out = '<span class="gv-mid">level</span>';
        }
        // bands its catalogue actually reaches, then the ones only its stated range claims
        const bd =
          r.bandsSpec.map(geoBandShort).join(" · ") +
          (r.bandsOnly.length
            ? `${r.bandsSpec.length ? " · " : ""}<span class="gv-non">${r.bandsOnly.map(geoBandShort).join(" · ")} (range only)</span>`
            : "");
        h +=
          `<tr><td>${escAll(r.comp.name)}</td><td>${bd}` +
          `</td><td class="n">${r.graded || "—"}</td><td>${out}</td><td>` +
          `${r.local ? '<span class="gv-bad">builds here</span>' : r.licence ? "partner / licence" : "exports in"}` +
          "</td></tr>";
      });
    h += "</table>";
    h += '<div class="geo-ov-why"><span class="gw-l">What this means for KSSL</span><ul>';
    h +=
      rs.length === 1
        ? `<li><b>The single overlap here is ${spec.length ? "confirmed at spec level" : "unconfirmed"}.</b> ` +
          (spec.length
            ? "Same country, same product class, overlapping product category, and class-matched models compared line by line."
            : "The categories meet, but no model pair is close enough in class to compare spec for spec.") +
          "</li>"
        : spec.length
          ? `<li><b>${spec.length} of the ${rs.length} overlaps ${spec.length === 1 ? "is" : "are"}` +
            " confirmed at spec level</b> — same country, same product class, overlapping category, and class-matched " +
            "models compared line by line." +
            (rs.length > spec.length
              ? ` The remaining ${rs.length - spec.length} share a category with KSSL but have no matched pair on file, so they are leads rather than proven collisions.`
              : "") +
            "</li>"
          : `<li><b>None of the ${rs.length} overlaps is confirmed at spec level.</b> All ${rs.length} sell defence platforms ` +
            `into ${ct} in a category KSSL also covers, but no class-matched model pair is on file for any of them, so ` +
            "every one is a lead to check rather than a measured collision.</li>";
    if (local.length)
      h +=
        `<li><b>${local.length} of them manufacture in ${ct}.</b> That is the hardest form of the overlap: they ` +
        "quote local currency, local lead times and local spares, which beats an equivalent imported machine before " +
        "specifications are compared.</li>";
    if (hardest && hardest.graded && hardest.rival > hardest.koel)
      h +=
        `<li><b>Sharpest exposure: ${escAll(hardest.comp.name)}.</b> It takes the datasheet in ${hardest.rival}` +
        ` of ${hardest.graded} class-matched pairs across ${hardest.bandsSpec.map(geoBandShort).join(", ")}` +
        ", so KSSL is holding that ground on price, financing or service rather than on measured specification.</li>";
    // only claim open ground where a category KSSL covers is genuinely reached by no rival
    const contested = {};
    rs.forEach((r) =>
      r.bandsSpec.forEach((b) => {
        contested[b] = 1;
      }),
    );
    const open = geoBandsOf(k.span).filter((b) => !contested[b]);
    h += open.length
      ? `<li><b>Open ground: ${open.map(geoBandShort).join(", ")}.</b> KSSL’s portfolio covers ` +
        `${open.length === 1 ? "this category" : "these categories"} in ${ct} and no rival here reaches ` +
        `${open.length === 1 ? "it" : "them"}, so KSSL quotes unopposed within the tracked set — the highest-margin volume ` +
        "in this market.</li>"
      : `<li><b>No open ground here.</b> Every category KSSL’s portfolio covers in ${ct} is reached by at least one rival, ` +
        "so there is no category in this market where KSSL quotes unopposed.</li>";
    h += "</ul></div>";
    h +=
      '<div class="geo-ov-src">Overlap from the footprint rows on this page · categories from the KSSL category ' +
      "definitions · datasheet outcome from the Positioning comparisons for each rival in the shared categories.</div>";
    return `${h}</div>`;
  }

  /* Dot state for one row of the competitor dropdown. Scoped to the selected
     country when there is one, otherwise across every market the rival is in. */
  function geoPickOverlap(c, selCountry) {
    const n = countriesForComp(c.id).length;
    const mk = `${n} mkt${n === 1 ? "" : "s"}`;
    if (c.isBf)
      return {
        cls: "bf",
        meta: mk,
        tip: `KSSL — present in ${n} market${n === 1 ? "" : "s"}`,
      };
    const scope = selCountry ? [selCountry] : countriesForComp(c.id);
    const ovs = scope.map((ct) => geoOverlap(c.id, ct)).filter(Boolean);
    /* "No overlap" is a finding; "not assessed" is not. With no client footprint on
       file the test never ran, so this dot must not be the same dot a rival earns by
       being tested and cleared -- it had been marking every rival in the roster
       "no overlap" on the strength of a missing input. */
    if (!clientFootprintKnown)
      return {
        cls: "ovl-unk",
        meta: mk,
        tip: `Overlap with KSSL not assessed${selCountry ? ` in ${selCountry}` : ""} — no KSSL footprint is on file to compare against`,
      };
    if (!ovs.length)
      return {
        cls: "noovl",
        meta: mk,
        tip: `No overlap with KSSL${selCountry ? ` in ${selCountry}` : ""} — no overlapping product category on a defence offering`,
      };
    const spec = ovs.filter((o) => o.tier === "spec");
    const where = selCountry
      ? ` in ${selCountry}`
      : ` in ${ovs.length} market${ovs.length === 1 ? "" : "s"}`;
    return spec.length
      ? {
          cls: "ovl",
          meta: mk,
          tip: `Overlaps KSSL${where} — confirmed on class-matched models in ${spec
            .map((o) => o.bandsSpec.map(geoBandShort).join(", "))
            .join(" / ")}`,
        }
      : {
          cls: "ovl-cat",
          meta: mk,
          tip: `Shares a category with KSSL${where}, but no class-matched model pair is on file`,
        };
  }

  /* Guards the parts of the overlap test that fail silently: a span parsed from
     the wrong end of a range, a band claimed that neither side reaches, a customer
     or component supplier counted as a rival, and matched pairs attributed to a
     band they are not in. */
  function selfCheck() {
    const fail = [];
    const ok = (c, m) => {
      if (!c) fail.push(m);
    };
    const S = (t) => geoKvaSpan(t);
    ok((S("SH-15 155mm howitzers") || []).indexOf("art") >= 0, "a 155mm row must read as artillery");
    ok(
      JSON.stringify(S("SH-15 155mm / VT-series tanks")) === JSON.stringify(["art", "pav"]),
      "artillery + armour in one row must yield both categories, in canonical order",
    );
    ok((S("Hermes 900 MALE UAV supplied") || []).indexOf("uav") >= 0, "a UAV row must read as uav");
    ok((S("Spike ATGM (multiple operators)") || []).indexOf("msl") >= 0, "an ATGM row must read as missiles");
    ok(S("training and simulation centre") === null, "no category keyword -> no span");
    ok(geoBandsOf(null).length === 0, "no span -> no categories");
    ok(
      JSON.stringify(geoBandsOf(["pav", "art"])) === JSON.stringify(["art", "pav"]),
      "geoBandsOf must return canonical category order",
    );
    const kc = koelCounter({ name: "CAESAR 155mm howitzer" });
    ok(kc && /ATAGS/.test(kc.p), "a 155mm rival product must be countered by the KSSL artillery line");
    ok(
      koelCounter({ name: "battlefield surveillance radar" }) === null,
      "a radar row has no like-for-like KSSL counter",
    );
    ok(GEO_NOTGEN.test("battlefield radar systems"), "radar rows must be excluded from the platform test");
    ok(
      GEO_NOTGEN.test("aerostructure components for a foreign prime"),
      "component supply into someone else's platform must be excluded",
    );
    let nSpec = 0;
    Object.keys(geoData).forEach((cid) =>
      Object.keys(geoData[cid]).forEach((ct) => {
        const ov = geoOverlap(cid, ct);
        if (!ov) return;
        if (ov.tier === "spec") nSpec++;
        ok(ov.bands.length > 0, `${ov.comp.name}/${ct}: an overlap with no shared band`);
        ok(geoIsRival(ov.comp.name, ov.comp.id), `${ov.comp.name} is flagged an overlap but is not a competitor`);
        const kb = geoBandsOf(ov.koelSpan);
        const rb = geoBandsOf(ov.rivalSpan);
        ov.bands.forEach((b) =>
          ok(
            kb.indexOf(b) >= 0 && rb.indexOf(b) >= 0,
            `${ov.comp.name}/${ct}: band ${b} is not reached by both sides`,
          ),
        );
        ok(
          ov.n === ov.per.reduce((a, p) => a + p.n, 0),
          `${ov.comp.name}/${ct}: pair total does not match its bands`,
        );
        ok(
          (ov.tier === "spec") === (ov.bandsSpec.length > 0),
          `${ov.comp.name}/${ct}: tier disagrees with its graded bands`,
        );
        ok(
          ov.bandsSpec.length + ov.bandsOnly.length === ov.bands.length,
          `${ov.comp.name}/${ct}: bands do not split cleanly into graded and range-only`,
        );
        ok(ov.graded <= ov.n, `${ov.comp.name}/${ct}: more graded pairs than pairs`);
        ok(
          ov.rival + ov.koel + ov.level === ov.graded,
          `${ov.comp.name}/${ct}: verdicts do not sum to graded`,
        );
        ov.per.forEach((p) => {
          const idx = geoPairIndex()[`${ov.comp.name}||${p.band}`] || [];
          ok(idx.length === p.n, `${ov.comp.name}/${p.band}: pair count not sourced from that band`);
          ok(
            idx.every((x) => x.compBy === ov.comp.name && x.catKey === p.band),
            `${ov.comp.name}/${p.band}: a pair belongs to another rival or band`,
          );
        });
      }),
    );
    /* Only assert this where the comparison could run at all. With no client footprint
       served, zero spec-confirmed overlaps is the correct answer, not a failure -- and
       reporting it as one trained the eye to ignore this check. */
    ok(
      clientFootprintKnown ? nSpec > 0 : nSpec === 0,
      clientFootprintKnown
        ? "no spec-confirmed overlap found at all"
        : "an overlap was computed with no client footprint on file",
    );
    // the dropdown dot is the only place the overlap is read at a glance, so it must
    // not drift from the model behind it
    geoComps.forEach((c) => {
      const got = geoPickOverlap(c, null).cls;
      const ovs = countriesForComp(c.id)
        .map((ct) => geoOverlap(c.id, ct))
        .filter(Boolean);
      const want = c.isBf
        ? "bf"
        : !clientFootprintKnown
          ? "ovl-unk"
          : ovs.some((o) => o.tier === "spec")
            ? "ovl"
            : ovs.length
              ? "ovl-cat"
              : "noovl";
      ok(got === want, `dropdown dot for ${c.name} is "${got}" but the model says "${want}"`);
    });
    ok(geoOverlap(CLIENT_KEY, "India") === null, "the client cannot overlap itself");
    if (fail.length) console.error("geo-overlap self-check FAILED:", fail);
    return fail;
  }

  return {
    clientFootprintKnown,
    countriesForComp,
    compsInCountry,
    productsFor,
    dirForAct,
    koelCounter,
    geoCatsOf,
    geoKvaSpan,
    geoBandsOf,
    geoBandShort,
    geoBandLabel,
    geoOffer,
    geoOverlap,
    geoRivalsIn,
    geoSpanText,
    geoThe,
    geoOvBadge,
    geoOvBadgeCountry,
    geoOvPanel,
    geoOwnPanel,
    geoPickOverlap,
    actLabel,
    selfCheck,
  };
}

/* The Footprint Lookup's competitor menu, and the count line above it, must count the
   same companies. The menu offered the whole roster -- 174 rows on the live dataset,
   97 of them badged "0 mkts", each opening an empty panel -- while the count line
   said 77. A competitor with no served market is not a footprint to look up. */
export function geoCoveredCompetitors(d) {
  const geoData = (d && d.geoData) || {};
  return ((d && d.geoComps) || []).filter((c) => c && geoData[c.id] && Object.keys(geoData[c.id]).length > 0);
}

export function geoLookupCompetitors(d, country, query) {
  const geoData = (d && d.geoData) || {};
  const q = String(query || "").trim().toLowerCase();
  return geoCoveredCompetitors(d).filter(
    (c) =>
      (!q || String(c.name || "").toLowerCase().includes(q)) &&
      (!country || !!geoData[c.id][country]),
  );
}
