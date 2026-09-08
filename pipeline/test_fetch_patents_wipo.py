# -*- coding: utf-8 -*-
"""Checks for fetch_patents_wipo.py that outlive one run.

    python -m pytest pipeline/test_fetch_patents_wipo.py -q
    python pipeline/test_fetch_patents_wipo.py          # no pytest needed

Hermetic: no network, no database. Two of these read repository artefacts -- the
1,157-row ledger and the drop list beside it -- because the faults they guard were
found in those files and not in any fixture. Collection is by name: pytest collects
test_* only, and a helper called check_* would run zero assertions and report green.
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_patents_wipo as M                                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "fetch_patents_wipo.json")
DROPS = os.path.join(HERE, "fetch_patents_unresolved.json")


def _load(path):
    if not os.path.exists(path):
        return None
    return json.load(io.open(path, encoding="utf-8"))


# --------------------------------------------------------------------------
# ATTRIBUTION
# --------------------------------------------------------------------------
def test_alias_is_not_folded_into_a_weaker_alias():
    """fold() was applied to the alias too, so "Diehl Defence" became "diehl".

    A one-token alias then falls under the rule that every leftover be geographic,
    and "defence" is not a place -- so the alias the author wrote out precisely
    because the brand alone is too weak was replaced by the brand alone and refused.
    """
    for applicant, cid in [
            ("DIEHL DEFENCE GMBH & CO KG", "rheinmetall"),
            ("Diehl Defence GmbH & Co. KG", "rheinmetall"),
            ("ELBIT SYSTEMS OF AMERICA, LLC", "elbit-systems"),
            ("ISRAEL WEAPON INDUSTRIES (I.W.I.) LTD.", "iwi")]:
        assert M.resolve(applicant)[0] == cid, applicant


def test_ampersand_does_not_split_an_alias():
    """"&" folds to the word "and", which sat between two alias tokens and broke
    the run the containment test looks for."""
    for s in ["BAE Systems Land & Armaments L.P.",
              "BAE SYSTEMS LAND & ARMAMENTS L.P.",
              "BAE Systems Land &; Armaments L.P.",
              "BAE Systems Land and Armaments LP"]:
        assert M.resolve(s)[0] == "bae-systems", s


def test_thirty_character_truncation_still_resolves():
    """WIPO's uppercase applicant index cuts at 30 characters. No alias can equal a
    cut-off string, so the tail is allowed to be a PREFIX of a noise word."""
    assert len("KRAUSS MAFFEI WEGMANN GMBH & C") == 30
    assert M.resolve("KRAUSS MAFFEI WEGMANN GMBH & C")[0] == "knds"
    assert M.resolve("SAAB BOFORS DYNAMICS SWITZERLA")[0] == "saab"
    assert M.resolve("OTOKAR OTOBUES KAROSERI SANAYI")[0] == "otokar"


def test_truncation_is_not_a_licence_to_guess():
    """Only a LEFTOVER may be forgiven, and only against places and legal forms."""
    assert M.resolve("KRAUSS MAFFEI WEGMANN GMBH & CATERPILLAR")[0] is None
    assert M.resolve("SAAB BOFORS DYNAMICS SWITZERBLAD SYSTEMS")[0] is None


def test_the_refusals_that_must_survive_every_loosening():
    """Each of these is a real, unrelated company or a person."""
    for s in ["Elbit Imaging Ltd", "Adani Green Energy Limited", "Saab Automobile AB",
              "Rafael Gomez", "Mark A. Skidmore", "Robert Willhelm",
              "General Dynamics , Pomona Division", "LEONARDO S.P.A.",
              "HUTA STALOWA WOLA SPOLKA AKCYJNA", "ELBIT SYSTEMS C4I AND CYBER LTD.",
              "NO.213 INSTITUTE OF CHINA NORTH INDUSTRIES GROUP CORPORATION",
              "Some Unlisted Kabushiki Kaisha", ""]:
        assert M.resolve(s)[0] is None, s


def test_stored_rows_keep_the_owner_they_were_stored_under():
    """THE REGRESSION THAT MATTERS. A looser resolver that re-attributes a stored
    row silently rewrites history, and regate() would then DROP every row whose
    answer moved. Run against the real ledger, not a fixture."""
    rows = _load(LEDGER)
    if not rows:
        return
    moved = [(r["assignee"], r["comp_id"], M.resolve(r["assignee"])[0])
             for r in rows
             if M.resolve(r["assignee"])[0] != r["comp_id"]]
    assert not moved, moved[:5]


def test_the_drop_list_is_measurably_smaller():
    """The proposal file records what the harvest refused to attribute. 335 of its
    613 publications are correctly-owned records the folding faults threw away."""
    drops = _load(DROPS)
    if not drops:
        return
    recovered = sum(d["n"] for d in drops if M.resolve(d["applicant"])[0])
    assert recovered >= 300, recovered


# --------------------------------------------------------------------------
# PARSING
# --------------------------------------------------------------------------
def test_the_result_row_yields_the_docid_and_the_abstract():
    got = M.parse_results(M.RESULT_ROW_FIXTURE)
    assert len(got) == 1
    r = got[0]
    assert r["doc_id"] == "PH290880599"
    assert r["no"] == "1/2018/000299"
    assert r["country"] == "PH" and r["pub_date"] == "09.03.2020"
    assert r["applicant"] == "POONGSAN CORPORATION"
    assert r["abstract"].startswith("The present invention relates")
    assert "docId=PH290880599" in r["detail_href"]


def test_the_registry_prints_its_own_total():
    """10 rows came back; the page said 60. The harvest read neither."""
    assert M.parse_total(M.RESULT_ROW_FIXTURE) == 60
    assert M.parse_total("<html>no count here</html>") is None


def test_ipc_subgroup_is_six_digits_not_two():
    """sym[8:10] turned F42B 1/032 into F42B 1/03 -- a real, different subgroup."""
    assert M.ipc_symbol("F42B0001032000") == "F42B 1/032"
    assert M.ipc_symbol("F42B0033020700") == "F42B 33/0207"
    assert M.ipc_symbol("F42B0005000000") == "F42B 5/00"
    assert M.ipc_symbol("F41A0009100000") == "F41A 9/10"
    assert M.ipc_symbol("F41H0005040000") == "F41H 5/04"


def test_detail_fields_and_the_reload_shell():
    d = M.parse_detail(M.DETAIL_FIXTURE)
    assert d["Application Date"] == "05.10.2018"
    assert d["Publication Date"] == "09.03.2020"
    assert d["Grant Number"] == "1/2018/000299"
    assert d["Grant Date"] == "28.04.2023"
    assert d["Publication Kind"] == "B1"
    shell = ("<html><body>Processing<script>setTimeout(function(){location.reload();}"
             ", 0);</script></body></html>")
    assert M.parse_detail(shell) == {}
    assert M.parse_detail("") == {}


# --------------------------------------------------------------------------
# THE THREE STATES
# --------------------------------------------------------------------------
def _row(**kw):
    base = {"comp_id": "poongsan", "no": "1020180041275", "ipc": ["F42B 5/00"],
            "title": "A real title", "pub_date": "17.04.2018", "country": "KR",
            "applicant": "POONGSAN CORPORATION", "doc_id": "KR217798612"}
    base.update(kw)
    return base


def test_unknown_is_a_state_and_not_a_default():
    """status='filed', granted=None was written for all 1,157 rows without asking.
    Of three records sampled live, all three were GRANTED."""
    (row,), _ = M.gate([_row()])
    assert row["status"] == M.ST_UNKNOWN
    assert row["filed"] is None
    assert row["granted"] is None
    assert row["published"] == "2018-04-17"


def test_granted_is_recorded_with_its_date_and_number():
    (row,), _ = M.gate([_row(detail={
        "Application Date": "21.08.2018", "Grant Number": "10254091",
        "Grant Date": "09.04.2019", "Publication Kind": "B2"})])
    assert row["status"] == M.ST_GRANTED
    assert row["granted"] == "2019-04-09"
    assert row["grant_no"] == "10254091"
    assert row["pub_kind"] == "B2"
    assert row["filed"] == "2018-08-21"


def test_filed_means_the_registry_was_asked_and_said_no_grant():
    (row,), _ = M.gate([_row(detail={"Application Date": "21.08.2018",
                                     "Publication Kind": "A1"})])
    assert row["status"] == M.ST_FILED
    assert row["granted"] is None
    assert row["filed"] == "2018-08-21"


def test_filed_is_never_the_publication_date():
    """Measured error up to +2.5 years, rendered in the UI as "Filed <date>"."""
    (row,), _ = M.gate([_row(pub_date="09.03.2020",
                             detail={"Application Date": "05.10.2018"})])
    assert row["filed"] == "2018-10-05"
    assert row["published"] == "2020-03-09"
    assert row["filed"] != row["published"]


def test_the_link_is_the_record():
    """result.jsf?query=FP:(2010239639) is a full-text search for a bare number: of
    14 stored links resolved live, 12 did not return the record."""
    (row,), _ = M.gate([_row()])
    assert row["url"] == M.DETAIL_URL % "KR217798612"
    assert "FP" not in row["url"]
    assert M.record_url({"doc_id": ""}) is None


# --------------------------------------------------------------------------
# DEDUP
# --------------------------------------------------------------------------
def test_the_dedup_keeper_is_the_grant():
    """The old test was a kind code on the publication number, and no number the
    parser produces carries one -- so the keeper was always the earliest
    publication, systematically the application rather than the grant."""
    fam = [_row(no="1/2018/000299", pub_date="09.03.2020", country="PH",
                doc_id="PH290880599", title="Detonator assembly"),
           _row(no="3312545", pub_date="25.04.2018", country="EP",
                doc_id="EP215066611", title="Detonator assembly"),
           _row(no="20180364015", pub_date="20.12.2018", country="US",
                doc_id="US235210071", title="Detonator assembly",
                detail={"Grant Number": "10254091", "Grant Date": "09.04.2019"})]
    kept, refusals = M.gate(fam)
    assert len(kept) == 1
    assert kept[0]["no"] == "20180364015"
    assert kept[0]["status"] == M.ST_GRANTED
    assert len(refusals["same invention, another office"]) == 2


def test_no_stored_number_carries_a_kind_code():
    """The premise of the old keeper test, checked against the corpus it ran on."""
    rows = _load(LEDGER)
    if not rows:
        return
    import re
    coded = [r["no"] for r in rows if re.search(r"[AB]\d?$", r["no"])]
    assert not coded, coded[:5]


# --------------------------------------------------------------------------
# WRITING
# --------------------------------------------------------------------------
def test_an_empty_write_is_refused():
    """write_db DELETEs the whole pipeline range before it inserts, so write_db([])
    deletes the entire tab. The caller's guard ran only when the run was non-empty."""
    try:
        M.write_db([])
    except SystemExit as e:
        assert "0 rows" in str(e)
        return
    raise AssertionError("write_db([]) did not refuse")


def test_repair_ledger_moves_the_date_it_never_measured():
    old = [{"no": "2010239639", "filed": "2011-09-08", "status": "filed",
            "granted": None,
            "url": "https://patentscope.wipo.int/search/en/result.jsf?query=FP%3A%28"
                   "2010239639%29"}]
    fixed, changed = M.repair_ledger(old)
    assert changed == 1
    assert fixed[0]["published"] == "2011-09-08"
    assert fixed[0]["filed"] is None
    assert fixed[0]["status"] == M.ST_UNKNOWN
    assert fixed[0]["url"] is None
    assert M.repair_ledger(fixed)[1] == 0


def test_the_gate_still_refuses_what_it_always_refused():
    invented, _ = M.gate([_row(no="IN-2024-EST01")])
    assert not invented
    unowned, ref = M.gate([_row(comp_id=None)])
    assert not unowned and "owner not on the roster" in ref
    toy, _ = M.gate([_row(ipc=["F41B 11/00", "F41A 9/00"])])
    assert not toy


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  PASS  %s" % name)
        except Exception as e:
            fails += 1
            print("  FAIL  %s: %s" % (name, e))
    print("\n%s" % ("all passed" if not fails else "%d FAILED" % fails))
    sys.exit(1 if fails else 0)
