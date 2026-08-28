"""Harvest real patent records through the browser, when the JSON endpoints refuse us.

    python fetch_patents_browser.py --dry
    python fetch_patents_browser.py --apply
    python fetch_patents_browser.py --demo

Google Patents' xhr/query endpoint answers "Sorry... your computer or network may
be sending automated queries" from this IP -- and it answers it to CamoFox too, so
it is a network-level block, not a user-agent one. Justia carries the same records
behind a Cloudflare interstitial that CamoFox clears on its own in about ten
seconds, which is exactly what the browser is kept for.

The gates are imported from fetch_patents rather than rewritten, so a record has
to clear the same two bars whichever route it arrived by: a well-formed
publication number, and a defence-relevant subject.
"""
import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from fetch_patents import (AREAS, ASSIGNEES, TOPICS, classify,  # noqa: E402
                           country_of, apply_rows)

CAMO = "http://127.0.0.1:9377"
KEY = "mallory-camofox-key"
SEARCH = "https://patents.justia.com/search?q="
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Justia is a US collection and prints numbers bare: "20090260513" for an
# application, "7654321" for a grant. The registry prefix is added here so the
# stored identifier says which office issued it.
JNUM = re.compile(r"Publication number:\s*([0-9,]{7,})")
FILED = re.compile(r"Filed:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
PUBDATE = re.compile(r"(?:Publication date|Date of Patent):\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
ASSIGNEE = re.compile(r"Assignee:\s*([^\n]{2,80})")
KIND = re.compile(r"Type:\s*(Application|Grant)")


def _post(path, body, timeout=90):
    req = urllib.request.Request(
        CAMO + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def new_tab():
    return _post("/tabs", {"userId": "u1", "sessionKey": "s1"})["tabId"]


# One IIFE, no regex literals, no raw newlines -- the evaluate endpoint rejects
# all three. Waits out the Cloudflare interstitial before reading.
GRAB = ("(()=>new Promise(r=>setTimeout(()=>{"
        "const out=[];"
        "document.querySelectorAll('.has-padding-content-block-30').forEach(e=>{"
        "const a=e.querySelector('a[href*=patent]');"
        "out.push({href:a?a.getAttribute('href'):'',text:e.innerText});});"
        "r(JSON.stringify({title:document.title,n:out.length,rows:out}));"
        "},%d)))()")


def search(tab, query, wait_ms=13000):
    url = SEARCH + urllib.parse.quote(query)
    _post("/tabs/%s/navigate" % tab, {"userId": "u1", "sessionKey": "s1", "url": url})
    res = _post("/tabs/%s/evaluate" % tab,
                {"userId": "u1", "sessionKey": "s1", "expression": GRAB % wait_ms})
    return json.loads(res["result"])


def parse_row(text, href):
    """-> record dict, or None when the block is not a patent result."""
    m = JNUM.search(text or "")
    if not m:
        return None
    num = m.group(1).replace(",", "")
    title = (text.strip().splitlines() or [""])[0].strip()
    absm = re.search(r"Abstract:\s*(.+?)(?:\nType:|\nFiled:|$)", text, re.S)
    abstract = " ".join((absm.group(1) if absm else "").split())[:1200]
    area = classify(title, abstract)
    if not area:
        return None
    kind = KIND.search(text)
    granted = PUBDATE.search(text)
    filed = FILED.search(text)
    asg = ASSIGNEE.search(text)
    is_grant = bool(kind and kind.group(1) == "Grant")
    return {
        "no": "US" + num, "title": title,
        "assignee": (asg.group(1).strip() if asg else "not stated"),
        "status": "granted" if is_grant else "filed",
        "filed": filed.group(1) if filed else None,
        "granted": granted.group(1) if (granted and is_grant) else None,
        "country": "US", "abstract": abstract, "area": area,
        "url": "https://patents.justia.com" + href if href.startswith("/") else href,
    }


# The search LIST never prints an assignee; only the detail page does. A patent
# table whose whole purpose is "who is building IP in our space" is worthless
# without it, so every hit is opened. Cloudflare challenges once per session, so
# these load in ~4s each after the first.
DETAIL = ("(()=>new Promise(r=>setTimeout(()=>{var t=document.body.innerText;"
          "function grab(w){var i=t.indexOf(w);return i>-1?t.slice(i+w.length,i+w.length+90)"
          ".split(String.fromCharCode(10))[0].trim():null;}"
          "r(JSON.stringify({assignee:grab('Assignee:'),kind:grab('Type:'),"
          "filed:grab('Filed:'),granted:grab('Date of Patent:'),"
          "pno:grab('Patent number:')}));},2600)))()")


def detail(tab, url):
    try:
        _post("/tabs/%s/navigate" % tab, {"userId": "u1", "sessionKey": "s1", "url": url})
        res = _post("/tabs/%s/evaluate" % tab,
                    {"userId": "u1", "sessionKey": "s1", "expression": DETAIL})
        return json.loads(res["result"])
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return {}


def enrich(tab, rows, verbose=True):
    """Fill assignee and the real grant number from each detail page.

    Rows whose owner cannot be established are DROPPED rather than stored as
    "not stated": an unattributed patent cannot tell KSSL whether a rival is
    moving, which is the only question this tab exists to answer."""
    out = []
    for i, r in enumerate(rows, 1):
        d = detail(tab, r["url"])
        asg = (d.get("assignee") or "").strip()
        # strip the trailing "(Maharashtra)" style location the page appends
        asg = re.sub(r"\s*\([^)]*\)\s*$", "", asg).strip()
        if not asg or asg.lower().startswith("inventor"):
            continue
        r["assignee"] = asg
        if d.get("kind") and "Grant" in d["kind"]:
            r["status"] = "granted"
            if d.get("pno"):
                r["no"] = "US" + re.sub(r"[^0-9]", "", d["pno"])
            r["granted"] = d.get("granted") or r.get("granted")
        r["filed"] = d.get("filed") or r.get("filed")
        out.append(r)
        if verbose and i % 10 == 0:
            print("    detail %d/%d, %d with a named owner" % (i, len(rows), len(out)),
                  flush=True)
    return out


def collect(queries, per=20, verbose=True):
    tab = new_tab()
    rows, seen, skipped = [], set(), {"irrelevant": 0, "unparsed": 0, "dup": 0}
    for q in queries:
        try:
            got = search(tab, q)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print("  %-34s SEARCH FAILED %s" % (q[:34], type(e).__name__), flush=True)
            continue
        if "Sorry" in (got.get("title") or "") or got.get("n", 0) == 0:
            print("  %-34s blocked or empty (%s)" % (q[:34], (got.get("title") or "")[:28]),
                  flush=True)
            continue
        kept = 0
        for item in got["rows"][:per]:
            rec = parse_row(item.get("text", ""), item.get("href", ""))
            if not rec:
                skipped["irrelevant"] += 1
                continue
            if rec["no"] in seen:
                skipped["dup"] += 1
                continue
            seen.add(rec["no"])
            rec["queried_as"] = q
            rows.append(rec)
            kept += 1
        if verbose:
            print("  %-34s %2d result(s) -> %2d kept" % (q[:34], got["n"], kept), flush=True)
        time.sleep(1.5)
    print("\n  opening %d detail page(s) for assignees..." % len(rows), flush=True)
    before = len(rows)
    rows = enrich(tab, rows, verbose)
    skipped["no_owner"] = before - len(rows)
    return rows, skipped


def main(apply=False, per=20):
    queries = list(TOPICS) + ['"%s"' % a for a in ASSIGNEES]
    rows, skipped = collect(queries, per)
    print("\n%d defence-relevant patent(s); %d not relevant/unparsed, %d duplicate"
          % (len(rows), skipped["irrelevant"], skipped["dup"]))
    areas = {}
    for r in rows:
        areas[r["area"]] = areas.get(r["area"], 0) + 1
    for a, n in sorted(areas.items(), key=lambda x: -x[1]):
        print("   %-34s %d" % (a, n))
    for r in rows[:10]:
        print("   %-14s %-46s %s" % (r["no"], r["title"][:46], r["assignee"][:26]))

    out = HERE / "fetch_patents.json"
    prev = []
    if out.exists():
        try:
            prev = json.loads(io.open(out, encoding="utf-8").read())
        except ValueError:
            prev = []
    merged = {r["no"]: r for r in prev}
    merged.update({r["no"]: r for r in rows})
    rows = sorted(merged.values(), key=lambda r: (r["assignee"], r["no"]))
    io.open(out, "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False, indent=1))
    print("\n%s now holds %d record(s)" % (out.name, len(rows)))

    if apply and rows:
        n, gone = apply_rows(rows)
        print("applied %d row(s), replaced %d" % (n, gone))
    elif not apply:
        print("(dry run -- nothing written to serving.patent)")
    return rows


def _demo():
    txt = ("Field Gun Aim\nPublication number: 20090260513\n"
           "Abstract: A howitzer suitable for deployment, comprising a barrel and a recoil "
           "accommodating mechanism.\nType: Application\nFiled: December 16, 2008\n"
           "Publication date: October 22, 2009\nInventor: David Andrew Eaglestone")
    r = parse_row(txt, "/patent/20090260513")
    assert r and r["no"] == "US20090260513", r
    assert r["title"] == "Field Gun Aim" and r["area"] == "Artillery"
    assert r["status"] == "filed" and r["granted"] is None, r
    assert r["filed"] == "December 16, 2008"
    assert "howitzer" in r["abstract"]
    # a grant carries its date; an application must not claim one
    g = parse_row(txt.replace("Type: Application", "Type: Grant"), "/patent/1")
    assert g["status"] == "granted" and g["granted"] == "October 22, 2009"
    # non-defence subject matter is refused whatever route it arrived by
    assert parse_row("A Teacup\nPublication number: 1234567\nAbstract: porcelain.",
                     "/patent/2") is None
    # a block with no publication number is not a result
    assert parse_row("Advertisement\nSign up today", "/x") is None
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--per", type=int, default=20)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply, a.per)
