"""Fetch the SECOND witness for values Positioning already found.

    python _corrob_fetch.py --plan
    python _corrob_fetch.py --limit 40
    python _corrob_fetch.py --demo

29 range/weight/crew values are located and held back for one reason: a single
domain carries them, and one news page is not enough to publish a number about a
real weapon. This does not need another search for the value -- it needs a
publisher we do not already hold.

Two targets, in order of what actually clears the bar:
  1. the PRODUCT'S OWN MAKER. One official source is sufficient on its own, so a
     single maker page publishes the value outright.
  2. a specialist registry we do not already have for this product. Two
     independent domains clear the bar together.

Queries are site-restricted, because a general search returns the same Wikipedia
page we are trying to corroborate.
"""
import argparse
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "l2" / "comprehend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fetch_for_products as F                                # noqa: E402
from _fieldwork import FIELD_Q                                # noqa: E402
from source_tiers import MAKER_DOMAINS, _same_org             # noqa: E402

# Registries worth trying for a second witness, most spec-table-dense first.
REGISTRIES = ["armyrecognition.com", "militaryfactory.com", "army-technology.com",
              "military-today.com", "weaponsystems.net", "globalsecurity.org",
              "deagel.com", "tanks-encyclopedia.com", "defenceweb.co.za"]
TRIES = 3          # site-restricted searches per value before giving up


def maker_domain(maker):
    """The product maker's own domain, if we recognise it."""
    for d, name in MAKER_DOMAINS.items():
        if _same_org(name, maker or ""):
            return d
    return None


def targets(entry):
    """-> [domain] to try, best first, skipping what we already hold."""
    have = set(entry.get("have") or [])
    out = []
    md = maker_domain(entry.get("maker"))
    if md and md not in have:
        out.append(md)                      # one official source is enough on its own
    out.extend(d for d in REGISTRIES if d not in have)
    return out


def queries(e):
    """Search strings, best first.

    The first round asked `site:X <maker> <product>` and staged a page from every
    single target -- and corroborated nothing, because "a page about this product"
    is not "a page stating this number". The VALUE has to be in the query: a search
    for "K9 Thunder 47 tonnes" finds the sentence we need to cite, wherever it is.
    """
    fq = FIELD_Q.get(e["field"], e["field"])
    val = str(e.get("value") or "").strip()
    out = []
    if val:
        out.append("%s %s %s" % (e["product"], val, fq))
    out.append("%s %s %s" % (e["maker"], e["product"], fq))
    for dom in targets(e)[:2]:
        out.append("site:%s %s %s" % (dom, e["product"], fq))
    return out


def run(limit=None, verbose=True, src=None):
    from segment import detect_lang
    work = json.loads((HERE / (src or "corroborate.json")).read_text(encoding="utf-8"))
    state = F._state()
    st = state["st"]
    print("%d value(s) one domain short\n" % len(work), flush=True)
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for e in work:
            if limit and st["searched"] >= limit:
                break
            got = 0
            have_doms = set(e.get("have") or [])
            for q in queries(e)[:TRIES + 1]:
                st["searched"] += 1
                hits = [u for u in F.search(q.strip())
                        if F.credible(u) and F.doc_id(u) not in state["have"]
                        and urlsplit(u).netloc.lower().replace("www.", "")
                        not in have_doms]
                for u in F.pick(hits, 3):
                    if F.stage(client, u, state,
                               "corroborate(%s / %s)" % (e["product"], e["field"]),
                               "%s %s" % (e["product"], e["field"]), detect_lang):
                        got += 1
                if got:
                    break                   # one new publisher is what was missing
                time.sleep(0.8)
            if verbose:
                print("  %-22s %-14s +%d page(s)   had: %s"
                      % (e["product"][:22], e["field"][:14], got,
                         ",".join(e["have"])[:34]), flush=True)
    print("\nsearched %d query(ies): +%d page(s) staged, %d dup, %d thin, %d error, "
          "%d already held" % (st["searched"], st["new"], st["dup"], st["thin"],
                               st["err"], st["have"]))
    return st


def _demo():
    assert maker_domain("KNDS") == "knds.com" or maker_domain("KNDS").startswith("knds")
    assert maker_domain("Bharat Forge") == "bharatforge.com"
    # the client group is one company, so a KSSL product targets Bharat Forge's site
    assert maker_domain("Kalyani Strategic Systems") is not None
    assert maker_domain("Nobody Ltd") is None
    # a domain we already hold is not a second witness
    t = targets({"maker": "KNDS", "have": ["knds.com", "armyrecognition.com"]})
    assert "knds.com" not in t and "armyrecognition.com" not in t
    assert t[0] in REGISTRIES
    # the maker comes first when we do not have it
    t2 = targets({"maker": "KNDS", "have": ["en.wikipedia.org"]})
    assert t2[0].startswith("knds")
    # the VALUE leads the query: a page about the product is not a page stating it
    qs = queries({"product": "K9 Thunder", "maker": "Hanwha", "field": "Weight",
                  "value": "47", "have": ["en.wikipedia.org"]})
    assert "47" in qs[0] and "K9 Thunder" in qs[0], qs[0]
    assert any(q.startswith("site:") for q in qs)
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--src", default=None, help="corroborate.json | halves.json")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.plan:
        for e in json.loads((HERE / (a.src or "corroborate.json")).read_text(encoding="utf-8")):
            print("  %-22s %-14s -> %s" % (e["product"][:22], e["field"][:14],
                                           ", ".join(targets(e)[:TRIES])))
    else:
        run(a.limit, src=a.src)
