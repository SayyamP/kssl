"""Fetch product pages from the manufacturers' OWN sites, for spec provenance.

    python fetch_official.py --probe          # which maker sites answer us
    python fetch_official.py --limit 200
    python fetch_official.py --demo

Positioning compares weapons, so its numbers have to come from somewhere a reader
would accept: the company that builds the thing, or a government programme page.
Search engines are blocking this network, so the reliable route is also the
correct one -- go to the maker's own site and take the product pages.

Two things this does that fetch_corpus deliberately does not:
  * keeps HTML TABLES (a spec sheet is mostly table), and
  * follows one level of product links from the products/defence section, so the
    entry point can be a hub page rather than a hand-listed URL per product.

Everything is staged in the same shape as fetch_corpus, so load_extracted and the
grounding step need no changes.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "l2" / "comprehend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx           # noqa: E402
import trafilatura     # noqa: E402
from source_tiers import MAKER_DOMAINS  # noqa: E402

UA = {"User-Agent": "KSSL-corpus/1.0 (defence market research; "
                    "contact: lomesh.narkhede@gmail.com) python-httpx"}
MIN_CHARS = 250

# Entry points per maker. A hub page, not a product page: the crawl finds the
# products from it, so this list does not go stale every time a model is added.
HUBS = {
    "bharatforge.com": ["https://www.bharatforge.com/defence", "https://www.bharatforge.com/"],
    # The client's own product pages. KSSL's vehicles are named by acronym (MPV,
    # ATC, LBPV, LTV, ULSV) and a search engine cannot find them by name at all --
    # the maker's own site is the only place those spec sheets exist.
    "kalyanistrategic.com": ["https://kalyanistrategic.com/products/",
                             "https://kalyanistrategic.com/"],
    "baesystems.com": ["https://www.baesystems.com/en/our-company/what-we-do"],
    "knds.com": ["https://www.knds.com/products/"],
    "knds.de": ["https://www.knds.de/en/products/"],
    "elbitsystems.com": ["https://elbitsystems.com/products/"],
    "hanwha.com": ["https://www.hanwha.com/en/products_and_services.html"],
    "saab.com": ["https://www.saab.com/products"],
    "rheinmetall.com": ["https://www.rheinmetall.com/en/products"],
    "leonardo.com": ["https://www.leonardo.com/en/products"],
    "gdls.com": ["https://www.gdls.com/products/"],
    "oshkoshdefense.com": ["https://oshkoshdefense.com/vehicles/"],
    "paramountgroup.com": ["https://www.paramountgroup.com/land/", "https://www.paramountgroup.com/"],
    "otokar.com.tr": ["https://www.otokar.com.tr/en/products/defence-industry", "https://www.otokar.com.tr/en"],
    "nurolmakina.com.tr": ["https://www.nurolmakina.com.tr/en/products"],
    "tataadvancedsystems.com": ["https://www.tataadvancedsystems.com/capabilities", "https://www.tataadvancedsystems.com/"],
    "mahindradefence.com": ["https://www.mahindradefence.com/products", "https://www.mahindradefence.com/"],
    "adanidefence.com": ["https://www.adanidefence.com/what-we-do"],
    "ashokleyland.com": ["https://www.ashokleyland.com/in/en/defence"],
    "forcemotors.com": ["https://www.forcemotors.com/"],
    "denel.co.za": ["https://www.denel.co.za/"],
    "patriagroup.com": ["https://www.patriagroup.com/products"],
    "nexter-group.fr": ["https://www.nexter-group.fr/en/produits", "https://www.knds.fr/en"],
    "aselsan.com.tr": ["https://www.aselsan.com/en/solutions", "https://www.aselsan.com.tr/en"],
    "roketsan.com.tr": ["https://www.roketsan.com.tr/en/products"],
    "milremrobotics.com": ["https://milremrobotics.com/robots/"],
    "excaliburarmy.cz": ["https://www.excaliburarmy.cz/en/products"],
    "brahmos.com": ["https://www.brahmos.com/"],
}

# A link worth following from a hub.
PRODUCT_HINT = re.compile(
    r"(product|vehicle|system|platform|howitzer|artillery|gun|mortar|armou?r|"
    r"munition|ammunition|missile|uav|drone|solution|capabilit|defen[cs]e|land)",
    re.I)
SKIP = re.compile(r"(career|job|news|press|investor|contact|privacy|cookie|legal|"
                  r"login|search|sitemap|\.pdf$|\.jpg$|\.png$|mailto:|tel:)", re.I)


def doc_id(url):
    return "doc_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def extract(html):
    t = trafilatura.extract(html, include_comments=False, include_tables=True)
    if not t:
        t = trafilatura.extract(html, include_comments=False, include_tables=False)
    return t or ""


def links_from(html, base, host):
    """Product-ish links on the same host, deduped, in page order."""
    out, seen = [], set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html or "", re.I):
        u = urljoin(base, m.group(1).strip())
        if not u.startswith("http") or SKIP.search(u):
            continue
        h = urlsplit(u).netloc.lower().replace("www.", "")
        if h != host.replace("www.", ""):
            continue
        u = u.split("#")[0].rstrip("/")
        if u in seen or not PRODUCT_HINT.search(u):
            continue
        seen.add(u)
        out.append(u)
    return out


def probe(client):
    """Which maker sites will talk to us at all. A blocked site is a finding."""
    rows = []
    for host, hubs in sorted(HUBS.items()):
        code, why = None, ""
        for h in hubs:
            try:
                r = client.get(h, headers=UA)
                code = r.status_code
                if code < 400:
                    why = "%d chars" % len(r.text or "")
                    break
            except (httpx.HTTPError, OSError) as e:
                code, why = None, type(e).__name__
        rows.append((host, code, why))
        print("  %-30s %-6s %s" % (host, code if code else "ERR", why), flush=True)
    ok = sum(1 for _h, c, _w in rows if c and c < 400)
    print("\n%d of %d maker site(s) reachable" % (ok, len(rows)))
    return rows


_TAB = {"id": None}


def _camo(path, body, timeout):
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:9377" + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer mallory-camofox-key"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def render(url, timeout=25):
    """Fetch through CamoFox. Several maker sites return a JavaScript shell to plain
    HTTP -- "Systems & Products - Overview" came back as 410 characters -- and a
    shell carries no specification table.

    ONE tab is reused for the whole run. Creating a tab per page spawned a browser
    context each time and the harvest managed 3 documents in 54 minutes."""
    try:
        if not _TAB["id"]:
            _TAB["id"] = _camo("/tabs", {"userId": "u1", "sessionKey": "s1"}, 30)["tabId"]
        tab = _TAB["id"]
        _camo("/tabs/%s/navigate" % tab,
              {"userId": "u1", "sessionKey": "s1", "url": url}, timeout)
        res = _camo("/tabs/%s/evaluate" % tab, {
            "userId": "u1", "sessionKey": "s1",
            "expression": "(()=>new Promise(r=>setTimeout(()=>r("
                          "document.documentElement.outerHTML),2200)))()"}, timeout)
        return res.get("result") or ""
    except Exception:
        _TAB["id"] = None        # tab died; the next call makes a fresh one
        return ""


def harvest(limit=None, per_site=12, verbose=True, depth=2, use_browser=True,
            only=None):
    from segment import detect_lang
    CORPUS.mkdir(exist_ok=True)
    have = {p.stem for p in CORPUS.glob("doc_*.json")}
    seen_sha = set()
    for p in CORPUS.glob("doc_*.json"):
        try:
            seen_sha.add(json.loads(p.read_text(encoding="utf-8"))["text_sha256"])
        except (ValueError, KeyError):
            pass

    st = {"new": 0, "dup": 0, "thin": 0, "err": 0, "have": 0, "hubs": 0, "rendered": 0}
    hubs_todo = {h: v for h, v in HUBS.items() if not only or h in only}
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for host, hubs in sorted(hubs_todo.items()):
            if limit and st["new"] >= limit:
                break
            maker = MAKER_DOMAINS.get(host, host)
            targets = []
            for hub in hubs:
                try:
                    r = client.get(hub, headers=UA)
                except (httpx.HTTPError, OSError):
                    continue
                if r.status_code >= 400:
                    continue
                st["hubs"] += 1
                first = links_from(r.text, hub, host)[:per_site]
                targets = [hub] + first
                # One level deeper: the hub lists categories, and the SPEC TABLE
                # lives on the product page under them. Stopping at depth 1 landed
                # 110 official pages of which only 10 carried a calibre.
                if depth >= 2:
                    for u2 in first[:6]:
                        try:
                            r2 = client.get(u2, headers=UA)
                            if r2.status_code < 400:
                                targets += links_from(r2.text, u2, host)[:6]
                        except (httpx.HTTPError, OSError):
                            pass
                    seen_t, ded = set(), []
                    for u in targets:
                        if u not in seen_t:
                            seen_t.add(u)
                            ded.append(u)
                    targets = ded[:per_site * 3]
                break
            if not targets:
                if verbose:
                    print("  %-28s unreachable" % host, flush=True)
                continue
            got, rendered_here = 0, 0
            print("  %-26s %d target(s)" % (host, len(targets)), flush=True)
            for u in targets:
                if limit and st["new"] >= limit:
                    break
                did = doc_id(u)
                if did in have:
                    st["have"] += 1
                    continue
                try:
                    r = client.get(u, headers=UA)
                    if r.status_code >= 400:
                        st["err"] += 1
                        continue
                    html, text = r.text, extract(r.text)
                except (httpx.HTTPError, OSError):
                    st["err"] += 1
                    continue
                if len(text) < 900 and use_browser and rendered_here < 6                         and PRODUCT_HINT.search(u):
                    # probably a JS shell -- render it before giving up
                    rendered_here += 1
                    html2 = render(u)
                    if html2:
                        t2 = extract(html2)
                        if len(t2) > len(text):
                            text, html = t2, html2
                            st["rendered"] += 1
                if len(text) < MIN_CHARS:
                    st["thin"] += 1
                    continue
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if sha in seen_sha:
                    st["dup"] += 1
                    continue
                seen_sha.add(sha)
                m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
                title = re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else u
                io.open(CORPUS / ("%s.json" % did), "w", encoding="utf-8").write(
                    json.dumps({"document_id": did, "url": str(r.url),
                                "source_id": host, "language": detect_lang(text),
                                "title": title, "text": text, "text_sha256": sha,
                                "n_chars": len(text),
                                "fetched_from": "official-site(%s)" % maker,
                                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                               ensure_ascii=False))
                have.add(did)
                st["new"] += 1
                got += 1
                if got % 5 == 0:
                    print("      %s ... %d staged" % (host, got), flush=True)
            if verbose:
                print("  %-28s %2d page(s) staged" % (host, got), flush=True)
            time.sleep(0.6)
    print("\nofficial pages: +%d new, %d dup, %d thin, %d error, %d already held "
          "(from %d hub(s))" % (st["new"], st["dup"], st["thin"], st["err"],
                                st["have"], st["hubs"]))
    return st


def _demo():
    html = ('<a href="/products/howitzer-x">A</a><a href="/careers/job">B</a>'
            '<a href="https://other.com/products/z">C</a><a href="/en/vehicles/mrap">D</a>')
    got = links_from(html, "https://knds.com/", "knds.com")
    assert "https://knds.com/products/howitzer-x" in got, got
    assert "https://knds.com/en/vehicles/mrap" in got
    assert not any("careers" in u for u in got), "careers must be skipped"
    assert not any("other.com" in u for u in got), "off-host links must be skipped"
    # tables survive, which is the whole point of using this instead of fetch_corpus
    t = extract("<html><body><article><p>Specification of the gun follows below now.</p>"
                "<table><tr><td>Calibre</td><td>155 mm</td></tr></table></article></body></html>")
    assert "155" in t, t
    assert doc_id("http://a") != doc_id("http://b")
    print("ok (%d maker hub(s))" % len(HUBS))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--per-site", type=int, default=12)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", default=None,
                    help="comma-separated hub domains to crawl (default: all)")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.probe:
        with httpx.Client(timeout=20.0, follow_redirects=True) as c:
            probe(c)
    else:
        harvest(a.limit, a.per_site, depth=a.depth, use_browser=not a.no_browser,
                only=set(x.strip() for x in a.only.split(",")) if a.only else None)
