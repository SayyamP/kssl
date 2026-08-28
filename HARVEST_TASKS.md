# Harvest run — live task list

`python pipeline/harvest/status.py` prints the live numbers. Last written 2026-08-27.

## Stages

- [x] **S0 · free the machine** — stopped 8 idle containers (rts-c3 ×2, sfl-searxng,
      vantra ×3, parallax-monitor, mallory-l2-monitor). Kept kssl-db, kssl-backend,
      camofox (C3), corpus tunnel, ingest. All reversible with `docker start`.
- [x] **S1 · target list** — `harvest/targets.py`. Eleven needs mapped to the pillar/tab
      that renders them, priority-ordered so Profile fills first. Seeds the home page
      only; the worker expands from the site's own link graph.
- [x] **S2 · harvester** — `harvest/worker.py` + `harvest/fetch.py`. C1 httpx → C3
      CamoFox → C4 host solver, escalating only on evidence. Sharded by COMPANY so one
      host is only ever touched by one worker.
- [x] **S3 · Fable 5 advisor** — audited before running wide. Found C4 dead on arrival
      (see below) plus 7 other blocking faults. All blocking items fixed.
- [x] **S4 · launch + control agents** — 8 instances live. A site-discovery agent took
      the roster from 35/58 to **56/58** verified sites; a QC agent found 33 soft-404s.
- [x] **S5 · profile extractors** — `harvest/extract_profile.py`, one gate per field.
- [x] **S6 · verify locally** — precision measured per field, sample-audited
- [x] **S7 · write to VPS** — promote verified rows into the VPS serving Postgres

## What the advisor and QC agents caught

| finding | impact | state |
|---|---|---|
| **C4 posted to `/fetch`; the server serves `/solve`** and returns `{ok,html,error}`, not `{text,status,url}` | the whole Cloudflare/Incapsula tier had a **0% success rate** and every such site was filed "failed" | fixed — BAE now returns 11,766 chars, IAI 39,290 |
| C1 dropped the body on an HTTPError | a 403 interactive challenge could never be detected, so every URL of every such site paid a guaranteed-loss browser render first | fixed |
| `_blocked()` matched bare phrases | a page *about* "bot detection" was condemned at every tier and retried forever | fixed — 2xx now needs structural markup |
| C4 called on any C3 error | a wedged CamoFox turned the whole fleet into a one-at-a-time queue | fixed — C3 breaker + evidence gate |
| Spec reader's page gate was English-only | would have silently zeroed every non-English catalogue (4th recurrence of that fault) | fixed — structural fallback on numeric values |
| An empty run overwrote a good catalogue file | one 403 day erases a successful harvest | fixed — refuses empty-over-full |
| **33 soft-404s stored as real pages** — one maker answers every unknown path with a 200 error page; another redirects guesses to its homepage | 7 of that company's 9 "covered" needs were fabricated | purged; the worker now rejects them on the way in |
| 47 byte-identical duplicate pages | fragments/trailing slashes fetched repeatedly | purged |
| L&T's seed URL was a hard 404 | company invisible | seed corrected |
| **5 regexes contained a literal 0x08** where `\b` should be | they compiled and never matched — fields went quietly empty | fixed; a control-char assert now guards every pattern |

## Where the numbers stand

```
tasks     1,229    755 done ·  79 pending · 387 failed (mostly honest 404s on guessed paths)
pages       590    45 companies, 5.46M characters
facts     1,308    product_spec 1,250 · facilities 38 · leadership 12 · sales 8
                   (leadership 206->38->12 and facilities 105->38 as each gate landed)
sites        56 of 58   (was 35; Thales WAF-blocked, Mahindra Defence has no live domain)
```

## S6 — measured precision, by hand, row by row

| field | rows | audit | verdict |
|---|---|---|---|
| leadership | 12 | every row read against its own quote | **12/12 correct** |
| facilities | 38 | 22-row sample read against its quote | real sites: Bhandara, Ishapore, Korwa, Hazira, HMNB Devonport, Billancourt, Lalru, Angul, Chakan, Pithampur |
| sales | 8 | every row | each a real revenue or order-book figure with its sentence |
| product_spec | 1,250 | not promoted here | belongs to Positioning and its like-for-like gate |

Leadership took three gates to get there, and the audit is what found each one. The first
pass scored **16 of 38 — 42%**, and the failures were one clean pattern:

