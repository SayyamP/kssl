"""The pipeline finds its own empty columns and goes and gets the documents.

    python3 backfill_gaps.py                 # report: which competitor lacks what
    python3 backfill_gaps.py --apply         # ...and queue DC documents that answer it
    python3 backfill_gaps.py --demo          # offline self-check

WHY THIS EXISTS. Every missing-data ticket on the Competitor tab has been worked the
same way by hand: notice a column is empty, grep the DC corpus for documents that would
fill it, queue those documents, wait for extraction, then write the signal. That is four
manual steps repeated per field, and the first one -- noticing -- only happens when
somebody files a ticket. Revenue sat at 0 for months. `leadership` sat at 0 of 43 from
the day the column was created until it was asked about.

The per-field JUDGEMENT cannot be generalised and should not be: what counts as a
founding year, an annual revenue or a sitting officer is the entire value of
fill_founded, fill_revenue and fill_leadership, and each is a different question. What
CAN be generalised is everything around it -- which competitor is missing which column,
which corpus documents plausibly speak to it, and getting those documents into
extraction. That loop is this file, and it runs every feeder cycle.

THE ARCHITECTURAL RULE IT OBEYS. A fact is never lifted out of `public.documents`. The
document is ENQUEUED, extracted into propositions with their evidence, and only then
read by a signal -- so every value on the dashboard carries a source, and survives the
next rebuild. See select_worklist.enqueue_ids, which says the same thing.

WHAT IT COSTS. `public.documents` has no text index, so this is a sequential scan of the
corpus however it is written. It is therefore ONE scan for ALL gaps -- every field's
probe and every gapped competitor's name in a single predicate, sorted out in Python --
and it is rate-limited to once every EVERY_HOURS on a marker table it owns.
"""
import argparse
import datetime
import html
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "signals"))

DEST_DSN = os.environ.get("KSSL_DSN", "")
SRC_DSN = os.environ.get("KSSL_CORPUS_SRC_DSN", "")

# The lane a gap-filling document enters at. P1 is the front of the queue: a document
# fetched BECAUSE a published column is empty is worth more than the next crawl batch,
# and the queue is drained in `class` order.
LANE = int(os.environ.get("KSSL_GAP_LANE", "1"))
# Per (competitor, field). Enough to give the signal several independent sources to
# agree on; small enough that 20 gaps do not become a 10,000-document queue.
PER_GAP = int(os.environ.get("KSSL_GAP_DOCS", "40"))
EVERY_HOURS = float(os.environ.get("KSSL_GAP_EVERY_H", "12"))

# (column, "is empty" predicate, words a document must contain to plausibly answer it)
#
# The probe is deliberately WIDER than the signal that will read the document: its job
# is to decide what is worth extracting, not what is true. A document that says
# "employs 4,200 people" is worth extracting for company_size even if the sentence
# turns out to be about a subsidiary -- that judgement belongs to the signal, which can
# see the parsed proposition and its evidence, not to a corpus grep.
FIELDS = [
    ("leadership", "leadership IS NULL OR leadership::text IN ('null', '[]')",
     r"chief executive|\mCEO\M|chairman|chairperson|managing director"
     r"|board of directors|chief financial officer|\mCFO\M"),
    ("company_size", "company_size IS NULL OR company_size = ''",
     r"employees|employs|headcount|workforce|staff of|personnel strength"),
    ("sales", "sales IS NULL OR sales::text IN ('null', '[]')",
     r"annual revenue|revenues? of|turnover of|net sales of|posted revenues?"
     r"|reported revenues?|full[- ]year sales"),
    ("starting_year", "starting_year IS NULL",
     r"was founded|were founded|was established|was incorporated|was formed"
     r"|founded in|established in|incorporated in|since its founding"),
    ("hq", "hq IS NULL OR hq = ''",
     r"headquarter|head office|headquartered|based in"),
    ("global_locations",
     "global_locations IS NULL OR global_locations::text IN ('null', '[]')",
     r"subsidiar|facilities in|operations in|offices in|plants? in|sites? in"
     r"|presence in|manufacturing in"),
]

