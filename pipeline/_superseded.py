"""Refuse to run a copy that a newer one has replaced.

    from _superseded import refuse_if_superseded
    refuse_if_superseded(__file__)

Ten modules exist under BOTH pipeline/ and extraction/signals/, and they have drifted
apart badly: enrich_serving by 2,591 lines, serving_fill by 1,416. The extraction/
copies are the ones the containers run; these are the originals, left behind.

That would be harmless if the difference were obvious. It is not. revive_partners
differs by THREE lines, and one of them is the bug:

    pipeline/    VALUES (...,'[]'::jsonb,...)      <- an empty array
    extraction/  VALUES (...,NULL,...)             <- carried forward instead

carry_restore is a COALESCE, so it fills a column the rebuild left NULL and never
overwrites one it filled. '[]' is not NULL. The old copy therefore beats the carried
value and DROPS every partner tie on the rows it writes -- which is the defect the
extraction copy was changed to fix. The old copy still has it, and CI rsyncs the whole
tree, so it is sitting on the production box right now, one `python3` away from a
partner wipe.

Deleting these would be tidier and is not this module's call to make: something may
still reference them. Refusing to run against a database is enough, and it fails in
the one direction that matters -- loudly, before anything is written.

KSSL_ALLOW_SUPERSEDED=1 overrides, for the case where someone genuinely wants the old
behaviour and knows why.
"""
import os
import sys
from pathlib import Path


def refuse_if_superseded(this_file, sibling="extraction/signals"):
    if os.environ.get("KSSL_ALLOW_SUPERSEDED") == "1":
        return
    here = Path(this_file).resolve()
    newer = here.parent.parent / sibling / here.name
    if not newer.exists():
        return
    try:
        same = newer.read_bytes() == here.read_bytes()
    except OSError:
        return
    if same:
        return
    print(
        "REFUSING TO RUN: %s has been superseded by %s, and the two have diverged.\n"
        "\n"
        "  this copy : %d lines\n"
        "  the live  : %d lines\n"
        "\n"
        "The containers run the extraction/signals copy. This one is the original and\n"
        "is kept only for reference; at least one of these pairs differs by a handful\n"
        "of lines where the older copy still writes '[]' into a column the newer one\n"
        "leaves NULL, which silently drops every carried partner tie.\n"
        "\n"
        "Run the live copy instead:\n"
        "    python3 %s\n"
        "\n"
        "Set KSSL_ALLOW_SUPERSEDED=1 if you genuinely want this older behaviour."
        % (here.name, newer, len(here.read_text().splitlines()),
           len(newer.read_text().splitlines()), newer),
        file=sys.stderr, flush=True)
    raise SystemExit(2)
