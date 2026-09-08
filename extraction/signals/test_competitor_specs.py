# -*- coding: utf-8 -*-
"""What a competitor's specification has to clear before it becomes a SERVED fact.

    python test_competitor_specs.py       (no DB, no network, no spreadsheet)
    pytest test_competitor_specs.py

test_competitor_portfolio.py already tests the SOURCE gate. These are the tests for
the four audits the workbook carries about ITSELF and which nothing in this repo was
reading -- Source Health, the Evidence tier, OPEN ISSUES, and whether the company is
on the roster at all -- plus the conflict policy that decides what an import is
allowed to overwrite.

Every fixture is a row that is really in
Defence_Competitor_MASTER_DATASET_CORRECTED_2026-09-06.xlsx, quoted verbatim. An
invented fixture tests the gate against my own idea of the failure, which is how a
sentence about Poongsan reached 134 Nammo rows and survived a full audit cycle.

The writer is exercised against a stub cursor, as competitor_portfolio's tests are and
for the same reason: there is no KSSL database on a workstation, and what can be wrong
here is the CONTROL FLOW -- which rows it decides to touch, which it decides to leave
alone, and whether it ever issues a DELETE. Postgres can be trusted to store what it
is given.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import competitor_specs as cs                                     # noqa: E402
import competitor_portfolio as cp                                 # noqa: E402
from engine import source_tiers as st                             # noqa: E402


# A real PRODUCT MASTER row: AWEIL's 105 mm Light Field Gun, two live sources on the
# maker's own domain. It clears every rule, so each test below changes ONE column and
# the change is the only thing that can have caused the refusal.
GOOD = {
    "Company": "AWEIL",
    "Category": "Artillery",
    "Product": "105 mm Light Field Gun (LFG)",
    "Granularity": "variant",
    "Technical Specifications": "• Calibre: 105 mm\n• Maximum range: 17.2 km",
    "Features & Capabilities": "• Light field artillery",
    "Sources": ("https://www.aweil.in/download/Annual-Report-2024-25-en.pdf?v=1.87\n"
                "https://www.aweil.in/download/rti/manuals_standard/1.1.pdf"),
    "Source Count": "2",
    "Source Health": "live",
    "Evidence": "T1 manufacturer/gov",
}


def _one(**over):
    return cs.verify([dict(GOOD, **over)])


def test_the_baseline_row_is_admitted():
    """Without this the tests below would pass on a broken gate that refuses
    everything."""
    got = _one()
    assert len(got) == 1, got
    assert len(got[0]["specs"]) == 2, got[0]["specs"]


# ── 1. a row with no source cannot become a served fact ──────────────────────
def test_a_zero_source_row_is_refused():
    """31 rows of the workbook carry no URL at all. There is nothing for the UI to
    cite, so there is nothing to publish -- the number would be on screen on our
    word alone, which is the one thing this project has decided it will not do."""
    assert _one(Sources="", **{"Source Count": "0", "Source Health": "no source"}) == []
    assert cs.REFUSALS["no_source"] == 1


def test_a_zero_source_row_is_refused_even_when_the_health_column_lies():
    """The refusal is on the ABSENCE of a URL, not on the Source Health label. A
    future workbook that forgets to set 'no source' must not slip a sourceless row
    through on the strength of a string."""
    assert _one(Sources="", **{"Source Health": "live"}) == []
    assert cs.REFUSALS["no_source"] == 1


# ── 2. an 'all dead' row is not live evidence ────────────────────────────────
def test_a_row_whose_every_source_is_dead_is_not_fresh_evidence():
    """26 rows. OPEN ISSUES rates this HIGH: 'Re-source from the maker's current
    site and archive at capture time.' A dead URL cannot be re-checked by the
    operator, by a reviewer, or by us -- unverifiable is not publishable."""
    assert _one(**{"Source Health": "all dead"}) == []
    assert cs.REFUSALS["all_sources_dead"] == 1


def test_the_dead_source_refusal_survives_an_official_maker_domain():
    """This is the fault it actually catches. All seven rows served today with every
    source dead were admitted as 'stated by an official source' -- aweil.in,
    diehl.com, avinc.com are all MAKER_DOMAINS, so engine/source_tiers rates them
    official and never asks whether the page still answers."""
    ok, _why, tier, _n = st.publishable(cp.urls_in(GOOD["Sources"]),
                                        product_maker="AWEIL")
    assert ok and tier == st.OFFICIAL, "the fixture must be the hard case"
    assert _one(**{"Source Health": "all dead"}) == []


def test_a_partially_dead_row_is_kept_but_flagged():
    """'1 dead' of two sources is not 'all dead'. The workbook publishes health per
    ROW and never per URL, so WHICH source died cannot be known from it -- the row
    is admitted and the uncertainty is recorded rather than guessed away."""
    got = _one(**{"Source Health": "1 dead"})
    assert len(got) == 1
    assert got[0]["evidence"]["source_health"] == "1 dead"
    assert cs.CAVEATS["some sources dead, which ones is not recorded per URL"] == 1


# ── 3. an absence is never a value ───────────────────────────────────────────
def test_a_not_established_line_is_never_stored_as_a_value():
    """The exact sentence the workbook uses where a figure could not be found. It
    states no number; stored, it renders in a spec table as though it were one."""
    cell = ("• detailed public performance figures not established in "
            "reviewed authoritative sources")
    specs, absent = cs.verified_specs(cell)
    assert specs == [], specs
    assert cs.absence_only(cell), "the cell must be recognised as an absence"
    assert _one(**{"Technical Specifications": cell}) == []
    assert cs.REFUSALS["absence_only"] == 1


def test_an_absence_does_not_take_the_figure_beside_it():
    """Paramount Group's 42 m Frontier, verbatim. Refusing the whole bullet loses
    '42 m'; keeping it serves the sentence. The absence belongs to its own CLAUSE."""
    specs, absent = cs.verified_specs(
        "• Length class: 42 m; detailed displacement/power not publicly "
        "exposed on current page")
    assert len(specs) == 1, specs
    assert "42 m" in specs[0]["v"]
    assert not any("not publicly exposed" in s["note"] for s in specs)
    assert absent and "not publicly exposed" in absent[0]


def test_the_absence_is_recorded_rather_than_discarded():
    """'Stored as absence' means the cell's refusal to state a figure survives on the
    row, where a reader can see that the gap was found rather than never looked for."""
    got = _one(**{"Technical Specifications":
                  "• Length class: 42 m; detailed displacement/power not "
                  "publicly exposed on current page"})
    assert got[0]["evidence"]["absent"], got[0]["evidence"]


def test_a_figure_hung_on_somebody_else_is_not_this_products_figure():
    """Paramount's N-Raven, verbatim: the sentence says these numbers are NOT the
    current production specification, and the numbers were being served as if they
    were. Evidence that exists is not evidence that entails."""
    specs, absent = cs.verified_specs(
        "• Earlier concept data published ~41 kg / 250 km / 10–15 kg "
        "payload; retained only as prototype lineage, not current production "
        "specification")
    assert specs == [], specs
    assert absent


def test_the_hedge_rule_takes_the_clause_and_not_the_bullet():
    """Kalashnikov's KORD, verbatim. One hedged clause among four stated ones must
    not cost the three real figures -- a rule that over-refuses is the mirror of the
    fault it is fixing."""
    specs, _a = cs.verified_specs(
        "• 12.7×108 mm; heavy machine gun; ~25 kg weapon class depending "
        "mounting; effective range ~2,000 m class; cyclic rate commonly reported "
        "around 600 rpm; belt-fed.")
    assert len(specs) == 1
    note = specs[0]["note"]
    assert "12.7" in note and "25 kg" in note and "2,000 m" in note
    assert "commonly reported" not in note


def test_no_admitted_spec_in_the_whole_workbook_carries_an_absence():
    """The corpus-wide version of the rule. A phrase list is only as good as the
    corpus it was measured on, so it is measured on all 1,072 rows."""
    products = cs.load()[0]
    bad = [(p["name"], s["note"]) for p in products for s in p["specs"]
           if cp.NO_FIGURE.search(s["note"]) or cs.HEDGED.search(s["note"])]
    assert not bad, bad[:3]


# ── 4. OPEN ISSUES: the workbook's own doubts ────────────────────────────────
def test_a_row_the_workbook_says_is_wrongly_cited_is_refused():
    """OPEN ISSUES, MEDIUM: 'the page loads, names the product, and carries none of
    the figures'. The workbook opened the page; we did not. Overruling it would be
    preferring our own convenience to somebody else's measurement."""
    assert cs.verify([dict(GOOD, Company="Mahindra Defence", Product="Marksman",
                           Sources="https://www.mahindradefence.com/p")]) == []
    assert cs.REFUSALS["cited_page_lacks_the_numbers"] == 1


