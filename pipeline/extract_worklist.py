"""Which staged documents are worth extracting, and what each would populate.

    python extract_worklist.py
    python extract_worklist.py --demo

718 documents sit in pipeline/corpus and 668 of them have never been through
Layer A. They already do useful work -- revive_matchups grounds specification
values against their raw TEXT -- but every other surface on the dashboard
(Partnerships, Geo Footprint, Innovation Pipeline, Competitors, Tenders, the
signal cards) is built from PROPOSITIONS, so an unextracted document contributes
nothing to any of them.

Extraction is the expensive step, so this scores each document against the same
predicates the enrichment steps use to pick their own candidates, and ranks by
how many surfaces it could feed. A spec sheet fetched for Positioning is not the
same kind of document as a contract-award story, and the ranking says so instead
of leaving it to the order the files were written.
"""
import os
import argparse
import collections
import io
import json
import re
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from enrich_serving import PART_RX, PROCURE_EV_RX, RD_RX, SPEC_RX, TENDER_RX  # noqa: E402
from serving_fill import is_listing, load_terms                               # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
MIN_CHARS = 400
# Past this a page is a catalogue rather than a story, whatever its URL looks like.
INDEX_CHARS = 60000
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A country named next to a company is what geo_presence is built from.
GEO_RX = re.compile(
    r"\b(india|indian|united states|u\.s\.|america|france|french|germany|german|"
    r"poland|polish|turkey|turkish|t[uü]rkiye|israel|israeli|south korea|korean|"
    r"brazil|brazilian|south africa|saudi|uae|emirates|armenia|armenian|ukraine|"
    r"ukrainian|egypt|indonesia|philippines|vietnam|thailand|malaysia|nigeria|"
    r"morocco|qatar|kuwait|oman|australia|canada|japan|spain|italy|sweden|"
    r"finland|norway|netherlands|czech|slovak|romania|bulgaria|greece|hungary)\b",
    re.I)

SURFACES = (
    ("partnership", PART_RX, "Partnerships"),
    ("tender", PROCURE_EV_RX, "Tenders"),
    ("innovation", RD_RX, "Innovation Pipeline"),
    ("spec", SPEC_RX, "Positioning specs"),
    ("geo", GEO_RX, "Geo Footprint"),
)


def score_doc(rec, rel_rx, comp_rx):
    """-> dict of what this document could feed, or None if it can feed nothing."""
    text = rec.get("text") or ""
    if len(text) < MIN_CHARS:
        return None
    title = rec.get("title") or ""
    hay = ("%s\n%s" % (title, text))[:20000]
    hits = {k: bool(rx.search(hay)) for k, rx, _lbl in SURFACES}
    low = hay.lower()
    # Named organisations are what every surface except the spec table keys on.
    named = sum(1 for rx in comp_rx if rx.search(low))
    relevant = any(rx.search(low) for rx in rel_rx)
    n = sum(1 for v in hits.values() if v)
    if not relevant or not n:
        return None
    return {
        "document_id": rec.get("document_id"),
        "url": rec.get("url", ""),
        "title": title[:120],
        "chars": len(text),
        "surfaces": [k for k, v in hits.items() if v],
        "n_surfaces": n,
        "named_orgs": named,
        "listing": is_listing(rec.get("url", "")),
        # A story that names organisations AND covers several surfaces is worth an
        # extraction call; a bare specification table mostly re-states what
        # Positioning already grounds from its raw text.
        "score": n * 2 + min(named, 6) + (2 if hits["partnership"] or hits["tender"] else 0),
    }


def rank(r):
    """Value per unit of COST, not value alone.

    Extraction time is proportional to length -- the engine chunks the text -- and a
    long document trips every predicate simply by being long. Ranking on the raw
    score therefore put the most EXPENSIVE documents first: the top 40 had a median
    of 14,860 characters against 4,091 across the whole list, and 25 documents hold
    36% of all the text. "List of equipment of the Indian Army" is 164,693
    characters of table that yields almost no story.
    """
    v = r["score"] / (1.0 + r["chars"] / 8000.0)
    if r["chars"] > INDEX_CHARS:
        v *= 0.25          # a catalogue, whatever its URL looks like: last, not never
    return v


