"""Find which markets each competitor operates in, from the corpus.

    python discover_geo.py --dry
    python discover_geo.py --apply
    python discover_geo.py --demo

The Geo tab plots 29 companies and 14 of them have no country at all, so the map
cannot answer the question it exists for: where does a rival meet KSSL. The
archive is exhausted -- revive_geo already republished everything it could source
-- so this reads the documents instead.

A market is claimed when a document we hold names the company and the country in
the same passage AND says what the company DOES there: exports to it, produces in
it, services in it, has a partner in it. Presence without an activity is not a
market -- "Rheinmetall" beside "India" in an article about an Indian tender says
nothing about Rheinmetall operating in India, and that sentence is most of a
defence corpus.

Activities use the same four codes the tab already draws (ex / lp / sv / pt), and
every row carries the sentence and the URL it came from.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _superseded import refuse_if_superseded  # noqa: E402
refuse_if_superseded(__file__)   # this copy is superseded; see the module
import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from source_tiers import domain as st_domain, publishable            # noqa: E402
from revive_matchups import load_docs, norm, index_df, DF            # noqa: E402
from revive_geo import ALIASES, country_forms, find_at, slug         # noqa: E402
from revive_partners import (ALIAS, acronyms, head_org,             # noqa: E402
                             name_tokens, whole_at)
from discover_ties import sentence_at, LIST_PAGE                     # noqa: E402
from mark_shared import Orgs                                         # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
PROX = 250            # the country has to be in the same passage as the company
GEO_ORD0 = 3000       # this writer's own range; revive_geo owns 2000-2999
MAX_PER_CO = 12
# What the company DOES there. Ordered: the first that matches names the activity.
ACTS = [
    ("lp", re.compile(r"produc(e|es|ed|tion)|manufactur|assembl(e|es|ed|y)|"
                      r"\bplant\b|factory|facility|localis|localiz|made in")),
    ("sv", re.compile(r"\bmro\b|maintenance|overhaul|servicing|service centre|"
                      r"service center|support centre|repair")),
    ("pt", re.compile(r"joint venture|\bjv\b|\bmou\b|partner|licen[cs]|"
                      r"technology transfer|transfer of technology|\btot\b")),
    ("ex", re.compile(r"export|deliver|supplie[sd]|supply to|shipped|sold to|"
                      r"order from|contract with|selected by|inducted")),
]
ACT_RX = re.compile("|".join(p.pattern for _c, p in ACTS))
# geo_presence.name is NOT NULL and is what the row is called on the map. An
# archive row names a PRODUCT there; a discovered row has no product, so it is
# named after the activity the document states -- never left blank, never invented.
ACT_NAME = {"lp": "Local production", "ex": "Export / supply",
            "sv": "Service / MRO", "pt": "Partnership / licence"}
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# The country has to be the OBJECT of the activity, not merely a word beside it.
# "a french-canadian pioneer in airships" and "the South African Paramount Group"
# both put a country next to a partnership word, and neither says the company
# operates there -- one describes the PARTNER's nationality.
PREP_RX = re.compile(r"\b(in|into|to|for|from|across|throughout|within|at)\s*$")


def find_all(text, needles, limit=24):
    """Every whole-word position of any of these surfaces, in order.

    find_at() returns the FIRST mention only, and the first mention of a country is
    routinely the wrong one: Hanwha's own page names Europe in a product title
    before it says "first production site in Europe", so testing only the first
    threw away the sentence that proves the market."""
    out = []
    for n in needles or ():
        i = text.find(n)
        while i != -1 and len(out) < limit:
            before = text[i - 1] if i else " "
            after = text[i + len(n)] if i + len(n) < len(text) else " "
            if not (before.isalnum() or after.isalnum()):
                out.append(i)
            i = text.find(n, i + 1)
    return sorted(set(out))


def act_of(window):
    for code, rx in ACTS:
        if rx.search(window):
            return code
    return None


def surfaces_for(name, cid, aliases=()):
    """The strings this company is written as. Same rule as the tie finder: an
    acronym, the whole name, or one token when the corpus says that token is
    distinctive on its own."""
    head = head_org(name)
    out = [s for s in (list(aliases) + acronyms(head)) if s and len(s) >= 4]
    toks = name_tokens(head)
    if len(toks) == 1 and DF.get(toks[0], 1.0) < 0.15:
        out.append(toks[0])
    return out, toks


def find_markets(docs, name, cid, countries, aliases=(), max_domains=4):
    """-> {country: [(url, act, quote, strong)]}"""
    surf, toks = surfaces_for(name, cid, aliases)
    if not surf and len(toks) < 2:
        return {}
    out = {}
    for _did, url, text in docs:
        i = find_at(text, surf)
        if i < 0 and len(toks) >= 2:
            i = whole_at(text, toks)
        if i < 0:
            continue
        near = []
        for ct in countries:
            for j in find_all(text, country_forms(ct)):
                if abs(i - j) <= PROX:
                    near.append((ct, j))
        # A page that puts eight countries beside the company is a headline index or
        # an export table, not a story about a market. BrahMos's own news column
        # produced "Vietnam" from a list of unrelated headlines.
        if not near or len({ct for ct, _j in near}) > 6:
            continue
        for ct, j in near:
            lo, hi = min(i, j), max(i, j)
            win = text[max(0, lo - 120): hi + 120]
            if not PREP_RX.search(text[max(0, j - 24): j]):
                continue                      # "in India", not "Indian company"
            act = act_of(text[max(0, j - 140): j])
            if not act:
                continue
            quote = sentence_at(text, i, j)
            # the citation has to show what it claims: both the company and the
            # country, in the passage a reader will actually see
            if find_at(quote, country_forms(ct)) < 0:
                continue
            if find_at(quote, surf) < 0 and not (len(toks) >= 2
                                                 and whole_at(quote, toks) >= 0):
                continue
            out.setdefault(ct, []).append((url, act, quote, win))
    return out


def judge(found, name, max_domains=3):
    """-> [{country, c, note, src, srcnote}] for markets that clear the source bar."""
    rows = []
    for ct, hits in found.items():
        by_dom, acts = {}, {}
        for url, act, quote, _win in hits:
            d = st_domain(url)
            acts[act] = acts.get(act, 0) + 1
            if d not in by_dom:
                by_dom[d] = (url, act, quote)
        ok, why, _t, _n = publishable([u for u, _a, _q in by_dom.values()], name)
        if not ok:
            continue
        url, act, quote = list(by_dom.values())[0]
        # the activity the sources agree on most often, not the first one seen
        act = max(acts, key=lambda a: acts[a])
        rows.append({"country": ct, "c": act, "note": quote, "src": url,
                     "srcnote": why, "n": len(by_dom)})
    return rows


def sync_geo_comps(cur, comps):
    """Every competitor gets a company row on the map, and each company gets ONE.

    The map joins geoData[id] to geoComps[id], so a competitor with no geo_comp row
    cannot be plotted however many presence rows it has -- and a company recorded
    twice under two ids (`adani-defence` and `adani-defence-aerospace`,
    `larsen-toubro` and `l-t`) splits its own footprint in half. Both are the same
    fault: one company, two ids."""
    cur.execute("""SELECT id, name, origin FROM serving.geo_comp""")
    rows = cur.fetchall()
    orgs = Orgs()
    for c in comps:
        orgs.add(c["name"], prefer_id=c["cid"])
        # "L&T" reduces to two one-letter tokens, so it shares nothing with the map's
        # own row for "Larsen & Toubro" and the company held two ids on one map.
        for al in ALIAS.get(c["cid"], ()):
            orgs.add(al, prefer_id=c["cid"])
    for gid, name, _o in rows:
        orgs.add(name or gid)
    orgs.finalise()

    made, moved = 0, 0
    for c in comps:
        cur.execute("""INSERT INTO serving.geo_comp (id, ord, name, dir, hq, "isBf", origin)
                       VALUES (%s,%s,%s,%s,%s,%s,'pipeline')
                       ON CONFLICT (id) DO UPDATE
                         SET name = excluded.name,
                             hq = coalesce(serving.geo_comp.hq, excluded.hq),
                             "isBf" = excluded."isBf" """,
                    (c["cid"], GEO_ORD0 + len(comps), c["name"], c["dir"] or "watch",
                     c["hq"], c["dir"] == "client"))
        made += cur.rowcount
    live = {c["cid"] for c in comps}
    for gid, name, origin in rows:
        if gid in live:
            continue
        target = orgs.key(name or gid)
        if not target or target not in live or target == gid:
            continue
        # fold the duplicate's presence rows onto the competitor's own id
        cur.execute("""UPDATE serving.geo_presence SET comp_id=%s
                        WHERE comp_id=%s AND origin='pipeline'""", (target, gid))
        moved += cur.rowcount
        cur.execute("DELETE FROM serving.geo_comp WHERE id=%s AND origin='pipeline'",
                    (gid,))
    return made, moved


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    cur.execute("""SELECT comp_id, name, dir, hq FROM serving.competitors
                    WHERE origin='pipeline' ORDER BY ord""")
    comps = [{"cid": r[0], "name": r[1], "dir": r[2], "hq": r[3]} for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT country FROM serving.geo_presence "
                "WHERE country IS NOT NULL")
    countries = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT value FROM serving.ui_config WHERE key='geoCountries'")
    row = cur.fetchone()
    vocab = row[0] if row and isinstance(row[0], list) else json.loads((row and row[0]) or "[]")
    countries = sorted(set(vocab) | set(countries))
    print("%d document(s), %d competitor(s), %d country name(s)"
          % (len(docs), len(comps), len(countries)))
    index_df(docs, [t for c in comps for t in name_tokens(head_org(c["name"]))])

    out, empty = {}, []
    for c in comps:
        found = find_markets(docs, c["name"], c["cid"], countries,
                             ALIAS.get(c["cid"], ()))
        rows = judge(found, c["name"])[:MAX_PER_CO]
        if rows:
            out[c["cid"]] = rows
        else:
            empty.append(c["cid"])
    print("%d competitor(s) have a sourced market, %d have none\n"
          % (len(out), len(empty)))
    for cid in sorted(out, key=lambda k: -len(out[k])):
        print("\n  %s" % cid)
        for r in out[cid]:
            print("    %-14s %-3s %-26s %s" % (r["country"], r["c"],
                                               r["srcnote"][:26], st_domain(r["src"])))
            print("      \"%s\"" % r["note"][:190])
    print("\nno market found: %s" % ", ".join(sorted(empty)))

    if apply:
        made, moved = sync_geo_comps(cur, comps)
        print("\ncompany rows on the map: %d written, %d duplicate row(s) folded in"
              % (made, moved))
        cur.execute("DELETE FROM serving.geo_presence WHERE origin='pipeline' "
                    "AND ord >= %s", (GEO_ORD0,))
        n = 0
        for ci, (cid, rows) in enumerate(sorted(out.items())):
            for ri, r in enumerate(rows):
                cur.execute("""INSERT INTO serving.geo_presence
                    (comp_id, comp_ord, country, country_ord, ord, name, c, val,
                     since, qty, stage, note, src, srcnote, origin)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,%s,%s,%s,
                            'pipeline')""",
                            (cid, GEO_ORD0 + ci, r["country"], ri, GEO_ORD0 + n,
                             ACT_NAME.get(r["c"], "Activity"),
                             r["c"], r["note"], r["src"], r["srcnote"]))
                n += 1
        con.commit()
        print("\napplied %d market row(s)." % n)
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return out


def _demo():
    DF.update({"rheinmetall": 0.01, "denel": 0.01})
    t = norm("Rheinmetall will produce 155 mm ammunition at a new plant in Ukraine "
             "under a joint venture announced this year.")
    docs = [("d1", "https://rheinmetall.com/x", t), ("d2", "https://euro-sd.com/y", t)]
    got = find_markets(docs, "Rheinmetall", "rheinmetall", ["Ukraine", "India"])
    assert "Ukraine" in got and "India" not in got, got
    rows = judge(got, "Rheinmetall")
    assert rows and rows[0]["c"] == "lp", rows
    # co-mention is not a market: the company and the country in one sentence with
    # nothing said about what it does there
    bare = norm("Rheinmetall was mentioned alongside India in the annual review.")
    assert judge(find_markets([("d3", "https://a.com/1", bare),
                               ("d4", "https://b.com/2", bare)],
                              "Rheinmetall", "rheinmetall", ["India"]),
                 "Rheinmetall") == []
    # a single uncorroborated news page does not publish
    assert judge(find_markets([("d5", "https://euro-sd.com/y", t)], "Rheinmetall",
                              "rheinmetall", ["Ukraine"]), "Rheinmetall") == []
    # the country has to be near the company, not merely in the same document
    far = norm("Denel makes the G5. " + ("filler " * 90) + " India bought guns.")
    assert find_markets([("d6", "https://a.com/1", far)], "Denel", "denel",
                        ["India"]) == {}
    # the country must be the object of the activity, not a nationality
    nat = norm("Bharat Forge signed an MoU with Flying Whales, a french company.")
    assert judge(find_markets([("d7", "https://a.com/1", nat),
                               ("d8", "https://b.com/2", nat)],
                              "Bharat Forge", "bf", ["France"]), "Bharat Forge") == []
    # the activity code is the one the sources agree on
    assert act_of(norm("will export to")) == "ex"
    assert act_of(norm("opened a maintenance and overhaul centre")) == "sv"
    print("ok")


if __name__ == "__main__":

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
