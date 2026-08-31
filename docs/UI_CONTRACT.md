# UI_CONTRACT.md — the reference app, screen by screen

This is the behavioural contract of `reference.html` (137Parallax — KSSL Competitive
Intelligence). Every claim below was read out of the app's own JS (the minified React bundle
after the `window.__EMBEDDED_DATASET__` block), not guessed from the dataset. Where a minified
identifier is cited it is given once in parentheses so a reader with the prettified bundle can
find the exact function. The 35 dataset globals and their fields are the vocabulary; the field
unions here were verified against `reference_dataset.json` / `contract_shapes.json`.

Contents:

1. Boot & data flow
2. Navigation, routing, left-rail badges
3. Overview feed views (`overview`, `m-overview`, `t-overview`)
4. Signal detail panel (`details[id]`)
5. Positioning (`positioning`) + matchup dossier
6. The spec-edge algorithm (`computeSpecEdge` / `tr`) — used by four views
7. Gap Analysis (`gap-competitive`)
8. Partnerships (`partnerships`)
9. Geo Footprint (`geo`)
10. Patents (`patents-comp`)
11. Tenders (`tender`, `awarded-tenders`, `closed-tenders`)
12. Innovation Pipeline (`innovation`)
13. Chat (global dock + per-panel scoped chat)
14. The derived gap model (`gapModel`) — full formulas
15. Dataset wiring at load (`wireDataset`) — what the API must ship vs what the app derives
16. localStorage keys
17. Fields and globals the app never reads
18. Final table: global → views → fields → serving treatment

---

## 1. Boot & data flow

- Root: `createRoot(#root)` renders `App` = `DataProvider(x_)` → `AppStateProvider(Zy)` → `Shell(ww)`.
- **DataProvider** calls `api.getDataset()`. The fetch layer (`Dr`) short-circuits: if
  `window.__EMBEDDED_DATASET__` exists it is returned synchronously; otherwise it fetches
  `http://localhost:8001/api/v1/dataset` (30 s timeout, `Accept: application/json`). Our
  backend replaces this base URL; **the response must be the same 35-global object**.
  Validation on receipt: `if (!data || !data.matchups) throw "no dataset available"`.
- On success DataProvider memoizes, in order:
  1. `data = wireDataset(raw)` (`n_`, §15) — in-place enrichment;
  2. `gapModel = d_(data)` (§14);
  3. `geo = r_(data)` — geo-overlap model (§9);
  4. `partners = l_(data)` — partnership graph model (§8);
  5. `counts = __(data, gapModel)` — nav badges (§2);
  6. `viewMeta = w_(data)` — per-view title/subtitle strings (§2).
- Boot states: error screen ("Could not load the KSSL dataset — …", Retry button) and a
  loading screen. **Honest-state rule carried throughout**: a missing number renders as `—`,
  `null` edge renders "NO SPEC-LEVEL EDGE"/"INSUFFICIENT MEASURED DATA", never a fabricated 50.
- Self-checks run once after load (spec-edge unit checks `Yy`, partners `selfCheck`/`geomCheck`,
  geo `selfCheck`) — console-only, no UI.

## 2. Navigation, routing, left-rail badges

### 2.1 Pillars and views

Three pillars (`Hl = ["competitive","market","technology"]`, labels `Competitive / Market /
Technology` in the top bar). Left-rail views per pillar (`Mf`), in order, with rail index `ix`:

| pillar | view id | label | ix |
|---|---|---|---|
| competitive | `overview` | Overview | grid icon |
| competitive | `positioning` | Positioning | 01 |
| competitive | `gap-competitive` | Gap Analysis | 02 |
| competitive | `partnerships` | Partnerships | 03 |
| competitive | `geo` | Geo Footprint | 04 |
| competitive | `patents-comp` | Patents | 05 |
| market | `m-overview` | Overview | grid icon |
| market | `tender` | Tender Pipeline | 01 |
| market | `awarded-tenders` | Awarded | 02 |
| market | `closed-tenders` | Closed | 03 |
| technology | `t-overview` | Overview | grid icon |
| technology | `innovation` | Innovation Pipeline | 01 |

`overview`, `m-overview`, `t-overview` form the "overview set" (`Go(view)`); they share one
feed component and get the metric strip.

### 2.2 Hash routing

- On every route change the app writes `#p=<pillar>&v=<view>` (URL-encoded) via
  `history.replaceState`, and persists `{pillar,view}` to `localStorage["kssl_parallax_route"]`.
- On boot (`Fy`): parse the hash as `URLSearchParams` of the string after `#`; accept if `p` is
  one of the three pillars (the view value is **not** validated). Else fall back to the
  localStorage route; else default `{pillar:"competitive", view:"overview"}`.
- Switching pillar via the top bar selects that pillar's **first** view (`Mf[p][0].view`).
- Clicking the "137Parallax" wordmark returns to `competitive` (and thus `overview`).

### 2.3 Cross-view jumps (`jumpTo` / `takePending`)

`jumpTo(pillar, view, payload)` sets the route and stores `payload` as a pending intent. The
target view consumes it once via `takePending(view)`:

- `positioning` consumes `{matchupId}` → selects that matchup.
- `tender` consumes `{tenderTitle}` → finds the tender by exact title, then substring either
  way, selects it and scrolls the assessment into view.

Jump sources: metric-strip tiles (§3.4), gap-card tender chips in the matchup dossier (§5),
innovation `gapx` chips (§12), Gap Analysis rival rows (§7).

### 2.4 Left rail badges (`counts`, computed in `__`)

Every rail item shows `counts[view] ?? "—"`:

| view | count formula |
|---|---|
| `overview` | `competitiveCards.length` |
| `positioning` | number of **unique competitor product names**: `new Set(Object.values(matchups).map(m => m.comp.split("·")[0].trim()))`.size |
| `gap-competitive` | `gapModel.filter(g => g.direction==="behind" && g.pillar==="competitive").length` |
| `partnerships` | `Object.keys(competitors).length` minus the client (`client.id`, default "KSSL") |
| `geo` | number of unique countries across all of `geoData` (every inner key of every company) |
| `patents-comp` | `PATENTS._meta.total \|\| 0` |
| `m-overview` | `marketCards.length` |
| `tender` | open tenders: not awarded and not closed (bucket rules in §11.2) |
| `awarded-tenders` | tenders with `status.toLowerCase()==="awarded"` or `urlKind==="award"` |
| `closed-tenders` | not awarded, and (`isLive===false` or `dl<=0` or `deadline` contains "Closed") |
| `t-overview` | total innovations: `Σ innovations[domain].length` |
| `innovation` | same total |

### 2.5 Top bar

