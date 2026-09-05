"""What a competitor's specification has to clear before it can sit beside KSSL's.

    python test_competitor_portfolio.py       (no DB, no network)
    pytest test_competitor_portfolio.py

Every fixture is a row that is really in the workbook. An invented fixture would
test the gate against my own idea of the failure, which is how a sentence about
Poongsan reached 134 Nammo rows and nobody noticed for a full audit cycle.

The writer is exercised against a stub cursor. There is no KSSL database on a
workstation, and what can be wrong here is the CONTROL FLOW -- which rows it
decides to touch and which values it decides to overwrite. A stub tests that
directly; Postgres can be trusted to store what it is given.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import competitor_portfolio as cp                                 # noqa: E402
from engine import source_tiers as st                             # noqa: E402


def _built():
    if not hasattr(_built, "v"):
        _built.v = cp.build()
    return _built.v


# ── the gate: whose word counts, and for what ────────────────────────────────
def test_a_maker_is_official_about_its_own_product_only():
    """Rheinmetall's site states Rheinmetall's guns. On a KNDS gun it is a rival
    talking about a competitor, and treating that as official would let one
    company's marketing set another's numbers."""
    ok, _why, tier, _n = st.publishable(["https://www.rheinmetall.com/en/products/x"],
                                        product_maker="Rheinmetall")
    assert ok and tier == st.OFFICIAL

    ok, why, _t, _n = st.publishable(["https://www.rheinmetall.com/en/products/x"],
                                     product_maker="KNDS Germany")
    assert not ok, why


def test_the_fifty_makers_own_sites_now_rank_official():
    """Before 2026-09-06 none of these were in MAKER_DOMAINS, so a manufacturer's
    own datasheet ranked as a news mention and needed a second outlet to
    corroborate what it published about its own weapon."""
    for url, maker in [("https://www.nammo.com/product/x", "Nammo"),
                       ("https://www.mbda-systems.com/x", "MBDA"),
                       ("https://www.iai.co.il/p/x", "Israel Aerospace Industries (IAI)"),
                       ("https://www.poongsan.co.kr/x", "Poongsan"),
                       ("https://aweil.in/x", "AWEIL"),
                       ("https://www.sssdefence.com/x", "SSS Defence"),
                       ("https://www.pelgel.com/x", "Premier Explosives")]:
        ok, why, tier, _n = st.publishable([url], product_maker=maker)
        assert ok and tier == st.OFFICIAL, (url, maker, why)


def test_a_single_upload_host_is_never_enough():
    """16 of Munitions India's 33 rows cited Scribd and nothing else."""
    ok, why, _t, _n = st.publishable(["https://www.scribd.com/document/1/x"],
                                     product_maker="Munitions India Ltd (MIL)")
    assert not ok and "uncorroborated" in why, why


def test_two_independent_domains_corroborate():
    ok, why, _t, n = st.publishable(["https://www.armyrecognition.com/a",
                                     "https://www.janes.com/b"],
                                    product_maker="NORINCO")
    assert ok and n == 2, (ok, why, n)


def test_two_pages_of_one_outlet_are_one_witness():
    ok, _why, _t, n = st.publishable(["https://www.armyrecognition.com/a",
                                      "https://www.armyrecognition.com/b"],
                                     product_maker="NORINCO")
    assert not ok and n == 1


# ── what the workbook's own faults must not do ───────────────────────────────
def test_no_admitted_product_carries_another_company_text():
    products, _profiles = _built()
    for p in products:
        blob = " ".join(s["note"] for s in p["specs"])
        assert "Poongsan portfolio includes fuzes" not in blob, p["name"]
    assert cp.REFUSALS["another company's text removed from the spec cell"] == 134


def test_a_vehicle_is_not_counted_under_two_makers():
    products, _profiles = _built()
    leo = {p["name"] for p in products if p["company"] == "Leonardo"}
    idv = {p["name"] for p in products if p["company"] == "IDV (Iveco Defence)"}
    assert not (leo & idv), sorted(leo & idv)
    assert "Centauro II" not in leo


def test_a_cell_that_says_the_figure_is_unpublished_yields_no_spec():
    assert cp.specs_of("• Uncrewed air system in BAE portfolio\n"
                       "• detailed public numeric specifications not established.") == []
    got = cp.specs_of("• Calibre: 155 mm\n• Max range: 40 km with ERFB-BB")
    assert [g["k"] for g in got] == ["Calibre", "Max range"], got
    assert got[0]["v"] == "155 mm"


def test_every_admitted_row_has_a_value_a_source_and_a_dashboard_category():
    products, _profiles = _built()
    assert products
    for p in products:
        assert p["specs"], p["name"]
        assert p["sources"] and all(u.startswith("http") for u in p["sources"])
        assert p["catKey"] in ("art", "amm", "sa", "pav", "nav", "uav", "mad"), p
        assert p["evidence"]["tier"] in (st.OFFICIAL, st.REGISTRY, st.NEWS)


def test_the_refusal_counter_is_actually_counting():
    """A zero here means the checks are not running at all."""
    _p, _pr = _built()
    assert sum(cp.REFUSALS.values()) > 400, dict(cp.REFUSALS)


