"""Fetch the documents the ARCHIVED reference data cites, so its claims can be grounded.

    python fetch_targeted.py                  # everything in revive_urls.json
    python fetch_targeted.py --limit 20
    python fetch_targeted.py --demo

Differs from fetch_corpus.py in three ways, each deliberate:

1. **Tables are KEPT.** `fetch_corpus` calls trafilatura with `include_tables=False`
   because a news article's tables are navigation furniture. Here the tables ARE
   the payload -- an armyrecognition or army-technology page carries calibre, range
   and weight in a table, and that is the only reason we want the page. Stripping
   them would fetch 133 documents and land none of the numbers.
2. **No MIN_CHARS floor on table pages.** A spec sheet can be mostly table and
   little prose; the general fetcher would call it "thin" and drop it.
3. **The worklist is a bibliography, not a feed.** These URLs were named by
   reference rows, so each one is wanted for a reason recorded in `cited_by`.

Staging shape is identical to fetch_corpus's, so load_extracted needs no changes.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
WORK = HERE / "revive_urls.json"
sys.path.insert(0, str(HERE.parent.parent / "l2" / "comprehend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx           # noqa: E402
import trafilatura     # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KSSL-corpus/1.0"}
MIN_CHARS = 300        # lower than fetch_corpus's 800: a spec sheet is mostly table
SPEC_CUES = ("calibre", "caliber", "range", "weight", "crew", "mm", "km", "kg",
             "specification", "technical data", "performance")


def doc_id(url):
    return "doc_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def extract(html):
    """-> text. Tables kept; falls back to no-table extraction if that yields nothing."""
    t = trafilatura.extract(html, include_comments=False, include_tables=True)
    if not t:
        t = trafilatura.extract(html, include_comments=False, include_tables=False)
    return t or ""


def looks_specced(text):
    """Did we actually land numbers? Reported, never used to reject -- a page that is
    only prose is still evidence for the claim that cited it."""
    low = text.lower()
    return sum(1 for c in SPEC_CUES if c in low) >= 4 and any(ch.isdigit() for ch in text)


def fetch(client, url):
    r = client.get(url, headers=UA)
    if r.status_code >= 400 or not r.text:
        return None, "http %d" % r.status_code
    text = extract(r.text)
    if len(text) < MIN_CHARS:
        return None, "thin (%d chars)" % len(text)
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else ""
    return (str(r.url), text, title), None


def main(limit=None):
    from segment import detect_lang
    if not WORK.exists():
        raise SystemExit("run revive_urls.py first -- no %s" % WORK.name)
    work = json.loads(io.open(WORK, encoding="utf-8").read())
    todo = work["todo"]
    cited = work.get("cited_by", {})
    CORPUS.mkdir(exist_ok=True)

    have = {p.stem for p in CORPUS.glob("doc_*.json")}
    seen_sha = set()
    for p in CORPUS.glob("doc_*.json"):
        try:
            seen_sha.add(json.loads(p.read_text(encoding="utf-8"))["text_sha256"])
        except (ValueError, KeyError):
            pass

    st = {"new": 0, "spec": 0, "dup": 0, "thin": 0, "err": 0, "have": 0}
    fails = []
    print("%d URL(s) cited by the archive; %d already staged\n" % (len(todo), len(have)))
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for i, url in enumerate(todo, 1):
            if limit and st["new"] >= limit:
                break
            did = doc_id(url)
            if did in have:
                st["have"] += 1
                continue
            try:
                got, why = fetch(client, url)
            except (httpx.HTTPError, OSError) as e:
                got, why = None, type(e).__name__
            if not got:
                st["err" if (why or "").startswith("http") else "thin"] += 1
                fails.append((url, why))
                print("  [%3d] SKIP %-52s %s" % (i, urlsplit(url).netloc[:52], why), flush=True)
                continue
            final_url, text, page_title = got
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if sha in seen_sha:
                st["dup"] += 1
                continue
            seen_sha.add(sha)
            spec = looks_specced(text)
            st["spec"] += bool(spec)
            row = {"document_id": did, "url": final_url,
                   "source_id": re.sub(r"^www\.", "", urlsplit(final_url).netloc),
                   "language": detect_lang(text), "title": page_title, "text": text,
                   "text_sha256": sha, "n_chars": len(text),
                   "fetched_from": "reference-bibliography(cited by %d row(s))"
                                   % cited.get(url, 0),
                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            io.open(CORPUS / ("%s.json" % did), "w", encoding="utf-8").write(
                json.dumps(row, ensure_ascii=False))
            have.add(did)
            st["new"] += 1
            print("  [%3d] %-46s %6d chars%s" % (i, urlsplit(final_url).netloc[:46],
                                                 len(text), "  SPECS" if spec else ""),
                  flush=True)

    print("\nstaged +%d new (%d carry spec-shaped numbers), %d dup, %d thin, %d http error, "
          "%d already had" % (st["new"], st["spec"], st["dup"], st["thin"], st["err"],
                              st["have"]))
    if fails:
        io.open(HERE / "fetch_targeted_failed.json", "w", encoding="utf-8").write(
            json.dumps(fails, ensure_ascii=False, indent=1))
        print("%d failure(s) -> fetch_targeted_failed.json (a dead citation is a finding: "
              "the reference row that cited it has no live source)" % len(fails))
    return st


def _demo():
    assert doc_id("http://a") == doc_id("http://a") and doc_id("http://a") != doc_id("http://b")
    # tables must survive extraction -- the entire reason this file exists
    html = ("<html><body><article><p>The gun is described below in detail for readers.</p>"
            "<table><tr><td>Calibre</td><td>155 mm</td></tr>"
            "<tr><td>Max range</td><td>40 km</td></tr></table></article></body></html>")
    t = extract(html)
    assert "155" in t and "40" in t, "table content was stripped: %r" % t
    assert looks_specced("calibre 155 mm range 40 km weight 13000 kg crew 5 specification")
    assert not looks_specced("a short prose sentence about policy")
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.limit)