def test_a_company_with_no_source_of_its_own_cannot_be_official():
    """OPEN ISSUES, HIGH, on NORINCO. engine/source_tiers rightly holds that a
    government publisher is official for anyone -- but an Australian army training
    portal is official about a procurement, not about a Chinese factory's data
    sheet, and it was setting a rival's numbers."""
    single = cs.verify([dict(GOOD, Company="NORINCO", Product="Type 90B",
                             Sources="https://date.army.gov.au/equipment/type-90b")])
    assert single == []
    assert any("no_company_owned_source" in k for k in cs.REFUSALS)
    # two independent domains DO clear the tier-2 bar the sheet asks for, and the
    # row is admitted with its tier demoted so the UI cannot overstate it.
    pair = cs.verify([dict(GOOD, Company="NORINCO", Product="Type 90B",
                           Sources="https://date.army.gov.au/equipment/type-90b\n"
                                   "https://www.armyrecognition.com/x")])
    assert len(pair) == 1
    assert pair[0]["evidence"]["tier"] == st.REGISTRY, pair[0]["evidence"]


def test_the_workbooks_own_tier_is_a_ceiling_on_ours():
    """Two gates built independently must both pass. Where the workbook resolved the
    URLs and rated the row 'T2 independent x1' while our domain table says official,
    the official-looking URL is not the maker's."""
    assert _one(Evidence="T2 independent x1") == []
    assert any("workbook_evidence_below_bar" in k for k in cs.REFUSALS)