def test_category_map_is_never_a_label_join():
    """The workbook says 'Marine/Naval'; the dashboard says catKey 'nav'. Joining
    two display labels is how this project lost an entire layer once already."""
    assert cp.CAT_KEY["Marine/Naval"] == "nav"
    assert cp.CAT_KEY["Missiles"] == "mad"
    assert set(cp.CAT_KEY.values()) == {"art", "amm", "sa", "pav", "nav", "uav", "mad"}


# ── the profile columns ──────────────────────────────────────────────────────
def test_a_governance_sentence_is_never_returned_as_a_chairman():
    _p, profiles = _built()
    by = {p["company"]: p for p in profiles}
    assert by["IDV (Iveco Defence)"]["chairman"] is None       # "IDV became a Leonardo company"
    assert by["MBDA"]["chairman"] is None                      # "Multinational governance..."
    assert by["Paramount Group"]["chairman"] is None           # "...stepped back from"
    assert by["BAE Systems"]["chairman"].startswith("Cressida Hogg")
    for p in profiles:
        c = p["chairman"]
        assert c is None or not (cp._NOT_A_NAME.match(c) or cp._VACATED.search(c)), \
            (p["company"], c)


class _Cur:
    def __init__(self, rows):
        self._src, self._rows, self.writes = rows, [], []

    def execute(self, sql, args=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select comp_id"):
            self._rows = list(self._src)
        elif s.startswith("update serving.competitors"):
            self.writes.append((args[-1], sql))
        else:
            raise AssertionError("unexpected sql: %s" % s[:80])

    def fetchall(self):
        return self._rows


PROF = [{"company": "Rheinmetall", "hq": "Duesseldorf, Germany", "starting_year": 1889,
         "company_size": "33,217 employees", "sales": "EUR 9.935 billion",
         "financial_year": "FY2025", "global_locations": "Germany; Italy; Hungary",
         "sources": ["https://www.rheinmetall.com/x"], "publishable": True}]


def test_a_value_that_is_already_there_is_never_replaced():
    """A value already in the table came from the corpus with its own provenance.
    Swapping it silently would leave nobody able to say which number is shown."""
    cur = _Cur([("rheinmetall", "Rheinmetall", "Already set", 1889, "existing",
                 {"text": "existing"})])
    updates, unmatched, _have = cp.plan_profiles(cur, PROF)
    assert not unmatched
    set_ = updates[0][2] if updates else {}
    for blocked in ("hq", "starting_year", "company_size", "sales"):
        assert blocked not in set_, (blocked, set_)


def test_a_blank_is_filled():
    cur = _Cur([("rheinmetall", "Rheinmetall", "", None, "", None)])
    updates, _u, _h = cp.plan_profiles(cur, PROF)
    set_ = updates[0][2]
    assert set_["hq"] == "Duesseldorf, Germany"
    assert set_["starting_year"] == 1889
    assert set_["sales"]["fy"] == "FY2025"
    assert set_["global_locations"] == ["Germany", "Italy", "Hungary"]


def test_an_unpublishable_revenue_is_not_written():
    prof = [dict(PROF[0], publishable=False)]
    cur = _Cur([("rheinmetall", "Rheinmetall", "", None, "", None)])
    updates, _u, _h = cp.plan_profiles(cur, prof)
    assert "sales" not in updates[0][2]


def test_a_company_the_dashboard_does_not_track_is_reported_not_created():
    """Adding a competitor is a decision about who we watch. An importer that
    creates one silently has made that decision for the operator."""
    cur = _Cur([])
    updates, unmatched, _h = cp.plan_profiles(cur, PROF)
    assert unmatched == ["Rheinmetall"] and not updates and not cur.writes


def test_apply_touches_only_pipeline_rows():
    cur = _Cur([("rheinmetall", "Rheinmetall", "", None, "", None)])
    updates, _u, _h = cp.plan_profiles(cur, PROF)
    assert cp.apply_profiles(cur, updates) == 1
    cid, sql = cur.writes[0]
    assert cid == "rheinmetall"
    assert "origin='pipeline'" in sql
    assert "::jsonb" in sql


def test_match_key_does_not_collapse_two_companies():
    _p, profiles = _built()
    seen = {}
    for p in profiles:
        k = cp.key_of(p["company"])
        assert k not in seen, (k, seen[k], p["company"])
        seen[k] = p["company"]
    assert len(seen) == 50


def test_match_key_still_matches_the_names_the_dashboard_uses():
    for workbook, served in [("Larsen & Toubro (L&T)", "L&T"),
                             ("Bharat Dynamics Ltd (BDL)", "Bharat Dynamics"),
                             ("Munitions India Ltd (MIL)", "Munitions India"),
                             ("Adani Defence", "Adani Defence")]:
        assert cp.key_of(workbook) == cp.key_of(served), (workbook, served)


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    bad = 0
    for n, f in fns:
        try:
            f()
            print("  ok   %s" % n)
        except AssertionError as e:
            bad += 1
            print("  FAIL %s: %s" % (n, e))
    print("\n%d passed, %d failed" % (len(fns) - bad, bad))
    sys.exit(1 if bad else 0)