Brand wordmark; pillar pills; right side: client name box (`client.name`, fallback "Kalyani
Strategic Systems") and a static "Feed · Live" status box.

### 2.6 View header (`k_`) and header count text

`<h1>{viewMeta[view].title}</h1>` plus a count string. `viewMeta` (`w_`) supplies, verbatim:

| view | title | cnt (template — computed pieces in braces) |
|---|---|---|
| overview | Competitive Intelligence | `{competitiveCards.length} active signals · sorted by relevance` |
| positioning | Positioning | `KSSL products mapped to rival products by spec category` |
| partnerships | Partnerships | `{#competitors-client} competitors · {Σ partners across non-client competitors} alliances mapped` |
| geo | Geo Footprint | `{#geoData keys − client.short} competitors · {#unique countries} markets · competitor activity by country` |
| tender | Tender Pipeline | `Live opportunities matched to product portfolio` |
| awarded-tenders | Awarded Tenders | `Contracts awarded or settled` |
| closed-tenders | Closed Tenders | `Opportunities closed or expired` |
| innovation | Innovation Pipeline | `Technology developments tracked across KSSL product domains` |
| patents-comp | Patents | `Filings by rival and by technology field · sourced from patent records` |
| gap-competitive | Gap Analysis | `Where KSSL trails rivals, from the Positioning spec comparisons` |

For the overview set the count text is overridden live (§3.5). Non-overview views use
`viewMeta[view].cnt`; `m-overview`/`t-overview` fall back to `viewMeta.overview`.

## 3. Overview feed views (`overview`, `m-overview`, `t-overview`)

One component (`A_`) handles all three, keyed by `pillarKey` (`overview→competitive`,
`m-overview→market`, `t-overview→technology`, map `_w`). Its configuration comes from
`overviewConfig[pillarKey]` **after wiring** (§15) which injects `cards`:
competitive→`competitiveCards`, market→`marketCards`, technology→`techCards`.

`overviewConfig[pillar]` fields used: `title`, `cnt`, `metrics[]`, `groups[]`,
`dirWord{threat,watch,fav}`, `filters[]`, plus the injected `cards[]`.

### 3.1 Card anatomy (`E_`)

Reads per card: `id`, `dir` (`threat|watch|fav` — colours the signal dot, `data-dir`), `rank`
(re-stamped by sort, see 3.2), `title` (**rendered as HTML**), `meta` (string split on `" · "`
into chips, each chip rendered as HTML), `sowhat` (HTML), `ago` (right-side timestamp), the
right-side dir tag text = `overviewConfig[pillar].dirWord[card.dir]`. If `card.match[0].n`
exists a "KSSL Product:" highlight row renders — **no reference card carries `match`, so this
is dormant but part of the contract**. `card.sec` (array of `{lens, read}`) and `card.lens`
are used only for sorting/metrics, not rendered on the card. `card.company`, `card.tags`,
`card.url` are used by metrics/tile filters only.

Click → open the signal detail panel for `details[card.id]` (§4); the card gets `sel`, and the
first card passing the current filters gets a `fresh` highlight.

### 3.2 Sequence control (`v_`)

Select with four modes (`m_`): `priority` "Priority (threats first)" (default), `recency`
"Most recent", `depth` "Analytical depth", `category` "By domain".

- priority: sort by dir order `threat(0) < watch(1) < fav(2)`, tiebreak `sec.length` desc.
- recency: parse `ago` (`dh`): "Mon YYYY" → year*12+month; bare year → year*12; contains
  "ago" → 999999 (most recent); else 0. Sort desc.
- depth: `sec.length` desc, tiebreak dir order.
- category: `String(meta).localeCompare` asc.

After sorting, `rank` is re-stamped `"01"…` in display order. Grouping: in `priority` mode the
config's `groups[]` (`{n, h, s}`) slice the sorted list sequentially (first group takes `n`
cards, etc., `n:99` = rest); other modes show one group headed by `p_[mode]` ("Most Recent
First" / "Richest Analysis First" / "Grouped by Domain") with subtitle `f_[mode]`. The first
group header is pinned above the filter bar.

### 3.3 Direction filters (`O_`)

Buttons from `overviewConfig[pillar].filters[]` (`{f, l, c}`; `c` is a CSS colour var for the
swatch). Clicking sets the dir filter (`card.dir === f`, `"all"` passes everything) and clears
any active metric tile. Empty result renders "— no signals match this filter —"; otherwise the
feed ends with "— end of active signals · {total} total —".

### 3.4 Metric strip (`L_`, values via `g_`) — overview set only

Tiles come from `overviewConfig[pillar].metrics[]`: `{l, v, unit?, sub, act, dot?, delta?,
src?}`. `v` animates from 0 (28 frames); values containing "," format `en-IN`. `sub` renders
with an optional source chip from `src`. For the **competitive** pillar only, `g_` recomputes
`v` live for tiles whose label matches exactly:

- "Competitive threats" = cards with `dir==="threat"`;
- "Watch signals" = `dir==="watch"`;
- "Companies tracked" = unique `card.company` (truthy);
- "Analytical lenses" = unique lens strings across `card.lens` and every `card.sec[].lens`;
- "All signals" = card count.

Market/technology metric values are shipped as-is in the dataset.

Tile click (`onPick` in `ww`): label containing "audited rival skus"/"rival skus" →
`jumpTo(competitive, positioning)`; containing "competitor brands"/"competitor brand"/"tracked
competitors" → `jumpTo(competitive, partnerships)`; `act==="all"` → clear tile+dir filter;
otherwise activate the tile `act` as a feed filter with predicate `Af(act)`:

- `threat`: `dir==="threat"` or tags contain "threat";
- `fav`/`watch`: `dir` fav/watch or tags contain opening/fav/watch;
- `atstake`, `gap`: effectively pass-all (the predicate ends `|| !0`);
- `open`, `deadline`, `patents`, everything else: pass-all.

(`card.tags` is a space-separated string.) Activating a tile also auto-opens the detail panel
of the first matching card.

### 3.5 Header count override (overview set)

With a tile active: `"{shown} of {total} signals · {y_[tile]}"` where `y_` maps
act→phrase (`atstake`→"contested bids, by value", `threat`→"threats to active bids",
`fav`→"openings to press", `deadline`→"by submission deadline", `open`→"open tenders",
`fit`→"strong KSSL fit", `geo`→"markets in play", `positioning`→"rating-matched rivals",
`gap`→"capability gaps", `patents`→"patent activity", `emission`→"emission compliance",
`all`→"sorted by relevance"). With a dir filter: `"{shown} of {total} signals ·
{filter.l}"`. Otherwise the config's `cnt` string.

## 4. Signal detail panel (`M_`, right column of the overview feed)

Data: `details[cardId]` — a dict keyed by card id (union of competitive/market/tech cards; the
reference set covers 50 of the 44 cards' ids plus extras; a card with no detail entry is
simply not selectable). Fields read:

- `rank` (eyebrow, e.g. "Technology Signal · 01"), `title` (HTML) + a dir pill labelled by
  `j_` = `{threat:"Threat", watch:"Watch", fav:"Favourable"}` from `dir`;
- `facts`: array of `[key, value]` pairs → "At a glance" rows (value is HTML);
- `kind`: when `"tender"` the "What happened"/"Why it matters" sections are **suppressed** and
  a "Matched KSSL product" section renders from `match[]` (`{n, fit, pct, lines[[up|down,
  html]]}` — same shape as tender matches);
- `what` (HTML) → "What happened"; `why` (HTML) → "Why it matters to {client.short}";
- `lens`: array of `[LENS NAME, html]` → "Full-spectrum read" paragraphs;
- sources: chips from `srcs[]` (`{label,url}`) or fallback single chip from `url`; optional
  `provenance` line (reference data has neither `srcs` nor `provenance` on details — only
  `url`);
- `suggest`: string array → suggested questions for the embedded "Ask Parallax" box (`T_`),
  answered locally by the scoped-chat answerer (§13.2) with `type:"signal"`.

`details.actions` and `details.pursue` exist in the dataset but are **never read**.

Selecting a signal also sets the chat scope (`setScope("signal", {type:"signal", data},
{pillar:"Competitive", view:"Overview", selection: detail.title})`).

## 5. Positioning (`positioning`)

Two-pane view: left product list (`I_`), right matchup dossier (`U_`) or an empty-state
placeholder. Selection persists in `localStorage["kssl_pos_selected"]` (a matchup id).

### 5.1 Left list

Reads `matchups` (dict id→matchup), `POS_CATS` (ordered `[key,label]` pairs), `CAT_KEY`
(label→key). Structure: for each `POS_CATS` category (in dataset order), group matchups whose
`CAT_KEY[m.cat]` equals the key; inside a category, group by **anchor** = `m.anchor || m.bf`
(the KSSL product), anchors ordered by rival count desc; within an anchor, matchups with
`global:true` sort first. Category header shows label + total matchup count and is
collapsible. Rows show `m.comp` ("vs KSSL {anchor}").

Controls, all narrowing each other's option sets:

- text search over `"{comp} {compBy} {cat} {country} {anchor}"` plus the literal
  `" global prime benchmark"` for `global` matchups;
- select "All companies" → `m.compBy`;
- select "All categories" → `CAT_KEY[m.cat]`, labelled from `POS_CATS`;
- select "All KSSL products" → anchor;
- select "All countries" → `m.country`.

Click row → select matchup; sets chat scope `type:"matchup"`, selection `"{comp} vs {bf}"`.

### 5.2 Matchup dossier (`U_`) — reads `matchups[id]` fields

`cat`, `comp`, `compBy`, `bf`, `bfBy`, `global`, `reason` (HTML), `verdictH`, `verdict`
(HTML), `advComp[]`, `advBf[]` (HTML strings), `specs[]`, `det[]` (pairs), `srcs[]`, `edge`
(recomputed at wire time, §15), `anchor`, `country`, `catKey` (used by geo model). Fields
`gen` and `ks_thin` are never read.

Layout, top to bottom:

1. **Header**: eyebrow `cat` + badge "Verified specs · analysed" (`global`) or "Verified ·
   analysed"; the VS block (competitor product/by vs `client.short` product `bf`/`bfBy`);
   `reason` HTML ("why these two are matched").
2. **Positioning verdict** band: heading `verdictH || "Positioning verdict"`, body `verdict`.
3. **Gap card** (`F_`, "mug"): see §5.5. Its `[data-tender]` chips call
   `jumpTo("market","tender",{tenderTitle})`.
4. **Product strip** (`pp2`): the two sides' blurbs from the spec row with
   `l === "Product (sourced)"` (`cv` = competitor blurb, `kv` = KSSL blurb).
5. **Tabs** (`W_`): `adv` "Advantages" (default) | `specs` "Spec Comparison" | `comp`
   "Competitor Detail".
   - **Advantages**: two columns; left "Competitor advantages" = `advComp[]`, right
     "{client.short} advantages" = `advBf[]`, each item HTML with a ▲ marker.
   - **Spec Comparison** (`B_`): if `edge != null` → edge gauge (word from `Ha`, marker at
     `edge`%, scale "Competitor stronger / Parity / KSSL stronger") + an explanation block
     (`Qy`) listing every decided dimension with ▲/▼ and its % gap, level-dimension count, the
     shrink note, and the fixed sentence excluding calibre/length/weight axes. Then legend and
     two sections (`D_`): "Quantitative specifications" — bar rows (`z_`) for specs with
     numeric `cn` & `kn` and `hi !== null`, excluding labels `Product (sourced)`,
     `Subcategory`, `End user`; "Qualitative assessment" — chip rows (`R_`) for **all** specs.
     If `edge == null` → "NO SPEC-LEVEL EDGE" banner with the honest explanation (KSSL
     undisclosed vs not-like-for-like) and competitor-only chip rows with "KSSL — undisclosed"
     where `kv` is absent.
   - **Competitor Detail**: `det[]` rendered as key/value rows, source chips from `srcs[]`,
     plus a "Generate detailed intelligence report" button → CEO briefing (`Z_`, §5.6).
6. **Scoped chat** (`nr`, scopeKey `matchup`, placeholder "Ask about this matchup…").

### 5.3 Spec row shape (`specs[]` items)

`l` label, `cv`/`kv` display strings (competitor/KSSL), `cn`/`kn` numeric values or null,
`u` unit, `hi` true = higher-is-better, false = lower-is-better, null = not comparable,
`p`/`cp`/`kp` provenance codes — anything other than `"s"` (sourced) renders an orange
"analytical estimate" dot. (`csrc`/`ksrc` exist in data, never read.)

### 5.4 Spec bar rendering rules (`z_`)

Bar widths proportional to value/max (min 4%). A side "wins" only if `hi !== null`, values
differ, and the relative gap `(max−min)/max ≥ 5%`; strength classes: `decisive ≥35%`,
`clear ≥15%`, `marginal ≥5%`, else parity. `hi === false` adds a "lower is better" tag;
equal/undecided adds "parity".

### 5.5 Gap card (`F_`)

If `edge == null`: "No measured gap on this matchup — specs undisclosed…". Else compute
`a = (50−edge)/50`; `behind` if `a > 0.02` (gap % = round(a·100)), `ahead` if `a < −0.02`,
else parity. Class for behind: `crit ≥70`, `high ≥40`, else `med`. It then looks up the
gapModel row with `pillar==="competitive" && benchmark_entity===comp && (koel_entity===bf ||
koel_entity==="KSSL · "+anchor)` to show: severity number, `₹ exposure` (`Of` formatting:
≥1000 → "₹X.Xk cr", else "₹N cr", 0 → "—"), "tender closes {N}d" when horizon ≤30, and the
row's `correlates`: market correlates become clickable 📄 tender chips (label = correlate
label minus the "KSSL · " prefix, → tender view), technology correlates a compounding note.
Footer: `Derived · matchup.edge={edge} · descriptive`.

