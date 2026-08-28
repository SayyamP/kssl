"""Fetch a real, KSSL-relevant corpus straight from the defence press.

    python fetch_corpus.py                 # fetch everything new, stage under corpus/
    python fetch_corpus.py --limit 40
    python fetch_corpus.py --demo

Articles come from two kinds of source, and the difference is the relevance filter:

  * DEFENCE OUTLET FEEDS -- the outlet itself is the topical gate, so every entry qualifies.
    The list deliberately spans languages, because the extraction pipeline is multilingual and
    an English-only corpus would test none of that.
  * GOOGLE NEWS QUERIES -- topic-targeted. The fixed list covers artillery/procurement themes;
    kssl_queries() adds one query per COMPETITOR and per PRODUCT CATEGORY generated from the
    reference dataset itself, so the corpus covers the rivals the client actually tracks.

Staged as one JSON per document under corpus/ rather than written to Postgres, so this step
has no dependency on the schema being up; load_extracted.py moves the staging area into
`extracted.document` when the database exists.

Language is detected with the extraction pipeline's OWN detector (comprehend/segment.py),
not a third library -- two detectors disagreeing about Persian vs Arabic is exactly the bug
this project has already paid for once.
"""
import argparse
import base64
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
sys.path.insert(0, str(HERE.parent.parent / "l2" / "comprehend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
import trafilatura

# Whole-outlet feeds: everything they publish is defence, so no keyword gate.
FEEDS = [
    "https://www.armyrecognition.com/rss",
    "https://defence-blog.com/feed/",
    "https://bulgarianmilitary.com/feed/",
    "https://www.zona-militar.com/feed/",
    "https://www.opex360.com/feed/",
    "https://meta-defense.fr/feed/",
    "https://www.defensahoy.com/rss",
    "https://www.idrw.org/feed/",
    "https://defencesecurityasia.com/feed/",
    "https://www.defenceweb.co.za/feed/",
    "https://militarnyi.com/en/feed/",
    "https://www.hartpunkt.de/feed/",
    "https://www.analisidifesa.it/feed/",
]

# Topic-targeted queries; hl picks the edition so the corpus stays multilingual on purpose.
GNEWS = [
    ("artillery howitzer 155mm order", "en"),
    ("K9 Vajra OR ATAGS OR 'Bharat Forge' defence", "en-IN"),
    ("India defence procurement contract", "en-IN"),
    ("obus 155mm artillerie commande", "fr"),
    ("artilleria autopropulsada contrato", "es"),
    ("Haubitze Artillerie Auftrag", "de"),
    ("KNDS OR Rheinmetall OR Hanwha howitzer", "en"),
    ("loitering munition order army", "en"),
]

MIN_CHARS = 800
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KSSL-corpus/1.0"}


def kssl_queries():
    """Competitor and product queries generated FROM the reference dataset, not typed here.

    The dataset names 28 competitors and 9 product categories; typing a subset by hand is how
    a corpus silently under-covers the rivals the client cares about. Short tickers (MIL, PEL,
    WIL) are skipped -- a three-letter ticker matches everything and nothing."""
    ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
    out = [("Kalyani Strategic Systems OR 'Bharat Forge' defence", "en-IN")]
    for key, c in ref.get("competitors", {}).items():
        name = (c.get("name") or key).strip()
        if len(name) <= 4:
            continue
        out.append(('"%s" defence contract OR order OR unveiled' % name, "en-IN"))
    for cat in ref.get("KSSL_CATS", []):
        out.append(("%s India tender OR contract OR order" % cat, "en-IN"))
    return out


def decode_gnews(url):
    """news.google.com/rss/articles/... links are JS redirect stubs -- fetching one yields a
    consent shell that trafilatura rightly calls thin (76 of the first run's fetches died
    there). The REAL article URL is base64-encoded in the path; decode it instead of fetching
    the stub. Best effort: the newer opaque encodings return None and the entry is dropped."""
    m = re.search(r"/rss/articles/([^?/]+)", url)
    if not m:
        return None
    tok = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
    except Exception:                                             # noqa: BLE001
        return None
    # The decoded blob is protobuf: the URL is a printable run terminated by a control byte.
    hit = re.findall(rb"https?://[\x20-\x7e]+", raw)
    for h in sorted(hit, key=len, reverse=True):
        u = h.decode("ascii", "ignore").strip()
        if "news.google" not in u and len(u) > 12:
            return u
    return None


def feed_entries(xml_text):
    """-> [(title, link)] from RSS or Atom, namespace-insensitively. feedparser is not
    installed and eleven lines of stdlib do not justify adding a dependency."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag != "item" and tag != "entry":
            continue
        title = link = None
        for ch in item:
            t = ch.tag.rsplit("}", 1)[-1]
            if t == "title":
                title = (ch.text or "").strip()
            elif t == "link":
                link = (ch.get("href") or ch.text or "").strip()
        if title and link:
            out.append((title, link))
    return out


def doc_id(url):
    return "doc_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def fetch_article(client, url):
    """-> (final_url, text, title) or None. trafilatura does the boilerplate stripping; a
    page that yields under MIN_CHARS of body text is a listing or a stub, not an article."""
    r = client.get(url, headers=UA)
    if r.status_code >= 400 or not r.text:
        return None
    text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
    if not text or len(text) < MIN_CHARS:
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else ""
    return str(r.url), text, title


def harvest(limit=None, verbose=True):
    from segment import detect_lang
    CORPUS.mkdir(exist_ok=True)
    have = {p.stem for p in CORPUS.glob("doc_*.json")}
    seen_sha = set()
    for p in CORPUS.glob("doc_*.json"):
        try:
            seen_sha.add(json.loads(p.read_text(encoding="utf-8"))["text_sha256"])
        except (ValueError, KeyError):
            pass

    todo = []
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for f in FEEDS:
            try:
                r = client.get(f, headers=UA)
                ent = feed_entries(r.text) if r.status_code < 400 else []
            except httpx.HTTPError:
                ent = []
            todo += [(t, u, f) for t, u in ent[:30]]
            if verbose:
                print("feed %-46s %d entr(ies)" % (f[:46], len(ent)), flush=True)
        for q, hl in GNEWS + kssl_queries():
            u = ("https://news.google.com/rss/search?q=%s&hl=%s"
                 % (httpx.QueryParams({"q": q})["q"].replace(" ", "+"), hl))
            try:
                r = client.get(u, headers=UA)
                ent = feed_entries(r.text) if r.status_code < 400 else []
            except httpx.HTTPError:
                ent = []
            # Decode the redirect stubs to real article URLs; what cannot decode is dropped
            # rather than fetched as a consent shell and counted "thin".
            dec = [(t, decode_gnews(u2) or "") for t, u2 in ent[:15]]
            todo += [(t, u2, "gnews:" + q) for t, u2 in dec if u2]
            if verbose:
                print("gnews %-46s %d entr(ies), %d decodable"
                      % (q[:46], len(ent), sum(1 for _t, u2 in dec if u2)), flush=True)

        stats = {"new": 0, "dup": 0, "thin": 0, "err": 0, "have": 0}
        for title, url, src in todo:
            if limit and stats["new"] >= limit:
                break
            did = doc_id(url)
            if did in have:
                stats["have"] += 1
                continue
            try:
                got = fetch_article(client, url)
            except httpx.HTTPError:
                stats["err"] += 1
                continue
            if not got:
                stats["thin"] += 1
                continue
            final_url, text, page_title = got
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if sha in seen_sha:
                # Same words at a different address -- a syndicated reprint. One copy is the
                # corpus; a second would be a fake independent witness downstream.
                stats["dup"] += 1
                continue
            seen_sha.add(sha)
            lang = detect_lang(text)
            row = {"document_id": did, "url": final_url, "source_id": re.sub(
                       r"^www\.", "", (re.findall(r"https?://([^/]+)", final_url) or ["?"])[0]),
                   "language": lang, "title": title or page_title, "text": text,
                   "text_sha256": sha, "n_chars": len(text),
                   "fetched_from": src, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            io.open(CORPUS / ("%s.json" % did), "w", encoding="utf-8").write(
                json.dumps(row, ensure_ascii=False))
            have.add(did)
            stats["new"] += 1
            if verbose and stats["new"] % 10 == 0:
                print("  %(new)d new (%(dup)d dup, %(thin)d thin, %(err)d err)" % stats,
                      flush=True)
    if verbose:
        langs = {}
        for p in CORPUS.glob("doc_*.json"):
            try:
                lg = json.loads(p.read_text(encoding="utf-8"))["language"]
                langs[lg] = langs.get(lg, 0) + 1
            except (ValueError, KeyError):
                pass
        print("staged: %d total; this run +%d new, %d dup, %d thin, %d err  langs=%s"
              % (len(list(CORPUS.glob("doc_*.json"))), stats["new"], stats["dup"],
                 stats["thin"], stats["err"], dict(sorted(langs.items(), key=lambda x: -x[1]))),
              flush=True)
    return stats


def _demo():
    rss = """<rss><channel><item><title>A</title><link>http://x/a</link></item>
             <item><title>B</title><link>http://x/b</link></item></channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>C</title>
              <link href="http://x/c"/></entry></feed>"""
    assert feed_entries(rss) == [("A", "http://x/a"), ("B", "http://x/b")]
    assert feed_entries(atom) == [("C", "http://x/c")]
    assert feed_entries("not xml at all") == []
    assert doc_id("http://x/a") == doc_id("http://x/a") and doc_id("http://x/a") != doc_id("http://x/b")
    # The gnews decoder must recover an embedded URL and refuse the undecodable politely.
    blob = b"\x08\x13\x22" + b"https://example.com/article-1" + b"\xd2\x01\x00"
    tok = base64.urlsafe_b64encode(blob).decode().rstrip("=")
    assert decode_gnews("https://news.google.com/rss/articles/%s?oc=5" % tok) == \
        "https://example.com/article-1"
    assert decode_gnews("https://news.google.com/rss/articles/!!notb64!!") is None
    assert decode_gnews("https://example.com/plain") is None
    # Queries must come from the dataset -- real competitor names, no bare tickers.
    qs = kssl_queries()
    assert any("Solar Industries" in q for q, _ in qs)
    assert not any('"MIL"' in q for q, _ in qs)
    assert any("Artillery" in q for q, _ in qs)
    # The pipeline's own detector must be importable -- a second detector is the known bug.
    from segment import detect_lang
    assert detect_lang("The howitzer fired twelve rounds at the range today.") == "en"
    # This file must contain no raw control bytes -- it has already been corrupted once by a
    # heredoc eating backslashes, and the corruption compiled up to the first null byte.
    src = Path(__file__).read_text(encoding="utf-8")
    bad = {c for c in src if ord(c) < 32 and c not in "\n\t"}
    assert not bad, [hex(ord(c)) for c in bad]
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        harvest(limit=a.limit)