MARKER = """CREATE TABLE IF NOT EXISTS serving.gap_scan (
              field   text PRIMARY KEY,
              ran_at  timestamptz NOT NULL)"""


def gaps(cur):
    """[(field, comp_id, name)] -- every SHOWN competitor missing every declared column.

    `serving_live.competitors` and not `serving.competitors`: the table holds the same
    company more than once (`BRAHMOS` and `brahmos-aerospace`), and a column that is
    empty on a row nobody can see is not a gap anyone has.
    """
    out = []
    for field, empty, _probe in FIELDS:
        cur.execute("SELECT comp_id, name FROM serving_live.competitors "
                    "WHERE (%s) AND name <> ''" % empty)
        out.extend((field, cid, html.unescape(n)) for cid, n in cur.fetchall())
    return out


def due(cur, fields, every_hours=EVERY_HOURS):
    """The subset of `fields` whose last scan is older than `every_hours`.

    A corpus-wide sequential scan on a database this pipeline shares is not something
    to run every ten minutes because a feeder loop happens to tick.
    """
    cur.execute(MARKER)
    cur.execute("SELECT field, ran_at FROM serving.gap_scan")
    seen = dict(cur.fetchall())
    now = datetime.datetime.now(datetime.timezone.utc)
    return [f for f in fields
            if f not in seen
            or (now - seen[f]).total_seconds() >= every_hours * 3600]


def probe_sql(fields):
    """One regex covering every due field's probe words."""
    return "|".join("(?:%s)" % p for f, _e, p in FIELDS if f in fields)


# Postgres `~*` is POSIX ERE, where `re.escape`'s backslash-space is not defined
# behaviour. Only the characters that are actually metacharacters get escaped.
_META = re.compile(r"([.^$*+?()\[\]{}|\\])")


def name_sql(names):
    """One regex covering every gapped competitor's name, longest first."""
    uniq = sorted({n for n in names if len(n) >= 4}, key=len, reverse=True)
    return "|".join(_META.sub(r"\\\1", n) for n in uniq)


def wanted(text, want, per_gap=PER_GAP, taken=None):
    """Which (field, comp_id) pairs this document could answer.

    `want` is [(field, comp_id, name regex, probe regex)]. A document counts for a gap
    only if it names the company AND says something about that field -- the two
    predicates that got it off the corpus, re-checked per pair, because one document
    matching "employees" and another matching "Rheinmetall" both satisfy the query.
    """
    taken = taken if taken is not None else {}
    hit = []
    for field, cid, name_rx, probe_rx in want:
        if taken.get((field, cid), 0) >= per_gap:
            continue
        if name_rx.search(text) and probe_rx.search(text):
            hit.append((field, cid))
    return hit


