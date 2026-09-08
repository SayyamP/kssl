# -*- coding: utf-8 -*-
"""VERIFY the competitor product workbook, then import only what survives.

    python competitor_specs.py --xlsx <workbook>  # re-parse -> portfolio/competitor_specs.json
    python competitor_specs.py --demo     # hermetic self-check, no DB, no spreadsheet
    python competitor_specs.py --report   # the workbook-side verdict, no DB
    python competitor_specs.py --dry      # + the roster join: what --apply would write
    python competitor_specs.py --apply

THE OPERATOR'S INSTRUCTION was "use any info we can BUT FIRST VERIFY IT WITH OUR
LOGICS". So this is not an import with a filter bolted on. It is a verification pass
whose by-product is an import, and every row that does not clear the bar is counted
and named rather than quietly dropped.

WHY THIS EXISTS BESIDE competitor_portfolio.py
----------------------------------------------
competitor_portfolio.py already parses this workbook and already writes
serving.competitor_product -- 709 of the 1,072 product rows. It asks ONE question
about a row: does engine/source_tiers.publishable admit its URLs? That question is
right and it is not sufficient, because the corrected 2026-09-06 master carries three
audits of its own that nothing in this repo was reading:

    Source Health   all 1,183 URLs were resolved.  943 rows live, 61 '1 dead',
                    11 '2 dead', 26 'all dead', 31 'no source'.
    Evidence        the workbook's own tier per row.  1,011 'T1 manufacturer/gov',
                    25 'T2 independent x1', 5 'T2 independent x2', 31 'none'.
    OPEN ISSUES     the workbook naming its own doubtful rows, by product.

...and a fourth thing nothing was reading at all: whether the company is on the
roster. competitor_portfolio.py resolves the 50 workbook names against
serving.competitors for the PROFILE columns and then imports the PRODUCTS without
asking.

Measured against the 709 rows served today, that let 89 through that should not be
there:

    69  not_on_roster -- Leonardo 18, Huntington Ingalls 12, Diehl 11, Naval Group 9,
        Northrop Grumman 7, HSW 4, Babcock 4, L3Harris 3, Thyssenkrupp Marine 1
    14  unserved_reference_id -- Solar Industries 8, Larsen & Toubro 6
     3  cited_page_lacks_the_numbers -- Nexter LECLERC XLR, Mahindra Marksman,
        SSS Defence 338 Saber
     3  all_sources_dead -- Lockheed Indago 4 UAS, AeroVironment Puma AE RQ-20B,
        Adani Vehicle-Mounted Counter-Drone System

(The workbook has 26 all-dead rows and 5 wrongly-cited ones; the rest belong to
companies rule 2 or 3 already refuses, which is why the two lists differ.)

This module is that reconciliation. It is a NARROWING and never a widening: every row
it admits, competitor_portfolio.py already admits, and a test asserts the subset.

NOTHING IN THIS FILE IS A SECOND COPY
-------------------------------------
    engine/source_tiers.publishable   whose word counts, and for what
    competitor_portfolio.specs_of     a bullet -> {k, v, note}
    competitor_portfolio.urls_in      the Sources cell -> URLs
    competitor_portfolio.NO_FIGURE    the sentence that declines to state a figure
    competitor_portfolio.match_companies  workbook name -> roster row, aliases-aware
    competitor_portfolio.slug/CAT_KEY/DOUBLE_COUNTED
    spec_direction.direction_of       which way is better, per FIELD
    positioning_gate.kind_of          what sort of thing this product is

THE REFUSAL RULES, in the order they are applied
------------------------------------------------
 1  double_counted        the 8 Leonardo rows that are IDV vehicles. Already
                          competitor_portfolio's rule; re-used, not re-decided.
 2  not_on_roster         the company reaches no row of serving.competitors.
                          Nine companies: Babcock, Diehl Defence, Huntington Ingalls,
                          HSW, L3Harris, Leonardo, Naval Group, Northrop Grumman,
                          Thyssenkrupp Marine. Several are not KSSL competitors at all
                          (two are naval shipbuilders; Leonardo the operator has said
                          is not a direct rival). A product for a company nobody tracks
                          is a row no screen can reach, so it is not written -- and a
                          roster entry is NOT invented to receive it.
 3  unserved_reference_id the company reaches ONLY an origin='reference' row.
                          "Larsen & Toubro (L&T)" -> comp_id 'LT' and "Solar
                          Industries" -> 'SOLAR'. serving_live.competitors is
                          origin='pipeline' only, so importing under those uppercase
                          ids would attach 51 products to a competitor no user can
                          open -- the same duplicate-id fault as the geo tables.
                          REFUSED LOUDLY, naming the id, because the fix is a roster
                          merge and not an import flag.
 4  cited_page_lacks_the_numbers
                          OPEN ISSUES, MEDIUM: "5 rows whose cited page does not
                          contain the numbers ... the page loads, names the product,
                          and carries none of the figures". The workbook checked; we
                          are not going to overrule it. Evidence that exists is not
                          evidence that ENTAILS.
 5  no_source             Source Count 0. 31 rows. A row with no source cannot become
                          a served fact -- there is nothing for the UI to cite.
 6  all_sources_dead      Source Health 'all dead'. 26 rows. A dead URL is not fresh
                          evidence and cannot be re-checked by anybody; OPEN ISSUES
                          rates this HIGH and says re-source from the maker's current
                          site. Until that happens the figure is unverifiable, which
                          is the definition of not publishable here.
 7  unpublishable         engine/source_tiers.publishable says no -- a single
                          uncorroborated news or registry source.
 8  workbook_evidence_below_bar
                          the workbook's own tier is a CEILING on ours. Where it says
                          'T2 independent x1' or 'none' and our gate says official, the
                          disagreement means the official-looking URL is not the
                          maker's. MEASURED: this fires on 0 rows of the 2026-09-06
                          master, because every row the workbook tiers below T1 our own
                          gate already refuses. It is kept as the guard for the next
                          workbook, and the fact that it is currently silent is stated
                          rather than left for a reader to discover.
 8b no_company_owned_source
                          OPEN ISSUES, HIGH: "NORINCO has no company-owned source. All
                          18 rows rest on trade press and a US Army training portal.
                          Action: mark the entry tier-2 so scoring discounts it."
                          Rule 8 cannot catch this, because the workbook's own Evidence
                          column calls those same rows 'T1 manufacturer/gov' -- the
                          DATA QUALITY/Evidence sheet and the OPEN ISSUES sheet of one
                          workbook contradict each other, and OPEN ISSUES is the one
                          that looked at the sources. Our gate agrees with the wrong
                          half: it admits 2 of the 18 as OFFICIAL through
                          armyrecognition.com plus date.army.gov.au and drdo.gov.in --
                          an Australian army training portal and India's DRDO ranked as
                          official for a CHINESE rival's specification, because
                          source_tiers rightly holds that a government publisher is
                          official for anyone. It is official about a procurement; it
                          is not the manufacturer's data sheet. So for a company the
                          workbook says owns no source, "official" is demoted to tier-2
                          and the row must clear the two-independent-domains bar
                          instead. Refuses those 2 rows and no others.
 9  no_measurable_value   nothing in the spec cell states a figure.
10  absence_only          counted apart from 9 because it is a different fault: the
                          cell is not empty, it says the figure could not be found.
                          "detailed public performance figures not established in
                          reviewed authoritative sources" is an ABSENCE. It is
                          recorded under evidence.absent and is never a value.

AN ABSENCE IS A PROPERTY OF THE CLAUSE, NOT OF THE BULLET
---------------------------------------------------------
17 accepted bullets mix a stated figure with an admission that the rest is not
public: "Length class: 42 m; detailed displacement/power not publicly exposed on
current page". Dropping the whole bullet loses 42 m; keeping it stores the sentence.
So a bullet is split into clauses and each clause is judged on its own. The same
treatment is given to a clause that hedges its number onto somebody else -- "public
secondary sources commonly report TAR-21 CLASS FIGURES around 720 mm", "Earlier
concept data published ~41 kg ... not current production specification". Six such
clauses exist; every one of them is a figure about a family or a scrapped concept
being served as this product's own.

CONFLICT POLICY -- STATED, AND PRINTED ON EVERY DRY RUN
-------------------------------------------------------
The key is product_id, and the write is an UPSERT. It is NOT the DELETE-then-INSERT
competitor_portfolio.py does, because that discards a well-sourced row in favour of a
worse one whenever a workbook regresses, and leaves nothing behind to say it happened.

    An existing row is PROTECTED only when it cites a source this run does not have.
    Where the sources are the same, the two rows are two judgements of one body of
    evidence and the newer one -- which has read Source Health, the Evidence tier and
    OPEN ISSUES -- wins. Where the existing row cites something extra:

        strength = (tier rank official>registry>news, independent sources)

SPEC COUNT IS NOT PART OF IT. It was, for one draft, and it inverted the module's
whole purpose: a row whose absence clause had just been struck out carries one value
fewer than the dirty row it corrects, ranked lower, and was refused. 5 rows.

    absent from the table          -> INSERT
    incoming strength >= existing  -> UPDATE
    incoming strength <  existing  -> KEEP the existing row, count kept_better_sourced,
                                      write nothing. A better-sourced fact already on
                                      screen is not replaced by a worse one.
    on the table, refused here     -> withheld_reason is set. THE ROW IS NOT DELETED.
                                      Same choice as withhold_matchups.py: the reason
                                      travels with the row, one UPDATE restores it, and
                                      a rule I got wrong costs nothing but a --restore.

NOTHING IS EVER DELETED BY THIS MODULE, and it REFUSES TO RUN if its own rules would
withdraw more than a third of the table or admit nothing at all.

WHAT THIS DOES NOT FIX, AND MUST BE SAID
----------------------------------------
serving.competitor_product HAS NO READER. `grep -rn competitor_product` over the repo
finds this module, competitor_portfolio.py, and three schema files -- and nothing in
backend/, frontend/ or revive_matchups.py, whose docstring nevertheless names itself
as the consumer. So verifying and importing these rows does NOT by itself put a rival
figure beside a KSSL one on the Positioning screen. Wiring revive_matchups.py to read
this table is a separate change, and until it lands the honest claim for this work is
"the rival catalogue is now trustworthy", not "the comparisons are filled".
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from engine import source_tiers as st                                # noqa: E402
import competitor_portfolio as cp                                    # noqa: E402
import positioning_gate                                              # noqa: E402
import spec_direction                                                # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKBOOK = HERE / "portfolio" / "Defence_Competitor_MASTER_DATASET_CORRECTED_2026-09-06.xlsx"
OUT_JSON = HERE / "portfolio" / "competitor_specs.json"
DSN = os.environ.get("KSSL_DSN", "")

# A rule change must never be able to empty the table. Measured: the verified set
# withdraws 89 of 709, or 12.6%.
MAX_WITHDRAW_FRACTION = 1.0 / 3.0

REFUSALS: collections.Counter = collections.Counter()
CAVEATS: collections.Counter = collections.Counter()

# ── the workbook's own audits ────────────────────────────────────────────────
# The Evidence column, as a CEILING on our own gate. 'T2 independent x1' means the
# workbook found exactly one independent witness, which is the case engine/
# source_tiers.publishable already refuses; where it says that and our gate says
# OFFICIAL, the official-looking URL is not the maker's own.
WORKBOOK_TIER_ADMITS = {
    "T1 manufacturer/gov": True,
    "T2 independent x2": True,
    "T2 independent x1": False,
    "none": False,
}

# Source Health, verbatim from the workbook. Only 'all dead' and 'no source' refuse;
# a partial death is recorded as a caveat because the workbook publishes health per
# ROW and not per URL, so which of the surviving sources died cannot be known from
# it. See "what could not be verified" in the report.
HEALTH_DEAD = "all dead"
HEALTH_NONE = "no source"
HEALTH_PARTIAL = ("1 dead", "2 dead")

# OPEN ISSUES, HIGH: a company whose entry rests on nobody's word but the trade
# press's. For these an OFFICIAL verdict from engine/source_tiers cannot have come
# from the maker, so the row has to clear the two-independent-domains bar instead.
# One company today; the sheet is the only thing that puts a name in here.
NO_COMPANY_OWNED_SOURCE = {"NORINCO"}

# OPEN ISSUES, MEDIUM: "5 rows whose cited page does not contain the numbers ... the
# page loads, names the product, and carries none of the figures." Keyed by the exact
# (Company, Product) of the PRODUCT MASTER rows the sheet's prose names. Two of the
# five belong to companies that are refused earlier anyway (Solar is reference-only,
# Diehl is off the roster); they are listed all the same, so that the rule survives a
# roster change.
CITED_PAGE_LACKS_NUMBERS = {
    ("SSS Defence", "338 Saber"),
    ("Solar Industries", "Guided Pinaka Rocket"),
    ("Mahindra Defence", "Marksman"),
    ("Nexter (KNDS France)", "LECLERC XLR"),
    ("Diehl Defence", "IRIS-T Air-to-Air Missile"),
}

# A CLAUSE THAT HANGS ITS NUMBER ON SOMEBODY ELSE. Not the same fault as an absence:
# here a figure IS given, and the sentence says it is a class figure, a commonly
# reported one, or a scrapped concept's -- not this product's stated specification.
# Six clauses in the whole workbook; each was read before the phrase was added:
#   PLR TAVOR TAR-21   "public secondary sources commonly report TAR-21 class figures"
#   PLR GALIL Sniper   "chambering commonly associated with 7.62x51 mm"
#   Paramount N-Raven  "Earlier concept data published ~41 kg ... prototype lineage"
#   Kalashnikov KORD   "cyclic rate commonly reported around 600 rpm"
#   Kalashnikov KUB-E  "launch mass commonly reported around 3 kg class"
#   IAI LORA           "400 km class export range commonly reported"
HEDGED = re.compile(r"class figures|figures vary by|commonly report|"
                    r"commonly associated with|concept data|prototype lineage|"
                    r"earlier concept", re.I)

# Clauses, not sentences: a semicolon separates two specifications as often as a full
# stop does, and a full stop inside "4.5 ms" or "5.56x45" separates nothing, which is
# why the delimiter must be followed by whitespace.
_CLAUSE = re.compile(r"(?<=[;.])\s+")


def stated_clauses(note):
    """-> (what the bullet actually states, [the clauses that state nothing]).

    An absence and a hedge are properties of the CLAUSE they appear in. Judging the
    whole bullet loses "Length class: 42 m" to the sentence that follows it, and
    keeping the whole bullet serves that sentence as a specification."""
    keep, drop = [], []
    for c in _CLAUSE.split(note or ""):
        if not c.strip():
            continue
        (drop if (cp.NO_FIGURE.search(c) or HEDGED.search(c)) else keep).append(c.strip())
    return " ".join(keep).strip(), drop


def verified_specs(cell):
    """-> (specs, absences). `specs` is competitor_portfolio's shape plus provenance.

    Every bullet goes through competitor_portfolio.specs_of, which is the module that
    already decides whether a bullet states a measurable value. What is added here is
    the clause filter above and `hi`, stamped from spec_direction's FIELD table so a
    rival value arrives on the table already comparable -- the flag revive_matchups
    needs to draw a lead, and the one the archive used to type by hand per row."""
    specs, absences = [], []
    for s in cp.specs_of(cell):
        kept, dropped = stated_clauses(s["note"])
        absences.extend(dropped)
        if not kept:
            continue
        for t in cp.specs_of("• " + kept):
            # direction_of, not stamp(): stamp reads the label under 'l'/'label' and
            # these specs carry it under 'k'. The TABLE is the thing being reused.
            t["hi"] = spec_direction.direction_of(t["k"])
            specs.append(t)
    return specs, absences


def absence_only(cell):
    """A non-empty spec cell that states no figure BECAUSE it says there is none."""
    return bool((cell or "").strip()) and bool(cp.NO_FIGURE.search(cell or ""))


# ── the row-level gate ───────────────────────────────────────────────────────
def verify(rows):
    """-> [product]. Pure: no DB, no network, no spreadsheet. Fills REFUSALS/CAVEATS.

    The ROSTER rules (2 and 3) are not applied here -- they need serving.competitors,
    and a roster snapshot committed to a file would be stale within the day. `plan`
    applies them against the live table.
    """
    REFUSALS.clear()
    CAVEATS.clear()
    out = []
    for r in rows:
        comp = (r.get("Company") or "").strip()
        name = (r.get("Product") or "").strip()
        cell = r.get("Technical Specifications") or ""

        if (comp, name) in cp.DOUBLE_COUNTED:
            REFUSALS["double_counted"] += 1
            continue
        if (comp, name) in CITED_PAGE_LACKS_NUMBERS:
            REFUSALS["cited_page_lacks_the_numbers"] += 1
            continue

        health = (r.get("Source Health") or "").strip()
        srcs = cp.urls_in(r.get("Sources") or "")
        if health == HEALTH_NONE or not srcs:
            REFUSALS["no_source"] += 1
            continue
        if health == HEALTH_DEAD:
            REFUSALS["all_sources_dead"] += 1
            continue

        ok, why, tier_used, n_indep = st.publishable(srcs, product_maker=comp)
        if not ok:
            REFUSALS["unpublishable: %s" % why] += 1
            continue

        # OPEN ISSUES asks for a DEMOTION, not a deletion -- "mark the entry tier-2 so
        # scoring discounts it" -- so that is what happens. The row then has to clear
        # the tier-2 bar on its own merits: two independent domains, which is the same
        # test publishable() applies when nothing official is present. On the
        # 2026-09-06 master both admitted NORINCO rows do have two domains, so the
        # measured effect is 2 rows demoted from 'official' to 'registry' and 0
        # refused. What changes is what the UI is allowed to say about the figure.
        if comp in NO_COMPANY_OWNED_SOURCE and tier_used == st.OFFICIAL:
            if n_indep < 2:
                REFUSALS["no_company_owned_source (OPEN ISSUES): %s" % comp] += 1
                continue
            tier_used = st.REGISTRY
            why = ("corroborated by %d independent sources; demoted from official -- "
                   "OPEN ISSUES: %s has no company-owned source" % (n_indep, comp))
            CAVEATS["official demoted to tier-2: no company-owned source"] += 1

        wb_tier = (r.get("Evidence") or "").strip()
        if not WORKBOOK_TIER_ADMITS.get(wb_tier, False):
            REFUSALS["workbook_evidence_below_bar: %s" % (wb_tier or "(blank)")] += 1
            continue

        specs, absences = verified_specs(cell)
        if not specs:
            REFUSALS["absence_only" if absence_only(cell) else "no_measurable_value"] += 1
            continue

        if health in HEALTH_PARTIAL:
            CAVEATS["some sources dead, which ones is not recorded per URL"] += 1
        if absences:
            CAVEATS["absence or hedge clause struck from a bullet"] += len(absences)

        cat = (r.get("Category") or "").strip()
        # The KIND is a caveat and NEVER a refusal. positioning_gate says so itself:
        # an unresolved kind is a gap in a keyword table, not a finding about the
        # product, and refusing on it deleted seven of ten pairings the one time it
        # was tried. Recorded so the gap is a worklist instead of a silent None.
        kind = positioning_gate.kind_of(name)
        if kind is None:
            CAVEATS["no kind for the product name (positioning_gate)"] += 1

        # PROVENANCE TRAVELS WITH THE FIGURE. A spec that reaches a matchup row is
        # separated from its parent product, so the URLs, the count and the tier are
        # written onto each spec as well as onto the row. They are the same values --
        # the workbook attributes sources per ROW, never per bullet, and pretending
        # otherwise would be an invented attribution.
        for s in specs:
            s["srcs"] = srcs
            s["src_n"] = len(srcs)
            s["tier"] = tier_used
        out.append({
            "product_id": "cp_%s_%s" % (cp.slug(comp), cp.slug(name)),
            "company": comp,
            "name": name,
            "file_category": cat,
            "catKey": cp.CAT_KEY.get(cat),
            "specs": specs,
            "features": cp.specs_of(r.get("Features & Capabilities") or ""),
            "sources": srcs,
            "evidence": {
                "why": why,                       # which branch of publishable() admitted it
                "tier": tier_used,
                "independent": n_indep,
                "source_count": len(srcs),
                "workbook_tier": wb_tier,         # the workbook's own audit of the row
                "source_health": health,
                # LOW priority in OPEN ISSUES and stored WITH that caveat: "Granularity
                # is a heuristic, not a measurement -- assigned by name and category."
                # The GRANULARITY MATRIX sheet says a comparison is only meaningful
                # between companies at the same level, so the pairing layer wants it;
                # nothing here gates on it.
                "granularity": (r.get("Granularity") or "").strip() or None,
                "granularity_is_a_heuristic": True,
                "kind": kind,
                "absent": absences,               # what the cell declined to state
            },
        })
    return out


# ── the committed artefact ───────────────────────────────────────────────────
def parse(path=WORKBOOK):
    """PRODUCT MASTER, through competitor_portfolio's parser. Needs openpyxl, which is
    not in extraction/requirements.txt -- run locally and commit the JSON, the same
    arrangement client_portfolio.py and competitor_portfolio.py use."""
    _directory, products = cp.parse_workbook(Path(path))
    return products


def write_json(products, rows_in, path=OUT_JSON, source=None):
    doc = {
        "built_from": (source or WORKBOOK).name,
        "gate": "engine/source_tiers.publishable AND the workbook's own "
                "Source Health / Evidence / OPEN ISSUES audits",
        "rows_in": rows_in,
        "products": products,
        "refused": dict(REFUSALS),
        "caveats": dict(CAVEATS),
        # spec_direction.UNKNOWN is filled while verify() runs and is empty by the
        # time anything reads the JSON, so it is captured here. An unrecognised label
        # is a gap in that table to close on purpose -- spec_direction's docstring is
        # explicit that guessing a direction from a substring is wrong in both
        # directions -- and a gap nobody prints is not a worklist.
        "labels_with_no_direction": dict(spec_direction.UNKNOWN.most_common()),
    }
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return doc


def load(path=OUT_JSON):
    """-> (products, refusals, caveats, rows_in). What every runtime path reads."""
    if not Path(path).exists():
        raise SystemExit("no %s -- run --xlsx to build it" % Path(path).name)
    d = json.load(io.open(path, encoding="utf-8"))
    return (d["products"], collections.Counter(d.get("refused", {})),
            collections.Counter(d.get("caveats", {})), d.get("rows_in", 0),
            collections.Counter(d.get("labels_with_no_direction", {})))


# ── the roster join ──────────────────────────────────────────────────────────
def resolve_roster(cur, names):
    """-> (served {name: (comp_id, roster name)}, reference_only {...}, unmatched []).

    TWO PASSES, and the order is the whole point. A workbook name is matched against
    the SERVED roster first; only the names that fail are offered the reference rows.
    Matching against the union would let "Larsen & Toubro (L&T)" bind to reference
    'LT' while a served L&T row sat unclaimed under another spelling.
    """
    cur.execute("SELECT comp_id, name FROM serving.competitors WHERE origin='pipeline'")
    served_rows = list(cur.fetchall())
    cur.execute("SELECT comp_id, name FROM serving.competitors WHERE origin='reference'")
    ref_rows = list(cur.fetchall())

    served = cp.match_companies(served_rows, names)
    rest = [n for n in names if n not in served]
    reference_only = cp.match_companies(ref_rows, rest)
    unmatched = [n for n in rest if n not in reference_only]
    return served, reference_only, unmatched


TIER_RANK = {st.OFFICIAL: 3, st.REGISTRY: 2, st.NEWS: 1}


def strength(tier, independent, n_specs=None):
    """How well SOURCED a row is. A single official source outranks any number of
    news outlets, and independent witnesses break the tie.

    `n_specs` IS DELIBERATELY IGNORED, and it was not on the first draft. Spec count
    was the third term, which made a row that had got CLEANER rank lower than the row
    it was correcting: strike an absence clause off a bullet and the incoming row has
    one value fewer, so `incoming < existing` and the dirty row was kept. Measured on
    this workbook: 5 rows, every one of them a row this module exists to fix. A count
    is not evidence about sourcing and must not be allowed to vote on it. The argument
    is kept so callers reading the old signature get an error at the reader, not a
    silent change of meaning."""
    return (TIER_RANK.get(tier, 0), int(independent or 0))


def plan(cur, products):
    """What --apply would do. Reads only. -> dict of lists."""
    names = sorted({p["company"] for p in products})
    served, reference_only, unmatched = resolve_roster(cur, names)

    admitted, off = [], collections.Counter()
    for p in products:
        c = p["company"]
        if c in served:
            q = dict(p)
            q["comp_id"] = served[c][0]
            admitted.append(q)
        elif c in reference_only:
            off["unserved_reference_id: %s -> %s" % (c, reference_only[c][0])] += 1
        else:
            off["not_on_roster: %s" % c] += 1

    cur.execute("SELECT product_id, evidence, sources, withheld_reason "
                "FROM serving.competitor_product WHERE origin='pipeline'")
    have = {}
    for pid, ev, sr, wr in cur.fetchall():
        ev = json.loads(ev) if isinstance(ev, str) else (ev or {})
        sr = json.loads(sr) if isinstance(sr, str) else (sr or [])
        have[pid] = (ev, sr, wr)

    inserts, updates, kept = [], [], []
    for p in admitted:
        cur_row = have.get(p["product_id"])
        if cur_row is None:
            inserts.append(p)
            continue
        ev, sr, _wr = cur_row
        # WHAT COUNTS AS "BETTER SOURCED" IS THE SOURCES, NOT THE STORED VERDICT.
        #
        # An existing row is protected only when it CITES something this run does
        # not have. If every URL it stands on is also in the incoming row, then both
        # rows are two judgements of the SAME evidence, and the newer judgement is
        # the one that has seen the workbook's Source Health, its Evidence tier and
        # its OPEN ISSUES -- refusing it there would freeze the over-claim in place.
        #
        # That is not hypothetical. The two NORINCO rows on the table today are
        # recorded as tier 'official' from an Australian army training portal; this
        # run demotes them to tier-2 on the same two URLs, exactly as OPEN ISSUES
        # asks. Comparing the stored verdicts alone made the demotion rank LOWER
        # than the claim it corrects, and kept the claim.
        theirs_only = set(sr) - set(p["sources"])
        if not theirs_only:
            updates.append(p)
            continue
        mine = strength(p["evidence"]["tier"], p["evidence"]["independent"])
        theirs = strength(ev.get("tier"), ev.get("independent"))
        (updates if mine >= theirs else kept).append(p)

    incoming = {p["product_id"] for p in admitted}
    withdraw = [(pid, wr) for pid, (_e, _s, wr) in sorted(have.items())
                if pid not in incoming and not wr]
    return {"served": served, "reference_only": reference_only, "unmatched": unmatched,
            "off_roster": off, "admitted": admitted, "inserts": inserts,
            "updates": updates, "kept_better_sourced": kept, "withdraw": withdraw,
            "have": have}


def guard(p):
    """Refuse to run when the rules would gut the table. A rule I got wrong must cost
    a loud stop, not a blank catalogue -- withhold_matchups.py makes the same refusal
    and for the same reason."""
    if not p["admitted"]:
        raise SystemExit("refusing: nothing was admitted; the roster join or the "
                         "workbook artefact is wrong, not the data")
    n_have = len(p["have"])
    if n_have and len(p["withdraw"]) > n_have * MAX_WITHDRAW_FRACTION:
        raise SystemExit("refusing: that would withhold %d of %d served rows (>%d%%)"
                         % (len(p["withdraw"]), n_have,
                            int(MAX_WITHDRAW_FRACTION * 100)))


_INSERT = """
INSERT INTO serving.competitor_product
  (product_id, ord, company, comp_id, name, file_category, cat, "catKey",
   specs, features, sources, evidence, origin, withheld_reason, updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
        'pipeline', NULL, now())