# ── 5. the roster join ───────────────────────────────────────────────────────
class _Cur:
    """Enough of psycopg2 to test the control flow. Records every write, so a test
    can assert that no DELETE was issued -- which is a claim about what the importer
    does NOT do, and is exactly the kind nobody writes and everybody needs."""

    def __init__(self, served=(), reference=(), existing=()):
        self.served, self.reference, self.existing = served, reference, existing
        self._rows, self.writes = [], []

    def execute(self, sql, args=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select comp_id") and "'pipeline'" in s:
            self._rows = list(self.served)
        elif s.startswith("select comp_id") and "'reference'" in s:
            self._rows = list(self.reference)
        elif s.startswith("select product_id"):
            self._rows = list(self.existing)
        else:
            self.writes.append((s.split()[0], args))

    def fetchall(self):
        return self._rows


def _prod(pid, company, tier=st.OFFICIAL, indep=2, n_specs=2, srcs=None):
    return {"product_id": pid, "company": company, "name": pid, "comp_id": None,
            "file_category": "Artillery", "catKey": "art",
            "specs": [{"k": "Calibre", "v": "105 mm", "note": "x", "hi": None}] * n_specs,
            "features": [], "sources": list(srcs or ["https://www.aweil.in/a"]),
            "evidence": {"why": "w", "tier": tier, "independent": indep}}


def test_a_company_that_matches_only_a_reference_row_is_not_imported():
    """'Larsen & Toubro (L&T)' reaches comp_id 'LT', which is origin='reference' and
    therefore absent from serving_live.competitors. Importing under it would attach
    21 products to a competitor no user can open -- the same duplicate-id fault the
    geo tables already have. Refused, and the id is NAMED, because the fix is a
    roster merge and not an import flag."""
    cur = _Cur(served=[("RHEIN", "Rheinmetall")],
               reference=[("LT", "L&amp;T"), ("SOLAR", "Solar Industries")])
    p = cs.plan(cur, [_prod("cp_lt_x", "Larsen & Toubro (L&T)")])
    assert p["admitted"] == []
    assert p["inserts"] == []
    assert any("unserved_reference_id" in k and "LT" in k for k in p["off_roster"]), \
        dict(p["off_roster"])


def test_a_company_on_no_roster_at_all_gets_no_invented_entry():
    """Nine companies match nothing, and several are not KSSL competitors -- two are
    naval shipbuilders. The importer writes no product for them and, deliberately,
    creates no competitor row to hang one on."""
    cur = _Cur(served=[("RHEIN", "Rheinmetall")], reference=[])
    p = cs.plan(cur, [_prod("cp_hii_x", "Huntington Ingalls Industries")])
    assert p["admitted"] == [] and p["inserts"] == []
    assert any(k.startswith("not_on_roster") for k in p["off_roster"])
    assert not any(w[0] == "insert" for w in cur.writes), cur.writes


def test_a_served_company_is_imported_under_its_served_id():
    cur = _Cur(served=[("RHEIN", "Rheinmetall")], reference=[("LT", "L&amp;T")])
    p = cs.plan(cur, [_prod("cp_rh_x", "Rheinmetall")])
    assert len(p["inserts"]) == 1
    assert p["inserts"][0]["comp_id"] == "RHEIN"


def test_the_served_roster_is_matched_before_the_reference_one():
    """Order, not preference. If both passes ran against the union, a workbook name
    could bind to a reference id while its served row sat unclaimed under a
    different spelling -- and the row would be silently refused."""
    cur = _Cur(served=[("lt", "Larsen &amp; Toubro")], reference=[("LT", "L&T")])
    p = cs.plan(cur, [_prod("cp_lt_x", "Larsen & Toubro (L&T)")])
    assert len(p["inserts"]) == 1, dict(p["off_roster"])
    assert p["inserts"][0]["comp_id"] == "lt"


# ── 6. the conflict policy ───────────────────────────────────────────────────
def _existing(pid, tier=st.OFFICIAL, indep=2, n_specs=2, withheld=None, srcs=None):
    """(product_id, evidence, SOURCES, withheld_reason) -- the four columns plan()
    reads. `n_specs` is accepted and unused: the policy stopped counting specs when
    counting them was found to refuse a row for having been cleaned."""
    return (pid, json.dumps({"tier": tier, "independent": indep}),
            json.dumps(list(srcs or ["https://www.aweil.in/a"])), withheld)


def test_a_better_sourced_existing_row_is_not_overwritten():
    """The reason this is an UPSERT and not competitor_portfolio's DELETE-then-
    INSERT. A workbook that regresses on one product must not take a well-sourced
    figure off the screen and leave nothing behind to say it happened."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_x", st.OFFICIAL, 3,
                                   srcs=["https://www.aweil.in/a",
                                         "https://pib.gov.in/only-the-old-row-has-this"])])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL", tier=st.NEWS, indep=2, n_specs=1)])
    assert p["updates"] == []
    assert len(p["kept_better_sourced"]) == 1


def test_a_longer_spec_list_never_promotes_a_worse_sourced_row():
    """Spec count is the LAST term of the strength tuple on purpose. Forty numbers
    from a news site are still forty numbers from a news site."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_x", st.OFFICIAL, 1,
                                   srcs=["https://www.aweil.in/a",
                                         "https://pib.gov.in/only-the-old-row-has-this"])])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL", tier=st.NEWS, indep=2, n_specs=40)])
    assert p["kept_better_sourced"] and not p["updates"]