def build():
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SELECT document_id FROM extracted.document")
    done = {r[0] for r in cur.fetchall()}
    con.close()
    rel_rx, comp_rx = load_terms()
    rows, skipped = [], collections.Counter()
    for p in sorted((HERE / "corpus").glob("doc_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            skipped["unreadable"] += 1
            continue
        if rec.get("document_id") in done:
            skipped["already extracted"] += 1
            continue
        s = score_doc(rec, rel_rx, comp_rx)
        if s is None:
            skipped["nothing it could feed"] += 1
            continue
        if s["listing"]:
            skipped["listing page"] += 1
            continue
        rows.append(s)
    rows.sort(key=lambda r: (-rank(r), -r["named_orgs"]))
    return rows, skipped


def main():
    rows, skipped = build()
    print("%d staged document(s) worth extracting\n" % len(rows))
    per = collections.Counter()
    for r in rows:
        for s in r["surfaces"]:
            per[s] += 1
    print("what they could populate (a document can feed more than one):")
    for key, _rx, label in SURFACES:
        print("   %-22s %4d document(s)" % (label, per[key]))
    print("\nnot worth a call: %s"
          % ", ".join("%s %d" % (k, v) for k, v in skipped.most_common()))
    dom = collections.Counter(r["url"].split("//")[-1].split("/")[0] for r in rows)
    print("\ntop publishers: %s"
          % ", ".join("%s %d" % (d.replace("www.", ""), n) for d, n in dom.most_common(8)))
    big = [r for r in rows if r["chars"] > INDEX_CHARS]
    print("\ncost: %.1fM characters in total; %d catalogue-sized page(s) pushed back"
          % (sum(r["chars"] for r in rows) / 1e6, len(big)))
    print("\nbest value per character:")
    for r in rows[:18]:
        print("  %-5.1f %-42s %6d ch  %-24s %s"
              % (rank(r), r["title"][:42], r["chars"], ",".join(r["surfaces"])[:24],
                 r["url"].split("//")[-1][:32]))
    io.open(HERE / "extract_worklist.json", "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))
    print("\nwrote extract_worklist.json (%d)" % len(rows))
    return rows


def _demo():
    rel, comp = [re.compile(r"kalyani")], [re.compile(r"kalyani")]
    part = {"document_id": "d1", "url": "https://x.com/a", "title": "T",
            "text": "Kalyani signed an MoU with Rafael to build launchers. " * 12}
    s = score_doc(part, rel, comp)
    assert s and "partnership" in s["surfaces"], s
    # too short to extract anything from
    assert score_doc({"document_id": "d", "url": "u", "text": "Kalyani MoU"}, rel, comp) is None
    # nothing in our vocabulary: not our document
    off = {"document_id": "d2", "url": "u", "text": "A recipe for bread. " * 40}
    assert score_doc(off, rel, comp) is None
    # a spec table scores, but below a story that also names organisations
    spec = {"document_id": "d3", "url": "u", "title": "",
            "text": "Kalyani gun. maximum range 40 km. weight 18 tonnes. " * 12}
    a, b = score_doc(spec, rel, comp), score_doc(part, rel, comp)
    assert a and b and b["score"] >= a["score"], (a["score"], b["score"])
    # between two equally useful documents the SHORTER one is worth more: it costs
    # less to extract, and this ranking is what decides where the budget goes
    assert rank(dict(b, chars=3000)) > rank(dict(b, chars=30000))
    # ...and a catalogue-sized page goes to the back
    assert rank(dict(b, chars=70000)) < rank(dict(b, chars=50000))
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main()
