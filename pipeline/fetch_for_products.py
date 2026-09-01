"""Targeted search-and-fetch for the products Positioning still cannot source.

    python fetch_for_products.py --worklist      # what is missing, and why
    python fetch_for_products.py --limit 40
    python fetch_for_products.py --demo

The gap this closes: 410 of 507 archived matchups are held back because their
specification values have no source good enough to show, and Gap Analysis is
empty because a gap needs the SAME field sourced for BOTH products -- one-sided
evidence proves nothing about a difference.

So the worklist is derived from the shortfall itself: every product that appears
in a matchup we could not publish, ranked by how many rows it blocks. Each one is
searched for by name, and only results on a CREDIBLE domain are fetched --
searching is how we find the page, not how we decide whether to trust it.

Search runs through CamoFox because the plain HTTP endpoints refuse this network;
fetching runs through httpx with tables kept, because a spec sheet is a table.
"""
import os
import argparse
import collections
import hashlib
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "l2" / "comprehend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx           # noqa: E402
import psycopg2        # noqa: E402
import trafilatura     # noqa: E402
from source_tiers import MAKER_DOMAINS, REGISTRY_DOMAINS, tier  # noqa: E402
from revive_matchups import product_of                          # noqa: E402
from _fieldwork import field_worklist                           # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
# Wikipedia (and several registries) answer 403 to a generic browser-shaped UA and
# 200 to one that identifies the tool and a contact -- which is their stated policy,
# not an obstacle. Every "0/2 fetched" in the first run was this.
UA = {"User-Agent": "KSSL-corpus/1.0 (defence market research; "
                    "contact: lomesh.narkhede@gmail.com) python-httpx"}
CAMO, KEY = "http://127.0.0.1:9377", "mallory-camofox-key"
MIN_CHARS = 250

# Encyclopaedic references. Not a manufacturer and not an edited trade title, but
# they carry the specification tables this comparison needs and they cite their own
# sources -- so they are worth FETCHING. What they are worth as EVIDENCE is still
# decided by source_tiers, which rates them news-tier and demands corroboration.
# WIKIPEDIA IS NOT ON THIS LIST, deliberately. A client-facing competitive
# dossier cannot cite an anyone-can-edit encyclopaedia as the provenance for a
# specification, however convenient its tables are. It was here, and it reached
# serving: 43 of the 126 matchups the UI showed cited it, 29 of them cited
# nothing else. See extraction/signals/source_policy.py, which is the single
# place that decides, and which also covers the mirrors (wikiwand, dbpedia)
# that a bare "wikipedia.org" rule would let straight through.
EXTRA_OK = {"military-today.com", "armyrecognition.com",
            "army-technology.com", "militaryfactory.com", "deagel.com",
            "weaponsystems.net", "globalsecurity.org", "tanks-encyclopedia.com"}
_TAB = {"id": None}