```
Micael Johansson, President & CEO     name then role  -> a person
President, Electric Boat              role then name  -> a DIVISION
Chairman, Jindal Steel                role then name  -> a COMPANY
Vice President-International Sales    role then name  -> a DEPARTMENT
```

Twenty of the twenty-two false positives were the second shape and no correct row was.
English writes a person before their title and a scope after it; that ordering was the
whole signal. Two more rules removed officers of OTHER organisations ("Mr Vladimir Putin,
President of Russia" on a BrahMos page; an Airbus buyer on a Tata page).

Facilities had its own distinct failure — `X Facility` was reading the process word in
front of the noun ("Welding Facility", "Testing Facility", "Power Plant"). Fixed by
requiring a REGION after the facility noun, which is what a real site names and a process
step never does.

## S7 — on the VPS

```
serving.competitors   +leadership +facilities +sales   (jsonb, each row carries url + verbatim line)
promoted              27 companies written
visible on screen     12  (serving_live filters to origin='pipeline')
```

`serving_live.competitors` had to be recreated — a view does not gain columns when its
table does. The VPS backend needed a real image rebuild for the same reason a previous
deploy did: `build: ./backend` in compose disagrees with the Dockerfile, which expects the
repo root as context.

Profile now renders Leadership / Facilities / Sales as sourced rows with a ❝ that reveals
the sentence on hover, and "Not collected" is computed PER COMPANY — printing it under a
heading filled for the rival next door would read as a finding rather than a gap.

## Honest caveats

* **Coverage is thin, and thin is the honest answer.** 12 companies show harvested rows
  of the 30 the dashboard renders. Most maker sites simply do not publish a board list or
  a plant list on a page a crawler can read; several put it in an annual-report PDF, which
  the brochure reader could be pointed at next.
* **`sales` is the thinnest and the most trustworthy** — 8 values, each a real revenue or
  order-book figure with its sentence.
* **1,250 product_spec rows are harvested and NOT promoted.** They belong to Positioning,
  which has its own like-for-like gate; putting unpaired specs on a profile page would
  repeat the fault that gate exists to stop.
* Nothing was promoted that had not been read against its own quote first.
* Nothing here has been written to the VPS. Local first, promotion after S6.

---

## Positioning — both sides, or not published

`pipeline/both_sides.py`. A comparison needs two numbers; Positioning was showing rows
where only one side had one, and the missing half rendered as a dash that reads like a
deficiency rather than an absence of evidence.

**The measurement was wrong before the data was.** `verify_positioning.py` counted a
matchup as sourced only when a KSSL value came from the export catalogue, and reported
**9 of 204**. But the matchups carry per-FIELD provenance on both sides — `srcK`/`tierK`
and `srcC`/`tierC` — which the row-level count never looked at. A comparison is made
field by field, so that is where it is now measured.

```
before   204 matchups · sourcing measured per ROW      ·   9 "both sides"
after     48 matchups ·  63 spec fields, per FIELD     ·  63 both sides = 100%
```

The rule, per spec row: the rival must state a value **and** show a source; the KSSL side
takes the export catalogue's figure where the catalogue publishes that field, otherwise
the archived value only if it carries a source. Anything else is dropped — not blanked,
dropped, because a row with one number should not occupy a line that looks like a
comparison. 247 half-sourced fields went; 156 matchups that had nothing both sides could
show went with them. `edge` is recomputed over what survived.

### What was tried and did not work, stated plainly

* **Nammo's catalogue is real and useless here.** 17 genuine products — all ammunition and
  shoulder-fired weapons. KSSL makes guns, vehicles and *empty* shell bodies. Pairing them
  would be the same category error the like-for-like gate exists to stop, with better
  sourcing behind it. Not used.
* **Rival spec sheets are not on guessable URLs.** Direct fetches of BAE/M777,
  Elbit/ATMOS, Hanwha/K9, KNDS/CAESAR returned 404s, landing pages, or nothing. The
  harvest reached each maker's home and category pages, which *name* products and specify
  none of them. Getting these needs per-product search and verification — a real
  sub-project, not a crawl parameter.
* Two catalogue-reader faults were fixed on the way: a two-column PROSE handbook was being
  read as a spec table (748 "specs" that were sentence fragments), and product titles were
  being taken from the largest text on the page, which on a catalogue is the page number
  (44 Nammo sheets named "116", "125", "136").

### A repo-wide check now exists for the fault that kept recurring

`harvest/no_control_chars.py`. A regex written through a shell heredoc had its `\b`
collapse into a literal 0x08 byte **six times** while building this — the pattern compiles
and silently never matches, so the field goes quietly empty and reads as a thin source.
The scan found dead regexes in `glance_facts.py`, `enrich_serving.py`,
`extract_profile.py` and `fetch_brochures.py`. Tree is clean: 52 files, zero.


---

## 2026-08-28 — the signal feed, and rival data sheets

### Where the numbers stand

```
corpus staged      4,000 documents   (was 876; the pull now streams, see below)
extracted            155 documents   in the engine store
                     650 documents   in Postgres `extracted`
signal cards          14 pipeline    unchanged since 2026-08-24
positioning           48 matchups · 64 spec fields · 100% sourced BOTH sides · live on VPS
rival data sheets      2 of 12 products specified (21 values, from the makers' own PDFs)
```

### The corpus pull lost every document it read

A 4,000-document pull ran for eighteen minutes and staged **zero**. Two faults, and the
connection drop was the smaller one:

* **The write was deferred to the end of the loop.** Every kept document sat in a list
  until the run finished, so one dropped connection discarded all of them.
* **One connection was held across thousands of round-trips** with no retry. Through an
  SSH tunnel that is a guaranteed loss eventually.

Documents are now written the moment they are kept, and `BodyReader` reconnects through
drops. The tunnel was never the problem — it probed clean at 0.8 s throughout.

### Rival data sheets: every product was reachable, each lost at a different layer

`harvest/discover_specs.py`. Five faults, one per layer:

| symptom | cause |
|---|---|
| BAE `sitemap=0` | `/sitemap.xml` is an Incapsula interstitial; the solver was disabled for that one fetch |
| Hanwha, Denel, Yugoimport `sitemap=0` | they answer 200 with their **homepage**. No sitemap exists — *presence is not shape* |
| Elbit `1613 urls -> 0 candidates` | its page is `/howitzer-systems/`**`atmos`**; we demanded `atmos-2000`. Makers drop the model year |
| KNDS `5 candidates -> 0 specs` | top-scored page was a **dashboard trainer**; the gun's numbers sit in a PDF whose URL is in escaped React props, not an `href` |
| Elbit datasheet `-> 0 specs` | the page-wide column vote needs a 12 pt gap; Elbit sets its table at ~9 pt, so the vote landed on the vertical sidebar lettering and cut `Firing Rate | 6-7` in half |

**A gate was throwing away the only page worth having.** Each page had to name the
product — but a data sheet names its product on the COVER. ATMOS appears on pages 1, 2
and 6, never on page 5, which is the specifications. The front of the document now
vouches for the document.

**The first 11 CAESAR specs looked fine and four were false.** Flowed two-column text
gave `Road speed: More than = 3.7m` (the HEIGHT value labelled as road speed) and
`Height: 3.1m - Min: 4,5km` (two unrelated fields in one row). Reading PDFs by column
geometry instead gives 15 correctly-paired rows.

### Positioning: the ceiling is KSSL's own catalogue, not the rivals

`pair_rivals.py`. KSSL's export catalogue publishes **four** spec fields for artillery —
elevation, traverse, intense rate, sustained rate. Every Artillery matchup names
*"MArG 155"*, which is a family of three guns, so a family name may claim only what all
three agree on: traverse and sustained rate. Intersect that with what the rivals state
and the answer is one row. **More rival data will not widen this; more KSSL data would.**

Two false comparisons stopped on the way, both of which would have shipped:

* `Intense Rate: 10 rounds in 2.5 min` against `Rate of fire: 6 rounds per minute` reads
  as 10-beats-6. KSSL's figure is **4 per minute**. Shown, not scored.
* `Traverse: 25° to Right & Left` against `55º` reads as double. KSSL's is **±25 = 50°**,
  about a tenth apart. Doubling it would be a guess about what Elbit meant. Shown, not
  scored.

### The heredoc `` trap fired for the SEVENTH time

In `pair_rivals.py`, in a patch written to fix something else. The per-module control-char
assert caught it before it could compile-and-never-match. `harvest/no_control_chars.py`
scans 56 files clean.

### Extraction moved back to this machine, at the operator's instruction

VPS2's Ollama runner wedged — 580% CPU for 20+ minutes, load 9.06, every other container
on the box under 2%, and a 20-token prompt returning HTTP 000 after 220 s. A client
timeout killed mid-inference, which wedges the runner. It does not self-recover.

Layer A is now running on the workstation 5090. The wedged VPS2 process is still holding
~6 cores and should be cleared.