def test_an_equally_sourced_row_still_updates():
    """A gate that only ever wrote strictly-better rows could never land a
    correction to a value, which is the commonest reason a workbook is re-issued."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_x", st.OFFICIAL, 2, 2)])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL", tier=st.OFFICIAL, indep=2, n_specs=2)])
    assert len(p["updates"]) == 1 and not p["kept_better_sourced"]


def test_a_row_that_got_cleaner_is_not_refused_for_having_fewer_values():
    """THE FAULT THE FIRST DRAFT SHIPPED. Spec count was the third term of the
    strength tuple, so striking an absence clause off a bullet -- the entire point of
    this module -- left the incoming row one value short of the dirty row it was
    correcting, ranked it lower, and kept the dirty one. It refused 5 real rows of
    this workbook. A count is not evidence about sourcing and does not get a vote."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_x", st.OFFICIAL, 2, n_specs=6,
                                   srcs=["https://www.aweil.in/a",
                                         "https://pib.gov.in/x"])])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL", tier=st.OFFICIAL, indep=2, n_specs=5,
                            srcs=["https://www.aweil.in/a", "https://pib.gov.in/x"])])
    assert len(p["updates"]) == 1, p["kept_better_sourced"]
    assert not p["kept_better_sourced"]


def test_a_demotion_on_the_same_sources_still_lands():
    """The NORINCO case, and the second fault the first draft shipped. The row on the
    table says 'official'; this run reads the same two URLs and demotes it to tier-2
    because OPEN ISSUES says the company owns neither of them. Comparing the STORED
    VERDICTS ranked the correction below the claim it corrects and kept the claim.
    Where the sources are the same, the newer judgement wins."""
    srcs = ["https://date.army.gov.au/x", "https://www.armyrecognition.com/y"]
    cur = _Cur(served=[("NORINCO", "NORINCO")],
               existing=[_existing("cp_n_x", st.OFFICIAL, 2, srcs=srcs)])
    p = cs.plan(cur, [_prod("cp_n_x", "NORINCO", tier=st.REGISTRY, indep=2, srcs=srcs)])
    assert len(p["updates"]) == 1, p["kept_better_sourced"]