def _camo(path, body, timeout=40):
    req = urllib.request.Request(
        CAMO + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


SEARCH_JS = ("(()=>new Promise(r=>setTimeout(()=>{"
             "var a=[].slice.call(document.querySelectorAll('a')).map(function(x){"
             "return x.href;}).filter(function(h){"
             "return h.indexOf('http')===0 && h.indexOf('duckduckgo')<0;});"
             "r(JSON.stringify(a.slice(0,40)));},%d)))()")


def search(query, wait_ms=6000):
    """-> [url]. One tab reused for the whole run."""
    try:
        if not _TAB["id"]:
            _TAB["id"] = _camo("/tabs", {"userId": "u1", "sessionKey": "s1"})["tabId"]
        tab = _TAB["id"]
        url = "https://duckduckgo.com/?q=" + urllib.parse.quote(query)
        _camo("/tabs/%s/navigate" % tab, {"userId": "u1", "sessionKey": "s1", "url": url})
        res = _camo("/tabs/%s/evaluate" % tab,
                    {"userId": "u1", "sessionKey": "s1", "expression": SEARCH_JS % wait_ms})
        return json.loads(res["result"])
    except Exception:
        _TAB["id"] = None
        return []


def credible(url):
    """Is this a domain worth FETCHING for a specification? (Not: worth believing.)"""
    h = urlsplit(url).netloc.lower().replace("www.", "")
    if h in EXTRA_OK or any(h.endswith("." + d) for d in EXTRA_OK):
        return True
    return tier(url) in ("official", "registry")


def doc_id(url):
    return "doc_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def worklist(cur, top=60):
    """Products blocking the most unpublished matchups, with their maker."""
    cur.execute("""select comp, "compBy", bf, "bfBy" from serving.matchup
                    where origin='reference'""")
    have = set()
    cur.execute("""select comp, bf from serving.matchup
                    where origin='pipeline' and matchup_id >= 20000""")
    for c, b in cur.fetchall():
        have.add(c)
        have.add(b)
    cur.execute("""select comp, "compBy", bf, "bfBy" from serving.matchup
                    where origin='reference'""")
    blocked = collections.Counter()
    maker = {}
    for comp, compby, bf, bfby in cur.fetchall():
        for name, mk in ((comp, compby), (bf, bfby)):
            if not name or name in have:
                continue
            p = product_of(name)
            if len(p) < 3:
                continue
            blocked[p] += 1
            maker.setdefault(p, mk or "")
    return [(p, maker.get(p, ""), n) for p, n in blocked.most_common(top)]


def extract(html):
    t = trafilatura.extract(html, include_comments=False, include_tables=True)
    if not t:
        t = trafilatura.extract(html, include_comments=False, include_tables=False)
    return t or ""


def pick(hits, n):
    """Top `n` results, one per DOMAIN -- three pages of one site is one witness."""
    picked, doms = [], set()
    for u in hits:
        d = urlsplit(u).netloc.lower().replace("www.", "")
        if d in doms:
            continue
        doms.add(d)
        picked.append(u)
        if len(picked) >= n:
            break
    return picked


def stage(client, url, state, note, title_fallback, detect_lang):
    """Fetch one page into the corpus. -> True if a new document was written."""
    did = doc_id(url)
    if did in state["have"]:
        state["st"]["have"] += 1
        return False
    try:
        r = client.get(url, headers=UA)
        if r.status_code >= 400:
            state["st"]["err"] += 1
            return False
        text = extract(r.text)
    except (httpx.HTTPError, OSError):
        state["st"]["err"] += 1
        return False
    if len(text) < MIN_CHARS:
        state["st"]["thin"] += 1
        return False
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if sha in state["sha"]:
        state["st"]["dup"] += 1
        return False
    state["sha"].add(sha)
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    io.open(CORPUS / ("%s.json" % did), "w", encoding="utf-8").write(
        json.dumps({"document_id": did, "url": str(r.url),
                    "source_id": urlsplit(str(r.url)).netloc.replace("www.", ""),
                    "language": detect_lang(text),
                    "title": (re.sub(r"\s+", " ", m.group(1)).strip()[:300]
                              if m else title_fallback),
                    "text": text, "text_sha256": sha, "n_chars": len(text),
                    "fetched_from": note,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                   ensure_ascii=False))
    state["have"].add(did)
    state["st"]["new"] += 1
    return True


def _state():
    CORPUS.mkdir(exist_ok=True)
    have, sha = set(), set()
    for p in CORPUS.glob("doc_*.json"):
        have.add(p.stem)
        try:
            sha.add(json.loads(p.read_text(encoding="utf-8"))["text_sha256"])
        except (ValueError, KeyError):
            pass
    return {"have": have, "sha": sha,
            "st": {"new": 0, "dup": 0, "thin": 0, "err": 0, "have": 0,
                   "nohit": 0, "searched": 0}}


def run_fields(limit=None, per_query=3, verbose=True):
    """Search per FIELD, not per product.

    Gap Analysis needs the same directional field on BOTH sides, and the general
    query ("<product> specifications calibre range weight") reliably returns
    calibre and rarely returns the fields a gap is actually measured on. So the
    worklist here is (product, field) pairs, ranked so that the pages which turn
    a half-sourced row into a comparable one come first.
    """
    from segment import detect_lang
    con = psycopg2.connect(DSN)
    work = field_worklist(con.cursor())
    con.close()
    state = _state()
    st = state["st"]
    print("%d (product, field) pair(s) blocking a gap\n" % len(work), flush=True)
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for product, mk, lab, query, score, nrows in work:
            if limit and st["searched"] >= limit:
                break
            # Spend the slots on pages we do NOT already hold. The first run of this
            # mode fetched 5 of 6 results straight into "already held": the field
            # words barely change what a search engine returns, so without this the
            # sweep re-reads the same three pages for every field of every product
            # and adds no second domain -- which is the only thing 105 of these rows
            # are actually waiting for.
            hits = [u for u in search(query)
                    if credible(u) and doc_id(u) not in state["have"]]
            picked = pick(hits, per_query)
            st["searched"] += 1
            if not picked:
                st["nohit"] += 1
                if verbose:
                    print("  %-24s %-16s no credible result"
                          % (product[:24], lab[:16]), flush=True)
                continue
            got = sum(1 for u in picked if stage(
                client, u, state, "field-search(%s / %s; %d row(s))" % (product, lab, nrows),
                "%s %s" % (product, lab), detect_lang))
            if verbose:
                print("  %-24s %-16s %d/%d fetched  (%d row(s), score %d)"
                      % (product[:24], lab[:16], got, len(picked), nrows, score),
                      flush=True)
            time.sleep(1.0)
    print("\nsearched %d pair(s): +%d page(s) staged, %d no credible result, "
          "%d dup, %d thin, %d error, %d already held"
          % (st["searched"], st["new"], st["nohit"], st["dup"], st["thin"],
             st["err"], st["have"]))
    return st


def run(limit=None, per_product=3, verbose=True):
    from segment import detect_lang
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    work = worklist(cur)
    con.close()
    CORPUS.mkdir(exist_ok=True)
    have = {p.stem for p in CORPUS.glob("doc_*.json")}
    seen_sha = set()
    for p in CORPUS.glob("doc_*.json"):
        try:
            seen_sha.add(json.loads(p.read_text(encoding="utf-8"))["text_sha256"])
        except (ValueError, KeyError):
            pass

    st = {"new": 0, "dup": 0, "thin": 0, "err": 0, "have": 0, "nohit": 0, "searched": 0}
    print("%d product(s) blocking unpublished matchups\n" % len(work), flush=True)
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for product, mk, nblock in work:
            if limit and st["new"] >= limit:
                break
            q = "%s %s specifications calibre range weight" % (mk, product)
            hits = [u for u in search(q.strip()) if credible(u)]
            st["searched"] += 1
            # dedupe by domain: three pages of one site is one witness, and the
            # corroboration rule counts domains
            picked, doms = [], set()
            for u in hits:
                d = urlsplit(u).netloc.lower().replace("www.", "")
                if d in doms:
                    continue
                doms.add(d)
                picked.append(u)
                if len(picked) >= per_product:
                    break
            if not picked:
                st["nohit"] += 1
                if verbose:
                    print("  %-34s no credible result" % product[:34], flush=True)
                continue
            got = 0
            for u in picked:
                did = doc_id(u)
                if did in have:
                    st["have"] += 1
                    continue
                try:
                    r = client.get(u, headers=UA)
                    if r.status_code >= 400:
                        st["err"] += 1
                        continue
                    text = extract(r.text)
                except (httpx.HTTPError, OSError):
                    st["err"] += 1
                    continue
                if len(text) < MIN_CHARS:
                    st["thin"] += 1
                    continue
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if sha in seen_sha:
                    st["dup"] += 1
                    continue
                seen_sha.add(sha)
                m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
                io.open(CORPUS / ("%s.json" % did), "w", encoding="utf-8").write(
                    json.dumps({"document_id": did, "url": str(r.url),
                                "source_id": urlsplit(str(r.url)).netloc.replace("www.", ""),
                                "language": detect_lang(text),
                                "title": (re.sub(r"\s+", " ", m.group(1)).strip()[:300]
                                          if m else product),
                                "text": text, "text_sha256": sha, "n_chars": len(text),
                                "fetched_from": "spec-search(%s; blocks %d row(s))"
                                                % (product, nblock),
                                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                               ensure_ascii=False))
                have.add(did)
                st["new"] += 1
                got += 1
            if verbose:
                print("  %-34s %d/%d fetched  (blocks %d row(s))"
                      % (product[:34], got, len(picked), nblock), flush=True)
            time.sleep(1.2)
    print("\nsearched %d product(s): +%d page(s) staged, %d had no credible result, "
          "%d dup, %d thin, %d error, %d already held"
          % (st["searched"], st["new"], st["nohit"], st["dup"], st["thin"], st["err"],
             st["have"]))
    return st


def _demo():
    # what we will FETCH is broader than what we will BELIEVE
    # wikipedia is not citable at all now -- see extraction/signals/source_policy.py
    assert not credible("https://en.wikipedia.org/wiki/ATAGS_(howitzer)")
    assert credible("https://www.armyrecognition.com/x")
    assert credible("https://knds.com/products/caesar")
    assert not credible("https://randomblog.example/post")
    # ...and fetching it does not upgrade it: wikipedia is still news-tier evidence
    assert tier("https://en.wikipedia.org/wiki/ATAGS_(howitzer)") == "news"
    assert tier("https://knds.com/x") == "official"
    assert doc_id("http://a") != doc_id("http://b")
    # one URL per domain, order preserved
    assert pick(["https://a.com/1", "https://a.com/2", "https://b.com/1"], 3) ==         ["https://a.com/1", "https://b.com/1"]
    assert len(pick(["https://a.com/1", "https://b.com/1", "https://c.com/1"], 2)) == 2
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--per-product", type=int, default=3)
    ap.add_argument("--worklist", action="store_true")
    ap.add_argument("--fields", action="store_true",
                    help="search per FIELD (what Gap Analysis is waiting on)")
    ap.add_argument("--field-worklist", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.field_worklist:
        con = psycopg2.connect(DSN)
        for p, mk, lab, q, sc, n in field_worklist(con.cursor()):
            print("  %-26s %-16s score=%-4d rows=%-4d  %s" % (p[:26], lab[:16], sc, n, q))
        con.close()
    elif a.fields:
        run_fields(a.limit, a.per_product)
    elif a.worklist:
        con = psycopg2.connect(DSN)
        for p, mk, n in worklist(con.cursor()):
            print("  %-40s %-30s blocks %d row(s)" % (p[:40], (mk or "")[:30], n))
        con.close()
    else:
        run(a.limit, a.per_product)
