"""One roster row per company -- in every writer that inserts into serving.partner.

This is a regression test for a fix that was applied to the wrong module. Production
showed "Paramount Group", "Israel Aerospace Industries (IAI)" and "Thales" twice on the
Partnerships tab. revive_partners.py carried the comment naming that exact failure
("or the tab shows Paramount twice"), so its duplicate check was fixed there -- and the
duplicates stayed, because those rows were never its rows. ord 1001-1009 is
enrich_serving's range; the same fault lived in the other writer, untouched.

serving.partner has two pipeline writers with disjoint ord ranges and a set of curated
reference rows that neither owns. Each writer must DELETE only its own rows and CHECK
against every row, including the ones it may not delete. Scoping the check the same way
as the delete is the bug, and it is invisible in the module where it occurs -- the rows
it fails to see were written by something else.
"""
import re
import sys

import roster

FILES = ("revive_partners.py", "enrich_serving.py")


def dedup_selects(src):
    """Every SELECT of serving.partner labels used as a duplicate check."""
    return re.findall(r'SELECT\s+label\s+FROM\s+serving\.partner\s+WHERE\s+([^"]+)', src)


def test_each_writer_checks_rows_it_does_not_own():
    for f in FILES:
        src = open(f, encoding="utf-8").read()
        wheres = dedup_selects(src)
        assert wheres, f + ": no duplicate check against serving.partner at all"
        for w in wheres:
            assert "origin <> 'pipeline'" in w, (
                f + ": the duplicate check is scoped to " + w.strip() + " -- reference "
                "rows are invisible to it, so a curated company gets a second row")
        print("  ok   %-22s checks beyond its own origin" % f)


def test_delete_stays_scoped_to_its_own_rows():
    # The other half: a check that widens must not drag the DELETE with it, or one
    # writer erases the other's roster (or the curated reference rows) every pass.
    for f in FILES:
        for d in re.findall(r'DELETE FROM serving\.partner WHERE ([^"]+)', open(f, encoding="utf-8").read()):
            assert "origin='pipeline'" in d and "ord" in d, (
                f + ": DELETE is not scoped to this writer's own rows: " + d.strip())
        print("  ok   %-22s deletes only its own range" % f)


# discover_ties reads the roster to decide which names are already known. It writes
# nothing to serving.partner (DISC_ORD0 is a reserved range, unused), so it is not
# subject to the delete/check rule -- but it must ask the same question of the same
# table, unscoped, or a name known only as reference data reads as unknown.
READERS = ("discover_ties.py",)


def test_readers_of_the_roster_are_not_scoped_either():
    for f in READERS:
        src = open(f, encoding="utf-8").read()
        assert re.search(r'SELECT label FROM serving\.partner"', src), (
            f + ": its roster read is scoped or absent; it must see every row")
        assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+serving\.partner", src), (
            f + ": it writes to serving.partner now, so it belongs in FILES, "
            "under the delete/check rule")
        print("  ok   %-22s reads every row, writes none" % f)


def test_head_org_is_the_shared_identity():
    # Both writers must compare on the same notion of "which company is this",
    # or one of them dedups on a string the other does not recognise.
    assert roster.head_org("Israel Aerospace Industries (IAI)") == "Israel Aerospace Industries (IAI)"
    assert roster.head_org("IndianOil & ReNew Power") == "IndianOil"
    assert roster.head_org("GE Aviation (CFM International)") == "GE Aviation"
    # ...and it must be ONE function, not a copy per module. Asserted on the function
    # object rather than on import syntax: discover_ties reaches it through
    # revive_partners, and pipeline/ has no roster.py, so requiring a direct import
    # would break a duplicate this fix has no business touching. What matters is that
    # every module normalises identity the same way, which `is` proves and grep cannot.
    import revive_partners
    import discover_ties
    for mod in (revive_partners, discover_ties):
        assert mod.head_org is roster.head_org, (
            mod.__name__ + ": has its own head_org; two writers then disagree about "
            "which company a label names, and the duplicate check misses")
    # enrich_serving reaches it by attribute, so identity is structural there.
    assert "roster.head_org" in open("enrich_serving.py", encoding="utf-8").read(), (
        "enrich_serving.py: does not compare on roster.head_org")
    print("  ok   head_org is one function, shared by every roster user")


if __name__ == "__main__":
    test_each_writer_checks_rows_it_does_not_own()
    test_delete_stays_scoped_to_its_own_rows()
    test_readers_of_the_roster_are_not_scoped_either()
    test_head_org_is_the_shared_identity()
    print("ok - one roster row per company, in both writers")
    sys.exit(0)