def test_an_extra_source_on_the_existing_row_is_what_protects_it():
    """The protection is about EVIDENCE, so it must switch off when the evidence is
    the same. Identical fixture to the test above except for one URL only the
    existing row carries."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_x", st.OFFICIAL, 2,
                                   srcs=["https://www.aweil.in/a",
                                         "https://pib.gov.in/extra"])])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL", tier=st.NEWS, indep=1,
                            srcs=["https://www.aweil.in/a"])])
    assert p["kept_better_sourced"] and not p["updates"]


def test_a_row_that_stops_verifying_is_withheld_and_never_deleted():
    """withhold_matchups.py's choice, for withhold_matchups.py's reason: the reason
    travels with the row and one UPDATE restores it, so a refusal rule I got wrong
    costs a --restore and not a re-import."""
    # six on the table, five still verifying: one withdrawal, well under the guard.
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_%d" % i) for i in range(5)]
                        + [_existing("cp_a_gone")])
    p = cs.plan(cur, [_prod("cp_a_%d" % i, "AWEIL") for i in range(5)]
                     + [_prod("cp_a_new", "AWEIL")])
    assert [pid for pid, _wr in p["withdraw"]] == ["cp_a_gone"]
    cs.apply_(cur, p)
    verbs = {w[0] for w in cur.writes}
    assert "delete" not in verbs, cur.writes
    assert "update" in verbs and "insert" in verbs


def test_an_already_withheld_row_is_not_withheld_twice():
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_gone", withheld="failed_verification")])
    p = cs.plan(cur, [_prod("cp_a_keep", "AWEIL")])
    assert p["withdraw"] == []


# ── 7. the refusal guard ─────────────────────────────────────────────────────
def test_the_importer_refuses_to_gut_the_table():
    """A rule change must cost a loud stop, not a blank catalogue. Nine existing
    rows, one survivor: eight withdrawals is well past a third."""
    cur = _Cur(served=[("AWEIL", "AWEIL")],
               existing=[_existing("cp_a_%d" % i) for i in range(9)])
    p = cs.plan(cur, [_prod("cp_a_0", "AWEIL")])
    try:
        cs.apply_(cur, p)
    except SystemExit as e:
        assert "refusing" in str(e), e
    else:
        raise AssertionError("no guard: it would have withheld %d of 9"
                             % len(p["withdraw"]))
    assert not cur.writes, "nothing may be written before the guard runs"


def test_the_importer_refuses_to_write_nothing_at_all():
    """An empty admitted set means the roster join or the artefact is broken, not
    that the competitors stopped making things.

    `existing` is EMPTY on purpose. With rows on the table an empty import also trips
    the withdraw-fraction guard, so this test would pass without the emptiness check
    existing at all -- which is what a revert run showed, and is why the fixture is
    the one shape where only this guard can fire."""
    cur = _Cur(served=[], existing=[])
    p = cs.plan(cur, [_prod("cp_a_x", "AWEIL")])
    try:
        cs.apply_(cur, p)
    except SystemExit as e:
        assert "refusing" in str(e), e
    else:
        raise AssertionError("an empty import must not be applied silently")


# ── 8. the shape of what is stored ───────────────────────────────────────────
def test_every_spec_carries_the_provenance_of_its_own_figure():
    """A spec that reaches a matchup row is separated from the product that sourced
    it, so the URLs, the count and the tier travel on the spec as well as the row."""
    s = _one()[0]["specs"][0]
    assert s["srcs"] and s["src_n"] == 2 and s["tier"] == st.OFFICIAL


def test_the_row_records_the_workbooks_own_audit_beside_ours():
    ev = _one()[0]["evidence"]
    assert ev["workbook_tier"] == "T1 manufacturer/gov"
    assert ev["source_health"] == "live"
    assert ev["source_count"] == 2
    assert ev["granularity"] == "variant" and ev["granularity_is_a_heuristic"]


def test_direction_is_stamped_from_the_field_table_not_guessed():
    """`hi` comes from spec_direction.DIRECTION, keyed by FIELD. Calibre must have
    none -- 155 mm is not better than 105 mm, it is a different class of gun -- and
    a range must be higher-is-better."""
    specs = _one()[0]["specs"]
    by = {s["k"]: s["hi"] for s in specs}
    assert by["Calibre"] is None, by
    assert by["Maximum range"] is True, by


def test_this_is_a_narrowing_of_the_existing_import():
    """Every row admitted here is already admitted by competitor_portfolio.py. If
    this ever stops holding, the two gates have diverged and one of them is wrong."""
    mine = {p["product_id"] for p in cs.load()[0]}
    theirs = {p["product_id"] for p in cp.load()[0]}
    assert mine <= theirs, sorted(mine - theirs)[:5]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok    %s" % name)
            except Exception as e:                                 # noqa: BLE001
                fails += 1
                print("  FAIL  %s: %s" % (name, e))
    print("all passed" if not fails else "%d FAILED" % fails)
    sys.exit(1 if fails else 0)