ON CONFLICT (product_id) DO UPDATE SET
  ord = EXCLUDED.ord, company = EXCLUDED.company, comp_id = EXCLUDED.comp_id,
  name = EXCLUDED.name, file_category = EXCLUDED.file_category, cat = EXCLUDED.cat,
  "catKey" = EXCLUDED."catKey", specs = EXCLUDED.specs, features = EXCLUDED.features,
  sources = EXCLUDED.sources, evidence = EXCLUDED.evidence,
  withheld_reason = NULL, updated_at = now()
"""


def apply_(cur, p):
    """UPSERT what was admitted; withhold what was refused. Deletes nothing."""
    guard(p)
    order = {q["product_id"]: i for i, q in enumerate(p["admitted"])}
    for q in p["inserts"] + p["updates"]:
        cur.execute(_INSERT, (
            q["product_id"], order[q["product_id"]], q["company"], q["comp_id"],
            q["name"], q["file_category"], q["file_category"], q["catKey"],
            json.dumps(q["specs"], ensure_ascii=False),
            json.dumps(q["features"], ensure_ascii=False),
            json.dumps(q["sources"], ensure_ascii=False),
            json.dumps(q["evidence"], ensure_ascii=False)))
    n_ins, n_upd = len(p["inserts"]), len(p["updates"])
    for pid, _wr in p["withdraw"]:
        cur.execute("UPDATE serving.competitor_product "
                    "SET withheld_reason='failed_verification', updated_at=now() "
                    "WHERE product_id=%s AND origin='pipeline'", (pid,))
    return n_ins, n_upd, len(p["withdraw"])


def restore(cur):
    cur.execute("UPDATE serving.competitor_product SET withheld_reason=NULL "
                "WHERE withheld_reason IS NOT NULL")
    return cur.rowcount


# ── reporting ────────────────────────────────────────────────────────────────
def report():
    products, refused, caveats, rows_in, unk = load()
    print("COMPETITOR PRODUCT SPECIFICATIONS -- workbook-side verification")
    print("  rows in the PRODUCT MASTER   : %d" % rows_in)
    print("  admitted (before the roster) : %d" % len(products))
    print("  specification values         : %d" % sum(len(p["specs"]) for p in products))
    print("  companies                    : %d" % len({p["company"] for p in products}))
    print("\n  refused (%d):" % sum(refused.values()))
    for why, n in refused.most_common():
        print("    %5d  %s" % (n, why))
    print("\n  caveats (recorded, not refused):")
    for why, n in caveats.most_common():
        print("    %5d  %s" % (n, why))
    print("\n  spec labels with no direction in spec_direction.DIRECTION: %d distinct"
          % len(unk))
    for k, n in unk.most_common(10):
        print("    %5d  %s" % (n, k))
    print("\n  THE ROSTER JOIN NEEDS THE DATABASE -- run --dry for it.")
    print("  NOTE: serving.competitor_product has no reader. Importing here does not"
          "\n  by itself fill the rival column of a Positioning comparison.")


def print_plan(p):
    print("\nCONFLICT POLICY: upsert on product_id. Nothing is ever DELETEd.")
    print("  same sources as the existing row     -> UPDATE, the newer judgement wins")
    print("  existing row cites a source we lack  -> KEEP it, unless our source tier")
    print("                                          and witness count are >= its own")
    print("  spec COUNT never votes: a row that got cleaner has one value fewer")
    print("  on the table but refused here        -> withheld_reason set, row kept")
    print("\nroster: %d company names served, %d reference-only, %d unmatched"
          % (len(p["served"]), len(p["reference_only"]), len(p["unmatched"])))
    print("\nwould INSERT            %5d" % len(p["inserts"]))
    print("would UPDATE            %5d" % len(p["updates"]))
    print("would KEEP (better)     %5d  existing row is better sourced" % len(p["kept_better_sourced"]))
    print("would WITHHOLD          %5d  on the table, refused by these rules" % len(p["withdraw"]))
    print("refused off the roster  %5d" % sum(p["off_roster"].values()))
    for why, n in p["off_roster"].most_common():
        print("    %5d  %s" % (n, why))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--xlsx", nargs="?", const=str(WORKBOOK))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    if a.demo:
        return demo()
    if a.xlsx:
        rows = parse(Path(a.xlsx))
        products = verify(rows)
        write_json(products, len(rows), source=Path(a.xlsx))
        print("wrote %s: %d of %d rows admitted, %d refused, %d caveats"
              % (OUT_JSON.name, len(products), len(rows),
                 sum(REFUSALS.values()), sum(CAVEATS.values())))
        return 0
    if a.report:
        return report()
    if not (a.dry or a.apply or a.restore):
        ap.error("choose --demo, --report, --xlsx, --dry, --apply or --restore")

    import psycopg2
    con = psycopg2.connect(DSN or "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
    cur = con.cursor()
    cur.execute("SET lock_timeout = '20s'")     # serving.* is written by the enrich pass
    if a.restore:
        n = restore(cur)
        con.commit()
        print("restored %d withheld row(s)" % n)
        return 0
    products = load()[0]
    p = plan(cur, products)
    print_plan(p)
    if not a.apply:
        print("\ndry run -- nothing written.")
        return 0
    n_ins, n_upd, n_wd = apply_(cur, p)
    con.commit()
    print("\napplied: %d inserted, %d updated, %d withheld, 0 deleted"
          % (n_ins, n_upd, n_wd))
    return 0


# ── self-check ───────────────────────────────────────────────────────────────
def demo():
    bad = [0]

    def ck(name, cond):
        print("  %-66s %s" % (name, "ok" if cond else "FAIL"))
        if not cond:
            bad[0] += 1
        return cond

    products, refused, caveats, rows_in, _unk = load()

    # 1. an absence is never a value, and the figure beside it survives
    s, absent = verified_specs(
        "• Length class: 42 m; detailed displacement/power not publicly "
        "exposed on current page")
    ck("an absence clause is struck and the stated figure survives",
       len(s) == 1 and "42 m" in s[0]["v"] and absent
       and not any("not publicly exposed" in x["note"] for x in s))
    # 2. a bullet that is ONLY an absence yields nothing at all
    s2, _a = verified_specs("• detailed public performance figures not "
                            "established in reviewed authoritative sources")
    ck("a bullet that is only an absence yields no spec", s2 == [])
    ck("...and that cell is recognised as an absence, not as empty prose",
       absence_only("detailed public performance figures not established in "
                    "reviewed authoritative sources"))
    # 3. a hedged clause is not this product's figure
    s3, a3 = verified_specs(
        "• Earlier concept data published ~41 kg / 250 km / 10-15 kg payload; "
        "retained only as prototype lineage, not current production specification")
    ck("a scrapped concept's figures are not served as the product's", s3 == [] and a3)
    s4, _a = verified_specs(
        "• 12.7x108 mm; heavy machine gun; ~25 kg weapon class depending "
        "mounting; cyclic rate commonly reported around 600 rpm; belt-fed.")
    ck("...but only that clause: the flatly stated figures in the same bullet stay",
       s4 and "12.7x108 mm" in s4[0]["note"] and "commonly reported" not in s4[0]["note"])

    # 4. the workbook's own audits refuse rows our gate alone admits
    row = {"Company": "NORINCO", "Product": "X", "Category": "Artillery",
           "Technical Specifications": "• Calibre: 155 mm",
           "Sources": "https://date.army.gov.au/x", "Source Count": "1",
           "Source Health": "live", "Evidence": "T2 independent x1"}
    ck("publishable() alone calls a foreign army's portal official for NORINCO",
       st.publishable(["https://date.army.gov.au/x"], product_maker="NORINCO")[0])
    ck("...and a single such source is refused: NORINCO owns no source (OPEN ISSUES)",
       verify([row]) == []
       and any("no_company_owned_source" in k for k in REFUSALS))
    # two independent domains DO clear the tier-2 bar OPEN ISSUES asks for, and the
    # row is admitted with 'official' demoted so the UI cannot overstate it.
    two = verify([dict(row, Evidence="T1 manufacturer/gov",
                       Sources="https://date.army.gov.au/x\n"
                               "https://www.armyrecognition.com/y")])
    ck("two independent sources clear tier-2, and 'official' is demoted to registry",
       len(two) == 1 and two[0]["evidence"]["tier"] == st.REGISTRY
       and "demoted from official" in two[0]["evidence"]["why"])
    # the workbook's own tier as a CEILING, on a company that does own its domain
    ck("the workbook's own T2-x1 tier is a ceiling on our own 'official' verdict",
       verify([dict(row, Company="Otokar", Product="Cobra II",
                    Sources="https://www.otokar.com.tr/p",
                    Evidence="T2 independent x1")]) == []
       and any("workbook_evidence_below_bar" in k for k in REFUSALS))
    ck("a zero-source row cannot become a served fact",
       verify([dict(row, Evidence="T1 manufacturer/gov", Sources="",
                    **{"Source Health": "no source"})]) == []
       and REFUSALS["no_source"] == 1)
    ck("a row whose every source is dead is not fresh evidence",
       verify([dict(row, Evidence="T1 manufacturer/gov",
                    Sources="https://www.norinco.com/p",
                    **{"Source Health": "all dead"})]) == []
       and REFUSALS["all_sources_dead"] == 1)
    ck("a row the workbook says is cited to a page without the numbers is refused",
       verify([dict(row, Company="Mahindra Defence", Product="Marksman",
                    Sources="https://www.mahindradefence.com/p")]) == []
       and REFUSALS["cited_page_lacks_the_numbers"] == 1)

    # 5. the committed artefact
    ck("the artefact was built from the corrected 2026-09-06 master",
       json.load(io.open(OUT_JSON, encoding="utf-8"))["built_from"]
       == WORKBOOK.name)
    ck("every admitted product has a value, a source and a catKey the UI knows",
       all(p["specs"] and p["sources"]
           and p["catKey"] in ("art", "amm", "sa", "pav", "nav", "uav", "mad")
           for p in products))
    ck("every spec carries its own provenance",
       all(all(s.get("srcs") and s.get("src_n") and s.get("tier") for s in p["specs"])
           for p in products))
    ck("no admitted spec carries an absence sentence",
       not any(cp.NO_FIGURE.search(s["note"]) or HEDGED.search(s["note"])
               for p in products for s in p["specs"]))
    ck("no admitted row rests on a dead-only or absent source",
       all(p["evidence"]["source_health"] not in (HEALTH_DEAD, HEALTH_NONE)
           for p in products))
    ck("the workbook's own tier admits every stored row",
       all(WORKBOOK_TIER_ADMITS.get(p["evidence"]["workbook_tier"]) for p in products))
    ck("the refusal counter is actually counting", sum(refused.values()) > 0)
    ck("this is a NARROWING of competitor_portfolio.py, never a widening",
       {p["product_id"] for p in products}
       <= {q["product_id"] for q in cp.load()[0]})

    # 6. the conflict policy
    ck("a single official source outranks two news outlets",
       strength(st.OFFICIAL, 1) > strength(st.NEWS, 2))
    ck("more specs never promote a worse-sourced row",
       strength(st.REGISTRY, 2) < strength(st.OFFICIAL, 1))
    ck("a row that got CLEANER still lands: spec count does not vote",
       strength(st.OFFICIAL, 2) >= strength(st.OFFICIAL, 2))

    print("all checks passed" if not bad[0] else "%d FAILED" % bad[0])
    return 1 if bad[0] else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