### 5.6 CEO positioning briefing (`Z_`)

Generated client-side after a 600 ms fake delay. Sections: bottom line (verdict with the
`<b>[Analysis]</b>` prefix stripped), per-side spec leads (from `specs` by comparing
`cn`/`kn` with `hi`), advantages both ways, up to 4 live tenders with `t.cat === m.cat`
(title, country, value, first match `n`/`pct`, `lean`), provenance line from the `det` pair
labelled `Provenance` or `Source`, print button (`window.print`). Null-edge variant states
"KSSL spec undisclosed — no measured edge."

## 6. The spec-edge algorithm (`tr` — `computeSpecEdge`)

Recomputed at load for every matchup (overwrites any shipped `edge`; §15). Also feeds the gap
model, Gap Analysis, and geo overlap verdicts. For each spec row:

1. **Exclude axis dimensions**: label contains (case-insensitive) any of `Calibre`, `MTOW`,
   `Length`, `Barrel` (`Wy`) — these are what the pair was matched on.
2. Require `cn`, `kn`, `hi` all non-null.
3. **Plausibility windows** (`Uy`): `Crew` [1,15], `Crew / pax` [1,20], `Speed` [0.1,30]; a
   value outside drops the row (guards unit mismatches).
4. Signed relative difference `w = (kn−cn)/mean(cn,kn)`, sign flipped when `hi===false`.
5. **Deadband** (`qy`): zero the vote if `|w|` < 15% for labels starting `Effective range`;
   10% for `Rate of fire`, `Endurance`, `Range`, `Speed`; 3% otherwise (`Vy`).
6. Clamp each vote to ±0.4 (`ea`).

Result: no usable dimensions → `edge = null`; all votes zero → `edge = 50`. Else
`edge = round(50 + 50 · mean(nonzero votes)/0.4 · d/(d+1))` where `d` = decided count
(evidence shrink), clamped to [2,98]. Returns `{edge, n, decided, dims[{l, a, raw}]}`.

Verdict bands (`Ha`): `edge ≥ 58` → ahead ("KSSL AHEAD"), `≥ 42` → "NEAR PARITY", else
"KSSL BEHIND"; `null` → "INSUFFICIENT MEASURED DATA". A self-test (`Yy`) asserts symmetry,
deadbands, axis exclusion, etc. at boot.

## 7. Gap Analysis (`gap-competitive`, `nw`)

