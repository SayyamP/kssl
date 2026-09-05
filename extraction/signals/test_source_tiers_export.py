"""Every script in this directory must be importable.

    python test_source_tiers_export.py          (no database, no model)

THE BUG THIS PINS. There are two files called source_tiers.py:

    signals/source_tiers.py   the TRUST TIER table -- how much a claim weighs
    engine/source_tiers.py    the PUBLISHABILITY rule -- maker / government / two
                              independent domains; owns `domain` and `publishable`

Five scripts here wrote `from source_tiers import domain, publishable`. From this
directory that resolves to the first file, which has neither name, so discover_geo.py,
revive_geo.py, discover_ties.py, revive_partners.py and mark_shared.py raised ImportError
on the FIRST LINE -- in the deployed image included. They were not broken subtly; they
could not start. The geo footprint fill was scheduled to run on 2026-09-05 and could not.

Nothing caught it because CI runs `test_*.py` and a handful of named `--demo` calls, and
none of those five is either. A script nobody imports is a script nobody notices is dead,
which is why this test asserts the humble thing: that each one imports.

The same collision was found twice before and worked around one file at a time
(revive_matchups.py and client_portfolio.py load the engine module by path). The fix
under test re-exports the rule from signals/source_tiers.py, so either import is correct.
"""
import importlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

bad = 0


def check(name, ok, detail=""):
    global bad
    if not ok:
        bad += 1
        print("  FAIL %s%s" % (name, ("\n    " + detail) if detail else ""))


# --- the re-export itself -----------------------------------------------------------
import source_tiers                                                  # noqa: E402

check("signals/source_tiers exposes the trust tier", hasattr(source_tiers, "tier_of"))
for fn in ("domain", "publishable"):
    check("...and re-exports the engine rule's %s()" % fn, hasattr(source_tiers, fn))

if hasattr(source_tiers, "domain"):
    # It must be the ENGINE's function, not a look-alike defined here.
    check("domain() is the engine's, and parses a URL",
          source_tiers.domain("https://www.baesystems.com/en/article") == "baesystems.com",
          repr(source_tiers.domain("https://www.baesystems.com/en/article")))

# --- and the five scripts that could not start --------------------------------------
# Import only. What each does is covered by its own --demo; the point here is that the
# module body runs at all.
for mod in ("discover_geo", "revive_geo", "discover_ties", "revive_partners",
            "mark_shared", "revive_matchups", "client_portfolio"):
    try:
        importlib.import_module(mod)
        ok, detail = True, ""
    except Exception:                                                 # noqa: BLE001
        ok, detail = False, traceback.format_exc().strip().splitlines()[-1]
    check("%s imports" % mod, ok, detail)

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - the trust table re-exports the publishability rule; all 7 scripts import")