def run(apply=False, every_hours=EVERY_HOURS, limit_docs=200000):
    import psycopg2
    import select_worklist

    dest = psycopg2.connect(DEST_DSN, connect_timeout=15)
    dcur = dest.cursor()
    holes = gaps(dcur)
    if not holes:
        print("gaps: every declared column is filled on every shown competitor",
              flush=True)
        return {"gaps": 0, "queued": 0}

    by_field = {}
    for field, cid, name in holes:
        by_field.setdefault(field, []).append((cid, name))
    for field in sorted(by_field):
        print("gaps: %-17s %2d competitor(s): %s"
              % (field, len(by_field[field]),
                 ", ".join(n for _c, n in by_field[field])[:110]), flush=True)

    fields = due(dcur, list(by_field), every_hours)
    dest.commit()
    skipped = sorted(set(by_field) - set(fields))
    if skipped:
        print("gaps: %s scanned within the last %gh -- not rescanning"
              % (", ".join(skipped), every_hours), flush=True)
    if not fields:
        return {"gaps": len(holes), "queued": 0}
    if not apply:
        print("dry run: nothing scanned or queued (pass --apply)", flush=True)
        return {"gaps": len(holes), "queued": 0}

    want = [(f, cid, re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)", re.I),
             re.compile(dict((x[0], x[2]) for x in FIELDS)[f].replace(r"\m", r"\b")
                        .replace(r"\M", r"\b"), re.I))
            for f, cid, n in holes if f in fields]
    names = name_sql([n for f, _c, n in holes if f in fields])
    probes = probe_sql(fields)

    src = psycopg2.connect(SRC_DSN, connect_timeout=20)
    scur = src.cursor(name="gapscan")      # server-side: do not buffer the corpus
    scur.itersize = 1000
    # BOTH PREDICATES SERVER-SIDE. The sequential scan happens either way -- there is no
    # text index -- but with the filter in the query only the matching rows cross the
    # wire, which is far kinder to a database this pipeline shares.
    scur.execute("""SELECT document_id, left(main_text, 60000)
                      FROM public.documents
                     WHERE main_text ~* %s AND main_text ~* %s
                     LIMIT %s""", (probes, names, limit_docs))

    taken, picked, n_docs = {}, {}, 0
    for did, text in scur:
        n_docs += 1
        if n_docs % 2000 == 0:
            print("  %d docs scanned, %d picked" % (n_docs, len(picked)), flush=True)
        for field, cid in wanted(text or "", want, PER_GAP, taken):
            taken[(field, cid)] = taken.get((field, cid), 0) + 1
            picked.setdefault(did, []).append((field, cid))
    scur.close()
    src.close()
    print("gaps: scanned %d corpus doc(s), %d answer a gap" % (n_docs, len(picked)),
          flush=True)

    queued, pulled = select_worklist.enqueue_ids(list(picked), LANE)
    print("gaps: queued %d document(s) at lane P%d (%d bodies pulled from the corpus)"
          % (queued, LANE, pulled), flush=True)
    dcur.execute("SET lock_timeout='30s'")
    for f in fields:
        dcur.execute("INSERT INTO serving.gap_scan(field, ran_at) VALUES (%s, now()) "
                     "ON CONFLICT (field) DO UPDATE SET ran_at = now()", (f,))
    dest.commit()
    dest.close()
    for (field, cid), n in sorted(taken.items()):
        print("  %-17s %-32s %d doc(s)" % (field, cid, n), flush=True)
    return {"gaps": len(holes), "queued": queued}


def _demo():
    want = [("leadership", "saab",
             re.compile(r"(?<!\w)Saab(?!\w)", re.I),
             re.compile(r"chief executive|\bCEO\b", re.I)),
            ("company_size", "saab",
             re.compile(r"(?<!\w)Saab(?!\w)", re.I),
             re.compile(r"employees|employs", re.I))]

    # Names the company and speaks to one field: that field only.
    got = wanted("Saab appointed a new chief executive this week.", want)
    assert got == [("leadership", "saab")], got
    # Speaks to a field but names nobody in the roster -- the corpus query matched it on
    # the OTHER half of the predicate, which is why the pair is re-checked here.
    assert wanted("The company employs 4,200 people.", want) == []
    # Names the company but says nothing about either field.
    assert wanted("Saab delivered two Gripen aircraft.", want) == []
    # Both fields at once is two gaps answered by one document.
    got = wanted("Saab employs 28,000 people; its CEO said so.", want)
    assert len(got) == 2, got
    # The per-gap cap stops one company swallowing the queue.
    taken = {("leadership", "saab"): 40}
    assert wanted("Saab's chief executive said", want, 40, taken) == []

    assert probe_sql(["company_size"]).count("employees") == 1
    assert name_sql(["Saab", "BAE Systems", "ab"]) == "BAE Systems|Saab", \
        name_sql(["Saab", "BAE Systems", "ab"])
    assert name_sql(["Larsen & Toubro (L&T)"]) == "Larsen & Toubro \\(L&T\\)", \
        name_sql(["Larsen & Toubro (L&T)"])
    print("backfill_gaps: demo ok", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--every-hours", type=float, default=EVERY_HOURS)
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(apply=a.apply, every_hours=a.every_hours)