Left: category list; right: per-category rival table + accordions. Persisted:
`localStorage["kssl_gap_cat"]`.

### 7.1 Category list (`q_`)

Categories = distinct `m.cat` over matchups with `edge != null`, each with matchup count `n`,
rival count, behind/ahead counts and total `balance` from the per-category model (§7.2).
Sorted worst-first: behind-share desc, then behind desc, then n desc. Rows show
`{cat}`, "{rivals} rivals · {n} comparisons", and a signed net balance chip coloured
behind/level/ahead (behind if `behind ≥ rivals/2`). Text search filters by category name.

### 7.2 Per-category rival model (`Kf`)

For the selected category, group matchups by rival company `compBy`. Per rival, per dimension
(from `tr(m).dims`): count `win` (rival leads, vote<0), `loss` (KSSL leads), `level`, with
magnitudes. A rival **owns** a dimension when: comparable count ≥ 3 (`Bf`; relaxed to 1 when
the rival has <3 matchups) AND coverage ≥ 40% of its matchups (`Ff`), AND decided ≥ 3 of
them exist (`G_`, else "contested"), AND win-share ≥ 65% (`$a`) with a net margin ≥ 2 (`fh`);
symmetrically for KSSL ("koel"); else contested/nodata. Dimension keys are looked up
per-category first (`"{cat}|{dim}"`) in the app-constant advisory table `Vl` (bins, direction,
notes — hardcoded in the app, not the dataset).

Rival verdict: nodata if all dims nodata; "behind" (KSSL behind) if rival owns more dims than
KSSL; "ahead" if fewer; ties → "Traded"/"No clear edge"; a ±1 ownership edge contradicted by
the per-matchup win record is downgraded to "Traded". Also computed: `balance` (net dims),
`worst` (matchup with highest net rival dimension lead, tiebreak lowest edge — its **id** is
the click target), `thin` (<5 matchups, `Zf`), `masked` (verdict not-behind but some matchup
edge <42), `severity` (Σ of per-dim bin scores `Ts`), `dims` (owned dims sorted by severity).
Rivals sort: behind < contested < ahead < nodata, then net ownership, severity, win record, n.

### 7.3 Rendering (`ew`, `X_`, `J_`)

- **Hero**: "{behind}/{rivals} rivals hold an edge", the leading rival and its widest owned
  dimension with median gap (`qs` formats % via the `Vl` scale), deepest single loss
  ("{edge}/100 against {rival}"), and the ownership definition sentence.
- **Rival table**: rank, rival, verdict chip (⚠ when masked), a ±5-dim SVG balance bar
  (`Q_`, faded when thin), owned-vs, worst edge (bucket-coloured), win/level/loss record bar,
  N (⚠ when thin), biggest owned dimension. **Row click** (`data-mu` = worst matchup id) →
  `jumpTo("competitive","positioning",{matchupId})`.
- **"What they beat KSSL on"** (`X_`): accordion per dimension (from `Hf`: dims sorted by
  rival-owner count then median gap): severity word (from bins: 4→Critical, 3→High,
  2→Moderate), median gap, owning rivals with per-rival "leads in x/y matchups", record,
  KSSL-owns count, coverage, "Why it matters" prose from the app-constant `Ca` table + the
  `Vl` measurement note.
- **"What the edge buys them"** (`J_`): interpretation rows per owned dimension from `Ca`
  (kind chip, one-liner, why, "Matters most to" segment) with a fixed closing "Read:" block on
  step-function deployability, crew-as-automation, layer-bound range, and Indian procurement
  (L1 after qualification).
- Footer methodology note (thresholds restated) — all app-constant text.

Subtitle (`tw`): "{rivals} rivals · {Σn} head-to-head comparisons · {max dims} measured spec
dimensions".

## 8. Partnerships (`partnerships`, `iw`)

Three columns: competitor list / alliance graph / intelligence drawer. Persisted:
`localStorage["kssl_part_state"]` = `{cid, tie, mode, ovOpen}`.

### 8.1 Competitor list

