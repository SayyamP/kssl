"""Read the status a tie already states in its own words, for the rows no model wrote.

    python backfill_tie_status.py            # dry run
    python backfill_tie_status.py --apply
    python backfill_tie_status.py --demo

step_partnerships stamps `status` and `ended` on every tie it writes. The ties that
predate it -- 18 hand-written and revived rows on staging -- carry neither, and the
enrichment never revisits them: `partners` is a carried column, so they survive every
rebuild exactly as they are. Their state is not missing, though. It is sitting in the
label: "Historical Joint Venture (Ended 2013)" says both that it is over and when, and
the graph drew it as a live edge anyway, because statusTag reads `status` and there
was none.

WHAT THIS DOES NOT DO IS STAMP `active`. These rows have no date of any kind -- `date`
is "n/d" or empty on all 18 -- so there is nothing to support a claim of currency, and
`statusTag` renders no tag at all for a tie with neither status nor as_of. That is the
honest output. This only reads back what the text already asserts:

    ended      historical / former / lapsed / terminated / dissolved / "(Ended 2013)"
    announced  proposed / planned / prospective -- an intention, not a relationship

THE YEAR MUST BE ADJACENT TO THE END WORD. "Historical JV (established 2007 as JML,
now JCBL South)" is a live company whose first 4-digit number is its FOUNDING year;
taking the first year in the string would publish "ended 2007" about a going concern.

Idempotent: a tie that already has `status` is never touched, so this can run every
enrich cycle and only ever reaches rows nothing else has typed.
"""
import argparse
import json
import os
import re
import sys

import psycopg2

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# "historic" catches historical/historically; "former" catches formerly. `\b` on each
# so "planned" does not fire on "plant" and "ended" does not fire on "extended".
ENDED_RX = re.compile(
    r"\b(?:historic\w*|former\w*|lapsed|ended|terminated|dissolved|defunct|"
    r"wound[- ]?up|discontinued|ex-)\b", re.I)
# The year only counts where the text ties it to the ending.
ENDED_YEAR_RX = re.compile(
    r"\b(?:ended|until|till|through|to)\s*:?\s*((?:19|20)\d{2})\b", re.I)
PLANNED_RX = re.compile(r"\b(?:proposed|planned|prospective|intended|"
                        r"under discussion|in talks|to explore)\b", re.I)
# "MoU to explore a JV" is an announced JV; "restructured" is not an ending.
LIVE_RX = re.compile(r"\b(?:ongoing|current|active|continu\w+)\b", re.I)


def read_status(ptype, note=""):
    """-> (status, ended_year) or (None, None) when the text says nothing.

    ptype is the authority; the note is only consulted for the year, because a note
    is prose about the relationship and mentions dates that are not endings."""
    txt = " ".join(x for x in (ptype, note) if x)
    if not (ptype or "").strip():
        return None, None
    if LIVE_RX.search(ptype) and not ENDED_RX.search(ptype):
        return None, None                       # says it is live; we have no date, so no claim
    if ENDED_RX.search(ptype):
        m = ENDED_YEAR_RX.search(ptype) or ENDED_YEAR_RX.search(note or "")
        return "ended", (m.group(1) if m else None)
    if PLANNED_RX.search(ptype) or PLANNED_RX.search(note or ""):
        return "announced", None
    return None, None


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("""SELECT comp_id, name, partners FROM serving.competitors
                    WHERE partners IS NOT NULL AND jsonb_array_length(partners) > 0
                    ORDER BY comp_id""")
    rows = cur.fetchall()
    hits, scanned, untyped = [], 0, 0
    changed = []
    for cid, name, partners in rows:
        pl = partners if isinstance(partners, list) else json.loads(partners or "[]")
        touched = False
        for p in pl:
            if p.get("status"):
                continue                        # already typed: never overwrite
            scanned += 1
            st, yr = read_status(p.get("ptype") or "", p.get("note") or "")
            if not st:
                untyped += 1
                continue
            p["status"] = st
            if yr:
                p["ended"] = yr
            touched = True
            hits.append((name, p.get("label") or "", p.get("ptype") or "", st, yr or "-"))
        if touched:
            changed.append((cid, pl))

    print("%d untyped tie(s) scanned, %d given a status from their own text, "
          "%d left alone (nothing in the text says)" % (scanned, len(hits), untyped))
    for name, label, ptype, st, yr in hits:
        print("  %-20s %-40s %-9s %-5s  <- %s" % (name[:20], label[:40], st, yr, ptype[:52]))

    if apply:
        for cid, pl in changed:
            cur.execute("""UPDATE serving.competitors SET partners=%s, updated_at=now()
                            WHERE comp_id=%s""", (json.dumps(pl), cid))
        con.commit()
        print("\napplied to %d competitor row(s)." % len(changed))
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return len(hits)


def _demo():
    # THE ROW THIS EXISTS FOR: Mahindra/BAE, drawn as a live JV under a label that
    # says it ended in 2013.
    assert read_status("Historical Joint Venture (Ended 2013)") == ("ended", "2013")
    assert read_status("Historical Joint Venture") == ("ended", None)
    assert read_status("Joint Venture (Historic/Restructured)") == ("ended", None)

    # A FOUNDING YEAR IS NOT AN END YEAR. This note belongs to a going concern; the
    # first four-digit number in it is when the JV was established.
    assert read_status("Historical JV",
                       "Historical JV (established 2007 as JML, now JCBL South) for "
                       "manufacturing tippers") == ("ended", None), \
        "2007 is when it started -- publishing 'ended 2007' would be a false claim"
    # ...but a year the text ties to the ending is taken, from the note too.
    assert read_status("Historical JV", "ran until 2016") == ("ended", "2016")

    # an intention is not a relationship
    assert read_status("MoU / Planned JV") == ("announced", None)
    assert read_status("Joint Venture (proposed)") == ("announced", None)
    assert read_status("MoU; Proposed Joint Venture; Technology Collaboration")[0] == "announced"
    assert read_status("MoU", "MoU to explore JV for manufacturing")[0] == "announced"

    # THE DEFAULT IS SILENCE. These rows carry no date, so nothing here may claim a
    # tie is live -- statusTag prints no tag at all, which is the honest render.
    assert read_status("Joint Venture (51% Mahindra, 49% Telephonics)") == (None, None)
    assert read_status("Strategic Partnership") == (None, None)
    assert read_status("Memorandum of Understanding") == (None, None)
    assert read_status("Supply agreement", "supplies radars to the Indian Navy") == (None, None)
    assert read_status("") == (None, None)

    # WORD BOUNDARIES. These are the substring false-positives: a plant is not a plan,
    # an extended contract has not ended, a formerly-named partner is not a former one.
    assert read_status("Manufacturing plant partnership") == (None, None)
    assert read_status("Extended supply contract") == (None, None)
    assert read_status("Distribution / reseller") == (None, None)
    # "Historical" wins over "ongoing" only when both are present in the type itself
    assert read_status("Ongoing supply agreement") == (None, None)
    assert read_status("Historical JV, ongoing supply")[0] == "ended"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
