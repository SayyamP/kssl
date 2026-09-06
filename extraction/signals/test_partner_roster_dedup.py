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
        src = open(f).read()
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
        for d in re.findall(r'DELETE FROM serving\.partner WHERE ([^"]+)', open(f).read()):
            assert "origin='pipeline'" in d and "ord" in d, (
                f + ": DELETE is not scoped to this writer's own rows: " + d.strip())
        print("  ok   %-22s deletes only its own range" % f)


def test_head_org_is_the_shared_identity():
    # Both writers must compare on the same notion of "which company is this",
    # or one of them dedups on a string the other does not recognise.
    assert roster.head_org("Israel Aerospace Industries (IAI)") == "Israel Aerospace Industries (IAI)"
    assert roster.head_org("IndianOil & ReNew Power") == "IndianOil"
    assert roster.head_org("GE Aviation (CFM International)") == "GE Aviation"
    for f in FILES:
        assert "head_org" in open(f).read(), f + ": does not compare on head_org"
    print("  ok   both writers compare on roster.head_org")


if __name__ == "__main__":
    test_each_writer_checks_rows_it_does_not_own()
    test_delete_stays_scoped_to_its_own_rows()
    test_head_org_is_the_shared_identity()
    print("ok - one roster row per company, in both writers")
    sys.exit(0)