From `compOrder` (dataset order) minus `client.id`. Each row reads `competitors[cid]`:
`name`, `dir` (dot colour), `hq` (compressed label: contains "USA"→USA, "Italy"→Italy,
"China"→China, else India; hidden when "Not supplied"), `sector`, `partners.length` ("N
ties"), and "◆ N shared" when shared partners exist. Search matches name+sector+"shared";
an HQ select filters exact `hq` (lowercased). Click → select competitor, scope
`type:"partner"` with `partner:null`.

### 8.2 Alliance graph (SVG, model `l_`)

Nodes: the competitor centre (`competitors[cid].center`, synthesized `{id, label:name}` if
missing) plus one node per **distinct** partner company (dedup by `cid || id`; when several
rows share a company the "best" row wins: `[CORE]` in `insight` ranks over `[ADJACENT]`, then
`sig`). Max 16 nodes on a ring (370,228 centre, radii 200/158, alternating when >7). Edge
per node; **red** when the partner is shared with the client (`koel`/`shared`, wired in §15).
Node click → open that tie in the drawer; centre click → back to the competitor report.
Legend: grey "Partner relationship", red "Shared partner — overlapping with {client.short}".

Below the graph, the **overlap strip** (`overlapHtml`): "◆ Shared partners · X of Y" with
per-shared-partner chips (label, "{client} + N rivals", shared role — from `partner.koel.rel`
vs `ptype`, "also {other rivals}") — chips open the tie. A toggle reveals "what it costs"
definition blocks chosen by relationship class (`ah` maps rel/ptype →
channel/supplier/service/tech; `oh` holds the fixed prose). Zero-partner and zero-shared
variants have their own honest sentences.

### 8.3 Drawer — competitor report (mode `syn`, `compReportHtml`)

If `COMPSYN[cid]` exists (it has `thesis`, `vulns[{title, from[], intel}]`, `strat{thesis,
pattern, sowhat}`; `preds`/`moves` are never read): thesis block; stat trio (ties count,
`[CORE]` count "On {client} lines", partners with `kind==="Foreign OEM"` count "Foreign-IP");
numbered **structural weaknesses** — clicking one highlights ("traces") the contributing
graph nodes via `TRACEIDS[cid][vulnIndex]` (explicit partner-id lists) or, absent that, fuzzy
label matching on `vulns[].from`; strat block; a "Field-level read" button (mode `field`).
Else fallback: `competitors[cid].updates` (HTML), the full relationship list (each row:
`label`, `country`, `REL_LABEL[rel] || ptype`, `note`, `deal` unless "n/d", `date`; `[CORE]`
rows highlighted; click → tie), and `assess` (HTML) as "Assessment for {client.short}".
Source chips from `competitors[cid].srcs` or fallback `site`.

Drawer heading (`drawerHead`): "Intelligence" when COMPSYN has vulns, else "Relationships".

### 8.4 Drawer — tie detail (`tieHtml`)

For `partner = competitors[cid].partners.find(id)`: back link; hero (label, rel pill
`REL_LABEL[rel] || ptype`, country, CORE/ADJACENT badge from `insight` markers); sibling rows
(other partner rows sharing the same company `cid`); facts grid (Scope=`ptype`,
Programme=`note`, Deal/scale=`deal` unless "n/d", Timeline=`date`); if shared, "◆ Shared with
{client}" block naming the client's own relationship (`partner.koel.rel`, optional role) and
the other rivals on the same shelf, plus the `oh` cost bullets; "What this tie reveals" =
`insight` with the `[CORE]`/`[ADJACENT]` markers stripped; "Competitive read" = `mean` with
any `<b>Opening:</b>…` span removed; sources.

### 8.5 Drawer — field-level read (mode `field`, `fieldReadHtml`)

From `FIELDSYN`: `patterns[]` rows (`field||t`, `pattern||e` with optional "(n of total)",
`implication||s`), "Bottom line" = `bottomLine||bottom`; then **all tracked sources** from
`sourceRegistry[]` grouped by `company` (chips from `label`/`url`).

Scoped chat: scopeKey `partner`, placeholder "Ask about this competitor / partner…".

## 9. Geo Footprint (`geo`, `lw`; overlap model `r_`)

Layout: filter bar with two searchable dropdowns (Competitor, Country), a full-bleed Leaflet
map, and a detail overlay. Persisted: `localStorage["kssl_geo_state"]` = `{comp, country,
showDetail, pair, prodIndex, back}`.

### 9.1 Data

`geoData` = `{companyId: {country: rows[]}}`; row fields: `name`, `c` (activity code:
`lp` local production, `pt` partner/licence, `ex` export, `sv` service/MRO, `bf` client —
forced onto all client rows at wire time), `qty`, `val`, `since`, `stage`, `note`, `src`
(`"syn"` = analytical estimate, else sourced), `srcnote`, optional `srcs[]`. `geoComps` =
`[{id, name, dir, hq, isBf}]` (display names + client flag). `geoCountries` = the country list
the **map** plots. `actLabel` maps activity codes to display labels. `CAT_META` (per category
key: `label`, `kw[]` keywords, `desc`) powers keyword categorisation of rows; `counterRules[]`
(`{band, label, product, note}`) names the client's counter-product per category band.

### 9.2 Dropdowns

- Competitor: from `geoComps` (client included, listed as its name); when a country is chosen
  first, restricted to companies present there. Each option shows an overlap dot
  (`geoPickOverlap`): `bf` client, `ovl` spec-confirmed overlap, `ovl-cat` category-only,
  `noovl` none, plus "N mkts" and a tooltip.
- Country: from `geoCountries`; when a competitor is chosen first, restricted to its
  countries. Dot: `fav` when the client has rows there, `threat` when absent but rivals
  present ("⚠"), else none; meta = rival count.

### 9.3 Map (`ow`)

Leaflet, CARTO dark tiles, world-bounded, zoom 2.6. One circle marker per `geoCountries`
entry at hardcoded coordinates (`Fr` table; unknown names fall back to a deterministic
hash position). Colour: client present (has `geoData[client.short][country]`) → green
`#3fa86a`; rivals present → red `#f0593c`; else amber `#e0a020`. Selected country gets a
white ring and radius 11. Tooltip: country, "KSSL Present · Direct / Export / Assembly" or
"KSSL Absent · Contested Market ⚠", then up to 5 companies with **hardcoded** Exports/Imports
lines (`aw` table keyed by company name; generic fallback), and "Click point to open market
product details ↗". Click → select the country and auto-select the first company present.

### 9.4 Detail overlay — three list modes + product detail

Mode from selections: competitor only → **countries** list (each row: country, product count,
first row's activity label, overlap badge + "meets KSSL in {bands}", "since {first row
since}"); country only → **competitors** list (per company: overlap badge, product count,
activity, first product name); both → **products** list: the overlap panel (§9.5) followed by
each product row (activity dot `c`, name + Sourced badge or "Illustrative" dot for
`src==="syn"`, activity label · `qty`, KSSL counter line, `stage` · `val`). Rows are
`wt`-delegated clicks: country rows drill to products, competitor rows likewise, product rows
open the **product detail**: fact rows Activity/Quantity/Value/Stage/Since, a Source row
(`srcnote` if not a URL, else "analytical estimate"/"open-source", plus `srcs` chips), the
KSSL counter card (`counterRules` product + note, or the honest "No direct like-for-like
product — a portfolio gap…"), and a "What this means" assessment fixed per activity code.
Product selection also sets chat scope `type:"geo"` (comp name, country, counter). ScopeKey:
`geo`.

Header (kind/name/sub) varies by mode and includes an activity-mix chip row in products mode,
"Supplies N markets · meets KSSL in X of them" in countries mode, and "{n} competitors active
· KSSL present/absent ⚠ · {x} contest KSSL on rating-matched models, {y} on category only"
in competitors mode.

### 9.5 The overlap model (`geoOverlap`) — how "contested" is decided

For rival company `k` in country `A`:

1. Categorise each side's rows by `CAT_META` keyword hits on
   `"{name} {qty} {val} {note}"` (rows matching the exclusion regex
   `radar|electronic warfare|c4i|avionics|aerostructure|fuselage|components for|subsystems for`
   are ignored — component supply is not a platform).
2. Shared bands = intersection of the two category spans; none → no overlap.
3. Per shared band, pull the Positioning matchups keyed `"{compBy}||{catKey}"` for that rival
   name; each matchup with an edge votes rival/koel/level via `Ha(edge)`.
4. `tier: "spec"` when at least one band has graded pairs, else `"cat"`. Adds flags `local`
   (any `lp` row), `licence` (`pt`), `exportOnly`.

Rendered as: the rival panel (`geoOvPanel`) with the four-test strip (same country / same
product / same category / same specs), a per-band table (matched pairs, datasheet outcome
"rival leads x of y"/"KSSL leads…"/"level", KSSL counter from `counterRules`), and a "What
this means for KSSL" narrative (local-production / licence / export variants, weakest band,
open-ground reasoning). The client-side panel (`geoOwnPanel`) does the same per country
across all rivals, including the "no overlapping rival on file" honest state.

## 10. Patents (`patents-comp`, `hw`)

Persisted: `localStorage["kssl_pat_state"]` = `{lens, cid, area, catFilter}`.

### 10.1 Wiring (`i_`, at load — §15)

`PATENTS` ships `techAreas[]`, `byArea{area: rawRecord[]}`, `byAssignee{assignee:
rawRecord[]}`, `_meta{total, providers[], note, status, lastSync}`. Raw records:
`no`/`id`, `title`, `assignee`, `status` (regex → granted/pending/filed), `filed`, `granted`,
`country`/`jurisdiction`, `ipc[]`, `abstract`/`claims`, `area`/`techArea`, `threat`
(high/medium/low), `relev`, `srcs[]`, `url`, `p`. The wiring **derives**:

- `PATENTS.byCompetitor{cid: {stats:null, records[]}}` — each `byAssignee` key is tokenised
  (lowercased words >2 chars minus a corporate-stopword list) and assigned to the competitor
  (`compOrder`/`competitors[].name`) with the most token overlap; assignees matching the
  client name are skipped.
