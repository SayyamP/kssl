"""A module that exists twice must be identical, or the older copy must refuse to run.

    python test_no_silent_duplicate.py        (no database, no network)

Ten modules exist under both pipeline/ and extraction/signals/. They have drifted:
enrich_serving by 2,591 lines, serving_fill by 1,416. The containers run the
extraction/signals copies; the pipeline/ ones are the originals.

Big differences are survivable because they are obvious. The dangerous case is the
small one. revive_partners differs by THREE lines, and one of them is a bug that was
found and fixed on one side only:

    pipeline/    VALUES (...,'[]'::jsonb,...)
    extraction/  VALUES (...,NULL,...)

carry_restore is a COALESCE: it fills a column the rebuild left NULL and never
overwrites one it filled. '[]' is not NULL, so the old copy beats the carried value
and drops every partner tie on the rows it writes. CI rsyncs the whole tree, so that
file sits on the production box.

This test does not demand the copies be merged -- that is a bigger decision. It demands
that a diverged copy cannot be run by accident. Either the bytes match, or the older
file calls refuse_if_superseded() before it imports anything else.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OLD, LIVE = ROOT / "pipeline", ROOT / "extraction" / "signals"


def main():
    if not OLD.is_dir():
        print("ok - no pipeline/ tree to compare against")
        return 0
    same, guarded, bad = [], [], []
    for live in sorted(LIVE.glob("*.py")):
        old = OLD / live.name
        if not old.exists():
            continue
        if old.read_bytes() == live.read_bytes():
            same.append(live.name)
            continue
        head = old.read_text(errors="replace")
        # THE RULE IS ABOUT DATA LOSS, NOT TIDINESS. A diverged module that cannot
        # reach a database cannot drop anything: pipeline/aliases.py and
        # pipeline/source_tiers.py are lookup tables with a self-check in __main__ and
        # no psycopg2 at all. Requiring a guard there would mean adding an import-time
        # SystemExit to a library, which breaks the very scripts that import it.
        # Divergence is only dangerous where it can write.
        if "psycopg2" not in head:
            same.append(live.name + " (no db access)")
            continue
        # the guard has to run BEFORE the module's own imports: pipeline/source_tiers
        # has itself drifted far enough that some of these files now fail at import,
        # and a guard placed after that never runs. That is luck, not safety.
        body = head.split("refuse_if_superseded(__file__)")[0] if "refuse_if_superseded(__file__)" in head else None
        if body is None:
            bad.append((live.name, "diverged and NOT guarded"))
        elif "\nimport psycopg2" in body or "\nfrom psycopg2" in body:
            bad.append((live.name, "guard runs after psycopg2 is imported"))
        else:
            guarded.append(live.name)
    print("  identical: %d   diverged-but-guarded: %d   unguarded: %d"
          % (len(same), len(guarded), len(bad)))
    for n in guarded:
        print("    guarded  pipeline/%s" % n)
    for n, why in bad:
        print("    FAIL     pipeline/%s -- %s" % (n, why))
    if bad:
        print("\nA diverged duplicate must refuse to run. Add, above every other import:\n"
              "    from _superseded import refuse_if_superseded\n"
              "    refuse_if_superseded(__file__)\n"
              "...or make the two copies identical.")
        return 1
    print("ok - no diverged duplicate can be run by accident")
    return 0


if __name__ == "__main__":
    sys.exit(main())