- `PATENTS.byTechnology{areaName: {...}}` from `byArea`: `stats{totalFilings,
  activeAssignees, koel_position}` (position from the `techAreaMeta` entry whose `area`
  matches), `crowding` (≥25 records → "crowded", ≥8 → "emerging", else "open"), `summary`
  (`techAreaMeta.why || .desc`), `leaders[]` per assignee (`filings`, `granted`, `pending`,
  `countries[]`, `latest` year, max `threat`, `isClient` via client-name regex, `trend` from
  techAreaMeta) sorted client-first then granted/threat/latest/name, `whitespace: []`
  (always empty in this build), `koel{filings, position}` (filings counted by
  `/kalyani|kssl|bharat\s*forge/i` on assignee; position = `techAreaMeta.reason` or "No KSSL
  filings recorded in this field yet."), `records[]`.

### 10.2 View

Lens toggle "By rival" / "By technology field" (note text switches accordingly).

**By rival**: left list = **all** of `compOrder` (searchable by name) with per-competitor
record counts from `byCompetitor`; right canvas: header "{name} · patent portfolio", an
optional category filter select (distinct `techArea` values among the records, with counts;
filters the rendered cards client-side via `data-cat` and rewrites the "N filings" line), the
stats trio Granted/Filed/Pending (from `byCompetitor.stats` or a live count), the records as
patent cards, and the data-source note (`ql`: providers + "{_meta.total} filings currently
indexed." or the honest "No filings indexed yet…"). Empty/awaiting/error states have fixed
copy (`Di`).

**By technology field**: left list = `PATENTS.techAreas` (fallback `techCats[].name`),
searchable, with record counts; right: field crowding chip (open/emerging/crowded/locked with
colours), Filings/Assignees stats, `summary`, the KSSL bar ("KSSL holds N filings…"/"KSSL
holds no filings in this field. N rivals have staked it, M with a granted patent already
enforceable."), the holders list (name, KSSL tag, filings, countries, latest, granted chip,
published chip, threat chip), whitespace section (dormant — empty array), "KSSL position",
then the field's records as cards, and the data-source note.

**Patent card** (`Wf` on the normalised record `vh`): title, `relev` badge (CORE/ADJACENT
style classes), status badge, meta (assignee bolded in field lens, id, jurisdiction,
"Filed X · Granted Y"/"Pending"), IPC chips, abstract, link "View patent ↗" (or "Search for
this filing ↗" when the URL is the generated Google-Patents search fallback
`https://patents.google.com/?q={title}`), extra source chips.

Record fetch is a fake-async local lookup (`mh`) returning
`{status: "ok"|"empty", results, total, source:"dataset"}` — the shape a live patent backend
would occupy.

## 11. Tenders (`tender`, `awarded-tenders`, `closed-tenders` — one component `gw`, prop `mode`)

Persisted: `localStorage["kssl_tender_state"]` = `{productType, country, cat, sel}`.

### 11.1 Deadline normalisation at load (`Xy`/`Jy`, §15)

Every tender is rewritten before any view sees it: `dl` (days left), `deadline` (display
string), `timing`, `statusClass` (`urgent ≤7` / `soon ≤14` / `normal` / `settled`), `isLive`.
Resolution order: explicit awarded (status `awarded`/`settled` or deadline starting
"Awarded") → settled; `stage` string → treated as open, `dl=365`, deadline text = stage;
else find a date from `closingDate`/`dueDate`/`closing_date`, or a `req` row whose key
contains closing date/due date/deadline, or a `d MMM yyyy` inside `deadline`; else interpret
numeric `dl` as days from `createdAt` (fallback epoch **2026-08-11**). A resolved date in the
past → "Closed / Expired". Otherwise "N days left" with status `closing ≤3` / `open`.

### 11.2 Tab bucketing (identical to the nav counts)

awarded = `status==="awarded"` (case-insensitive) or `urlKind==="award"`;
closed = not awarded and (`isLive===false` or `dl<=0` or `deadline` contains "Closed");
open = the rest. `mode` selects the bucket. Sort: `dl` ascending ("sorted by deadline").

### 11.3 Filters (three dropdowns, option counts always computed over **all** tenders)

- **Product Type**: two synthetic buckets by regex `/uav|drone|naval|marine|missile|air
  defence/i` over `"{cat} {title}"` → "Air, Naval & Missiles" vs "Land Systems".
- **Country**: options = `tpAllCountries`, with a search box; count per option; sorted count
  desc then A–Z.
- **Category**: options = `tpAllCats`, same counting/sorting.

Summary line: "**N** open|awarded|closed tender(s) (filtered) · sorted by deadline".

### 11.4 Tender card

Reads `title`, `deadline` (chip class from `statusClass`, else derived from `dl`:
settled/urgent/soon/normal — `fw`), `issuer · country · cat · value · qty`, and a fit bar
from `matches[0]`: if `pct` contains "%", bucket `pw` (≥75 high / ≥50 mid / low) and show the
pct; else use `fit` word and show strong/partial/weak; bar width fixed 85/55/25%. Label
"{client.short} fit". Click → assessment panel + chat scope `type:"tender"`, selection
"{title} ({country})".

### 11.5 Assessment panel (right)

- Header: "Tender Assessment", `title`, `issuer · country · value · (timing || deadline)`.
- "What the tender requires": `reqNote` (HTML) then `req[]` `[key, value]` rows (HTML
  values). If any req row matches `/indigen|content|offset/i` a fixed DAP-2020 gloss
  paragraph renders.
- "Matched {client.short} products": each `matches[]` entry — `n`, "{pct} fit" chip classed
  by `fit`, and `lines[]` of `["up"|"down", html]` with ▲/▼ markers.
- "Bid assessment" panel classed by `lean` (`go|maybe|no`), body `leanTxt` (HTML); source
  chips from `srcs[]` or fallback `url`.
- **Pursue CTA**: resolves the URL as `t.url || t.srcs[0].url` (`Hc`); button label by
  `urlKind` (`award` → "Read the award announcement", `portal` → "Open the tender portal",
  URL present → "Open the tender notice", none → "Pursue this tender" and the click alerts
  "No source URL on record"). Note line: "opens this tender on {host}" / "no per-tender page
  on record — opens the listing on {host}" / "this contract is settled — opens the
  announcement on {host}" / "no source URL on this record".
- Scoped chat, scopeKey `tender`.

`tenders.stage` also displays through `timing`; `qty` appears only on the card meta row.

## 12. Innovation Pipeline (`innovation`, `yw`) — also feeds `t-overview` counts

Persisted: `localStorage["kssl_innov_state"]` = `{cat, sel}`.

- **Domain rail**: `techCats[]` (`{id, name}`) — wiring appends any `innovations` key missing
  from `techCats`, naming it from `techAreaMeta[id].area` or a prettified id (§15).
- **List** (`innovations[cat][]`): each item shows `t`, maturity pill `mat` mapped by
  `Qo`/`C_` (`lab` "Lab / research", `dev` "In development", `prod` "In production",
  `fielded` "Fielded / in service"), `body` (bold tags stripped), `driver · horizon ·
  {client.short} {gap}` pill (`gap` ∈ behind/parity/ahead).
- **Detail** (selection by index): verdict band "{client} is BEHIND / AT PARITY / AHEAD";
  "Why this matters to {client}" = `impact` with a leading `<b>[Analysis]…</b>` stripped;
  "Why {client} is {gap}" = `compNote`; "What's new" = `whatsNew`; "Background · what it is"
  = `body`; Status rows: Maturity, "Driven by" = `driver`, Horizon = `horizon`, "{client}
  position", Sources = chips from `srcs[]`/`url` (labelled by `sources`) or the plain
  `sources` text. Then the **gapx strip** (`h_`): finds the gapModel technology row whose
  `koel_entity` is `"KSSL · {t}"` (or endsWith `t`) and shows "₹ exposure {Of(value)} — live
  tenders in {category} this gap touches" plus "Reinforced across pillars" chips from
  `correlates` — market chips are clickable (`data-tender` → `jumpTo("market","tender")`).
- **CEO briefing** (`H_`, fake 600 ms delay): executive summary (`body`), what's new,
  strategic implication (`impact` stripped), competitive landscape (`compNote` + up to 6
  competitor products from matchups whose `cat` starts with the domain name word), up to 4
  live tenders with `cat === domain name`, sources, print button.
- Scoped chat, scopeKey `tech` (answer type `"tech"`).

`innovations[].action` is never read.

## 13. Chat

### 13.1 Global dock (`N_`, bottom-right "Ask Parallax")

Collapsible window. Context line from `chatCtx` (`pillar`, `view` title, `selection` — set by
every panel selection). Suggestion chips: with a selection → three fixed context questions;
otherwise `chatSuggest.overview` (first 3) or fixed fallbacks. Answers are computed locally
(`P_`) after a 420–800 ms typing delay, from a projection (`Rf`) of the wired dataset:
matchups (id/category/competitor "comp (compBy)"/koelProduct=`bf`/edge/verdict), geoRows
(country/company/product name/activity), tenders (id/title/country/cat/value/lean/first
match), techItems (t/dom/gap/mat), plus `competitors` verbatim (uses `products[]`, `sector`,
`threatNote`). Intent routing: country presence, category rivals, tender fit (lean go/maybe),
competitor profiles, cross-pillar mapping, recommendations (returns matchup verdicts —
descriptive-only disclaimer otherwise), technology landscape; fixed help text as fallback.
Footer: "Grounded in {client.name} platform intelligence · sourced + analytical data".

### 13.2 Scoped panel chats (`nr` + `T_`; answerer `zf`)

Each detail panel embeds an input scoped to the current selection (`scoped[scopeKey]`, epoch
resets clear the log). Types and the fields their canned answers read:

- `matchup`: specs (`l/cv/kv/cn/kn/hi/u`), edge + `Ha` phrase, `verdict`, `advBf`/`advComp`,
  `comp`/`compBy`/`bf`/`cat`.
- `tender`: `req`, `matches` (n/pct), `lean`/`leanTxt`, `value`, `issuer`, `country`,
  `timing`/`deadline`, `title`.
- `tech`: `impact`, `gap`, `compNote`, `whatsNew`, `body`, `mat`, `horizon`, `sources`, `t`.
- `partner`: partner `label/country/ptype/note/deal/date/mean/insight`; competitor
  `name/partners/updates/assess/hq`.
- `geo`: product row `name/qty/val/stage/c/note`, `actLabel`, counter product/note.
- `signal`: `why`, `facts`, `what`, `title`.

## 14. The derived gap model (`gapModel`, built by `d_`)

An array of gap rows; **never shipped — always derived**. Consumers: nav badge
`gap-competitive`, matchup gap card (§5.5), innovation gapx strip (§12), tender view
(receives it but only via the shared components). Row core fields: `id` ("g1"…), `pillar`,
`gap_type`, `koel_entity`, `benchmark_entity`, `magnitude` (0–1), `direction`
(`behind|ahead|at_parity`), `category`, `basis` (e.g. `matchup.edge=45`), `exposure_value`
(₹ cr), `exposure_count`, `exposure_horizon` (min days-left), `correlates[]`, `source`
(`derived:{basis}`), `confidence:1`, `status:"published"`, `verified_by:"engine"`.

Exposure per category (`_`): over tenders with `cat===category`: `tracked` sums `qo(value)`
for all; `value`/`count`/`horizon` only for non-awarded, live ones. `qo` parses "₹N" directly
(crore) and converts `US$ | A$ | $ | € | £ | AED | MYR` with hardcoded rates (8.3, 5.5, 8.3,
9, 10.5, 2.26, 1.9; B/bn/billion ×1000).

Four families:

1. **competitive / spec** — one row per matchup with non-null edge. `a=(50−edge)/50`;
   `behind` if `a>0.02` (magnitude `a`), `ahead` if `a<−0.02`, else parity/0.
   `koel_entity = bf || "KSSL · "+anchor`, `benchmark_entity = comp`. Extras: `lags`/`leads`
   (per-dimension % from `tr(m).dims`), `edge`, `muId`, `rivalCo`.
2. **market / demand_fit** — one row per tender having matches; best match pct → magnitude
   `(100−pct)/100`, direction behind unless ≤0.02. Extras: `tenderTitle`, `tenderValue`,
   `deadline`, `fitPct`, `fitWord`, `lean`. Exposure = that tender's own value.
3. **technology / frontier** — one row per innovation. `gap` behind→0.75, ahead→0.4 (marked
   ahead), else parity/0. Category = the POS_CATS label mapped from the domain id
   (`armoured→pav`, `naval→naval`, `missiles→msl`, `materials→pc`, `artillery→art`,
   `smallarms→sa`, `ammunition→ammo`, `uav→uav`). Extras: `techName`, `maturity`, `horizon`,
   `driver`, `domain`, `whatsNew`, `impact`, `compNote`, `gapWord`.
4. **competitive / ecosystem** — parses `CORE OVERLAP (cat1, cat2…)` out of every competitor
   partner's `mean`+`insight`; per category: tie count and distinct rivals; magnitude =
   ties/max-ties; always `behind`. Extras: `contestTies`, `contestComps`.

Post-pass on `behind` rows: `severity = magnitude · (0.35 + 0.65·exposure_value/maxExposure)`;
`severity_pct = round(·100)`; `urgency = 0` if horizon null or >180 else `1 − horizon/180`;
`rank_score = severity + 0.08·urgency`. Non-behind rows zero these and get `advantage_pct`.
`correlates`: within the same category, other-pillar behind rows — product-token matches
first (`onProduct:true`; tokens from entity names minus a stopword+generic-product list),
then non-market rows by magnitude, max 3, as `{id, pillar, label:benchmark_entity, mag, sev,
onProduct}`.

## 15. Dataset wiring at load (`wireDataset` / `n_`) — API obligations

The app performs these mutations after fetch; the serving layer must ship the **inputs**,
never the outputs:

1. `overviewConfig[p].cards` ← `competitiveCards` / `marketCards` / `techCards`.
2. `techCats` extended with any `innovations` key not present (name from
   `techAreaMeta[id].area` or prettified id).
3. **Every** `matchups[id].edge` overwritten with `tr(matchup).edge` — the shipped edge is
   advisory only.
4. All rows under `geoData[client.short]` get `c="bf"` forced.
5. `PATENTS.byCompetitor` / `PATENTS.byTechnology` derived (§10.1).
6. `tenders` normalised by `Jy` (§11.1) — `dl`, `deadline`, `timing`, `statusClass`,
   `isLive` are recomputed.
7. Shared-partner wiring: for each non-client competitor partner, match against
   `KSSL_PARTNERS` by `cid`/`id` equality or by label containment (both >5 chars, either
   direction); on match (or pre-set `shared`/`koel`) set `partner.shared=true`,
   `partner.cid`, `partner.koel` = the matching KSSL_PARTNERS row (or `{rel, role}`
   fallback). This is what draws red edges and shared chips.
8. Chat knowledge: `geoRows` (flattened geoData with company display names from `geoComps`)
   and `techItems` (flattened innovations with `dom`).
9. `signalTheme`/`themeSignals` initialised empty (vestigial).

**Hard rule restated from PLAN.md**: presence is not shape. Every global must arrive with a
usable shape (lists as lists, dicts as dicts) — `wireDataset` and the models index into them
without defensive checks in several places (`overviewConfig.competitive`, `techCats.slice`,
`innovations` keys, `compOrder.map`, `client`).

## 16. localStorage keys (all UI-state, never data)

| key | shape | owner |
|---|---|---|
| `kssl_parallax_route` | `{pillar, view}` | router |
| `kssl_pos_selected` | matchup id string | Positioning |
| `kssl_gap_cat` | category name | Gap Analysis |
| `kssl_part_state` | `{cid, tie, mode, ovOpen}` | Partnerships |
| `kssl_geo_state` | `{comp, country, showDetail, pair, prodIndex, back}` | Geo |
| `kssl_pat_state` | `{lens, cid, area, catFilter}` | Patents |
| `kssl_tender_state` | `{productType, country, cat, sel}` | Tenders |
| `kssl_innov_state` | `{cat, sel}` | Innovation |

## 17. Fields and globals the app never reads (ship for contract fidelity, don't build UI on them)

- **Globals never referenced by the app code**: `overviewMetrics` (empty lists in the
  reference data), `CAT_ALIASES`, `companySources`, `KSSL_CATS`.
- **Fields never read**: `matchups[].gen`, `matchups[].ks_thin`, spec `csrc`/`ksrc`,
  `details[].actions`, `details[].pursue`, `innovations[].action`, `COMPSYN[].preds`,
  `COMPSYN[].moves`, `PATENTS._meta.note/status/lastSync` (only `total` and `providers` are
  read), card `match` (read but absent from all reference cards).
- **App-constant content that is NOT in the dataset** (lives in code; replicate in the
  frontend, not the DB): the gap-dimension measurement table `Vl` (bins/direction/notes per
  dimension, category-scoped keys like `"Artillery|Weight"`), the gap interpretation table
  `Ca` (kind/one/why/seg prose), the partnership cost-definition tables `ah`/`oh`, the geo
  map coordinates `Fr` and the exports/imports tooltip table `aw`, currency conversion rates
  `u_`, maturity label maps, all fixed methodology/honest-state copy.

## 18. Final table — global → reading views → fields used → serving treatment

Treatment legend: **table** = real serving table (pipeline writes rows); **table+JSONB** =
real table whose array-valued fields are JSONB columns; **ui_config** = one row in
`serving.ui_config(key, value jsonb)` (interface vocabulary, pipeline never writes).

| global | read by | fields the UI reads | serving treatment |
|---|---|---|---|
| `client` | topbar, every view (branding, "KSSL" substitutions), chat | `id`, `name`, `short`; (`sector`,`website`,`currency`,`magnitude`,`locale` unread) | ui_config |
| `overviewConfig` | overview set (feed, metrics, filters, groups, header cnt) | per pillar: `title`, `cnt`, `metrics[{l,v,unit,sub,act,dot,delta,src}]`, `groups[{n,h,s}]`, `dirWord`, `filters[{f,l,c}]` | ui_config |
| `competitiveCards` | overview feed, competitive metric recompute, nav badge, details join | `id,dir,rank,title,meta,sowhat,ago,company,lens,sec[{lens,read}],tags,url`, optional `match` | table (cards, pillar='competitive'); `sec`/`match` JSONB |
| `marketCards` | m-overview feed, nav badge | `id,dir,rank,title,meta,sowhat,ago,tags` | table (cards, pillar='market') |
| `techCards` | t-overview feed | same as competitiveCards | table (cards, pillar='technology') |
| `details` | signal detail panel, scoped signal chat | key=card id; `rank,dir,title,facts[[k,v]],what,why,lens[[k,v]],match[],suggest[],url,kind`; optional `srcs`,`provenance` | table (details); `facts`/`lens`/`match`/`suggest`/`srcs` JSONB |
| `matchups` | positioning (list+dossier), gap analysis, gap model, geo overlap, chat, nav badge | `cat,catKey,anchor,bf,bfBy,comp,compBy,country,global,dir,reason,verdict,verdictH,advBf[],advComp[],specs[{l,cv,cn,kv,kn,u,hi,p,cp,kp}],det[[k,v]],srcs[]`; `edge` recomputed | table (matchups); `specs`/`advBf`/`advComp`/`det`/`srcs` JSONB |
| `POS_CATS` | positioning grouping order, gap-model domain naming | ordered `[key,label]` | ui_config |
| `CAT_KEY` | positioning category filter | label→key | ui_config |
| `tenders` | tender/awarded/closed views, gap model, CEO briefings, chat, nav badges | `id,title,issuer,country,cat,value,qty,deadline,dl,status,stage,urlKind,url,srcs[],reqNote,req[[k,v]],matches[{n,fit,pct,lines[[dir,html]]}],lean,leanTxt`; derived: `timing,statusClass,isLive` | table (tenders); `req`/`matches`/`srcs` JSONB |
| `tpAllCountries` | tender country dropdown | list | ui_config |
| `tpAllCats` | tender category dropdown | list | ui_config |
| `competitors` | partnerships (list/graph/drawer), patents mapping, chat, nav badge, shared-partner wiring, gap ecosystem | key=cid; `name,dir,sector,hq,partners[{id,cid,label,kind,rel,sig,ptype,note,date,country,deal,insight,mean}],updates,assess,threatNote,products[],site,srcs[],center` | table (competitors) + table (partners rows, FK cid); prose/array fields JSONB |
| `compOrder` | partnerships + patents list order, patents mapping | ordered cid list | ui_config |
| `KSSL_PARTNERS` | shared-partner wiring, overlap strip, tie "shared with" block | `id,cid?,label,kind,rel,sig,ptype,note,date,country,deal,insight,mean` | table (partners with owner='client') or its own table; row-per-partner |
| `REL_LABEL` | partnership rel pills | rel→label | ui_config |
| `COMPSYN` | partnerships drawer (thesis, vulns, strat) | per cid: `thesis`, `vulns[{title,from[],intel}]`, `strat{thesis,pattern,sowhat}` | ui_config (interface-adjacent analysis; or JSONB column on competitors) |
| `TRACEIDS` | vuln→graph-node tracing | cid → per-vuln partner-id lists | ui_config |
| `FIELDSYN` | partnerships field-level read | `patterns[{field/t,pattern/e,implication/s,n,total}]`, `bottomLine/bottom` | ui_config |
| `sourceRegistry` | partnerships field read (source list) | `company,label,url,kind` | table (sources) |
| `geoComps` | geo dropdown/list/map, wiring names | `id,name,dir,hq,isBf` | table (geo_companies) |
| `geoData` | geo view, geo overlap model, map colours, chat geoRows, nav badge | company→country→rows `{name,c,qty,val,since,stage,note,src,srcnote,srcs?}` | table (geo_rows: company, country + row fields) |
| `geoCountries` | map dots, country dropdown | ordered list | ui_config |
| `actLabel` | geo activity labels | code→label (`lp,pt,ex,sv,bf`) | ui_config |
| `CAT_META` | geo categorisation keywords | key→`{label,kw[],desc}` | ui_config |
| `counterRules` | geo KSSL counter cards + overlap tables | `[{band,label,product,note}]` | ui_config |
| `PATENTS` | patents view, nav badge | `techAreas[]`, `byArea{area:records}`, `byAssignee{assignee:records}`, `_meta{total,providers}`; records `no,title,assignee,status,filed,granted,country,ipc[],abstract,area,threat,relev,url,srcs?` | table (patents: one row per record with area+assignee columns; rebuild byArea/byAssignee in the API) + `_meta` from ui_config or aggregate |
| `techAreaMeta` | patents field stats/summary, techCats naming | id→`{area,desc,maturity,position,trend,reason,why?}` | ui_config |
| `innovations` | innovation view, t-overview counts, gap model, chat | domain→`[{t,mat,gap,driver,horizon,body,whatsNew,impact,compNote,sources,url?,srcs?}]` | table (innovations, domain column); `srcs` JSONB |
| `techCats` | innovation rail, patents fallback, gap-model naming | `[{id,name}]` | ui_config |
| `chatSuggest` | global chat suggestion chips | keyed string lists (only `overview` read) | ui_config |
| `overviewMetrics` | — (never read) | — | ui_config (fidelity only) |
| `CAT_ALIASES` | — (never read) | — | ui_config (fidelity only) |
| `companySources` | — (never read) | — | ui_config (fidelity only) |
| `KSSL_CATS` | — (never read) | — | ui_config (fidelity only) |

Derived-only (never stored, always computed by the app): `gapModel`, `counts`, `viewMeta`,
`PATENTS.byCompetitor/byTechnology`, tender `dl/deadline/timing/statusClass/isLive`,
`matchups[].edge`, `geoRows`, `techItems`, `overviewConfig[p].cards`, partner
`shared/koel/cid` back-fill. The API may ship the raw values it has for these fields; the app
will overwrite them.
