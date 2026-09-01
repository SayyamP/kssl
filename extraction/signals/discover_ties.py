"""Find partnership ties for every competitor, from the corpus, in one pass.

    python discover_ties.py --dry
    python discover_ties.py --apply
    python discover_ties.py --demo

The tab lists 28 competitors and 16 of them showed no partner at all. The archive
could not help -- it holds the Indian domestic ecosystem, and 130 of its 150 ties
have no supporting document. But the corpus does talk about these companies, and
what it says about them is what the tab is for.

So this reads the documents rather than the archive. Every organisation we already
know of -- competitors, the client, its roster, every partner named anywhere --
becomes a name to look for. A document that names two of them within one sentence
of each other, with a relationship word between them, states a tie; the sources
then clear the same bar as everything else on the page (the company's own site or
a government publisher, or two independent domains).

One pass over the corpus, not one per pair: positions for every known name are
found once per document, and the pairs are read off those positions. 200 names
over 1,300 documents is a minute; the pairwise form would have been a day.

What it does NOT do is invent a partner. A company the vocabulary has never heard
of cannot be discovered here -- that needs entity recognition, and a name nobody
has ever written down is exactly where a hallucination would come from.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from source_tiers import domain as st_domain, publishable          # noqa: E402
from revive_matchups import load_docs, norm, index_df, DF, COMMON  # noqa: E402
from revive_partners import (ALIAS, FORCE_RX, REL_RX, STRONG_RX, PROX,  # noqa: E402
                             acronyms, head_org, name_tokens, rare_tokens,
                             find_at, slug, whole_at, same_company)
from mark_shared import Orgs                                       # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
DISC_ORD0 = 3000        # this writer's own range in serving.partner
MAX_TIES = 12           # per competitor, strongest first -- the graph draws 16
PROX_DISC = 250         # tighter than the archive reviver's 400: there is no
                        # recorded tie behind this one, the sentence is all of it
REL_PTYPE = {"jv": "Joint venture", "tech": "Technology / ToT",
             "supply": "Supply / customer", "mou": "MoU / strategic",
             "acq": "Acquisition / stake", "other": "Partnership"}
# what the sentence says the relationship IS, read from the word that matched
REL_OF = [("jv", re.compile(r"joint venture|\bjv\b|\bjvc\b")),
          ("mou", re.compile(r"\bmou\b|memorandum of understanding|alliance")),
          ("acq", re.compile(r"acquir|stake in|majority stake")),
          ("tech", re.compile(r"co-develop|co develop|licen[cs]|technology transfer|"
                              r"transfer of technology|\btot\b|collaborat|teaming")),
          ("supply", re.compile(r"suppl|subcontract|components for|manufactur"))]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Neither side of a partnership is a ministry, a service or an investment vehicle.
# The archive files those as partners; they are the customer or the money.
NOT_A_COMPANY = re.compile(r"\b(ministry|minist[eè]re|government|investment fund|"
                           r"joint investment|sovereign fund|department of defen|"
                           r"parliament|cabinet|secretariat)")


def rel_of(window):
    for rel, rx in REL_OF:
        if rx.search(window):
            return rel
    return "other"


def sentence_at(text, lo_pos, hi_pos=None, width=90):
    """The passage that holds BOTH mentions, trimmed to something quotable.

    A window around the midpoint instead produced quotes that named neither
    company -- a stock ticker in one case -- which is a citation a reader cannot
    check."""
    hi_pos = lo_pos if hi_pos is None else hi_pos
    lo = max(0, lo_pos - width)
    hi = min(len(text), hi_pos + width)
    frag = text[lo:hi]
    # start after the first sentence break, end at the last one, so the quote is
    # not a fragment beginning mid-word
    a = frag.find(". ")
    b = frag.rfind(". ")
    if 0 <= a < b:
        frag = frag[a + 2: b + 1]
    return " ".join(frag.split())[:300]


class Vocab:
    """Every organisation we know of, and the strings it is written as.

    Keyed by ORGANISATION, not by label: the corpus writes DRDO four different
    ways, and keying on the label listed all four as separate partners of the same
    competitor. Clustering is `mark_shared.Orgs`, the same one the red line uses,
    so a tie discovered here and a tie revived from the archive carry one id."""

    def __init__(self):
        self.orgs = Orgs()
        self.surf = {}       # key -> [surface, ...]
        self.label = {}      # key -> display label
        self.toks = {}       # key -> whole-name tokens (>= 2 means "name must be whole")
        self._pending = []

    def add(self, key, label, aliases=()):
        """Collected now, keyed on finish(): a cluster is only known once every
        label has been seen."""
        if label:
            self._pending.append((key, label, tuple(aliases)))

    def _key(self, label):
        return self.orgs.key(label)

    def _install(self, key, label, aliases=()):
        if not key or not label:
            return
        head = head_org(label)
        # Discovery is the lowest-evidence path on the page, so it takes the
        # strictest name test: three-letter acronyms are the false-positive machine
        # ("STV" was found in five companies' documents and quoted in none of them).
        surfaces = [s for s in (list(aliases) + acronyms(head)) if s and len(s) >= 4]
        self.surf.setdefault(key, [])
        for s in surfaces:
            if s not in self.surf[key]:
                self.surf[key].append(s)
        self.label.setdefault(key, label)
        if len(label) < len(self.label[key]):
            self.label[key] = label
        toks = name_tokens(head)
        # the whole-name test uses the SHORTEST form; a longer variant of the same
        # company would otherwise demand tokens the corpus never writes together
        if key not in self.toks or 0 < len(toks) < len(self.toks[key]):
            self.toks[key] = toks

    def finish(self, docs, pinned=()):
        """Cluster the labels, then add the single-token surfaces the corpus says
        are distinctive."""
        for key, label, aliases in self._pending:
            pin = key if key in pinned else None
            self.orgs.add(label, prefer_id=pin)
            # an alias is another NAME for the same organisation, so it has to join
            # the same cluster -- otherwise the client's own parent ("Bharat Forge")
            # is discovered as one of its partners
            for al in aliases:
                self.orgs.add(al, prefer_id=pin)
        self.orgs.finalise()
        for key, label, aliases in self._pending:
            k = self._key(label)
            if k:
                self._install(k, label, aliases)
        index_df(docs, [t for ts in self.toks.values() for t in ts])
        for k, ts in self.toks.items():
            # ONE word may stand for a company only when the company IS one word.
            # "Indo-Russian Rifles" was found in the phrase "the indo-russian joint
            # venture BrahMos" -- on the word `indo`, which names nobody. A
            # multi-word name has to appear whole, or as its acronym.
            if len(ts) != 1:
                continue
            if DF.get(ts[0], 1.0) < 0.15 and ts[0] not in self.surf[k]:
                self.surf[k].append(ts[0])

    def mask(self, win, *keys):
        """Blank out these organisations' names, so only the words AROUND them can
        state the relationship."""
        for k in keys:
            for sfc in [norm(head_org(self.label.get(k, "")))] + list(self.surf.get(k, ()))                     + list(self.toks.get(k, ())):
                if sfc and len(sfc) >= 3:
                    win = win.replace(sfc, " " * len(sfc))
        return win

    def names_in(self, text, key):
        """Is this organisation named in this passage?"""
        if find_at(text, self.surf.get(key, ())) >= 0:
            return True
        toks = self.toks.get(key, [])
        return len(toks) >= 2 and whole_at(text, toks) >= 0

    def positions(self, text):
        """-> {key: position}. First mention only; that is the anchor."""
        out = {}
        for k, surfaces in self.surf.items():
            i = find_at(text, surfaces)
            if i < 0 and len(self.toks[k]) >= 2:
                i = whole_at(text, self.toks[k])
            if i >= 0:
                out[k] = i
        return out


def build_vocab(cur, docs):
    v = Vocab()
    cur.execute("""SELECT comp_id, name, dir FROM serving.competitors
                    WHERE origin='pipeline'""")
    live = {}
    client = None
    for cid, name, direction in cur.fetchall():
        live[cid] = name
        if direction == "client":
            client = cid
        v.add(cid, name, ALIAS.get(cid, ()))
    # the archive's own company list and every partner label anyone has recorded
    cur.execute("SELECT comp_id, name, partners FROM serving.competitors")
    for cid, name, partners in cur.fetchall():
        pl = partners if isinstance(partners, list) else json.loads(partners or "[]")
        for p in pl:
            lab = p.get("label")
            if lab:
                v.add(slug(head_org(lab)), lab)
        if cid not in live:
            v.add(slug(name), name, ALIAS.get(cid, ()))
    cur.execute("SELECT label FROM serving.partner")
    for (lab,) in cur.fetchall():
        v.add(slug(head_org(lab)), lab)
    cur.execute("SELECT id, name FROM serving.geo_comp WHERE name IS NOT NULL")
    for gid, name in cur.fetchall():
        v.add(slug(name), name)
    v.finish(docs, pinned=set(live))
    return v, live, client


# A page that names this many organisations is a directory, an exhibitor list or an
# equipment index -- every pair in it is adjacent to the word "partner" and none of
# them is a story about a partnership.
LIST_PAGE = 10


def collect(docs, v, live, client):
    """-> {(a, b): [(url, rel, quote, strong)]} for pairs touching a live company."""
    interesting = set(live)
    pairs = {}
    for _did, url, text in docs:
        pos = v.positions(text)
        if len(pos) < 2 or len(pos) > LIST_PAGE:
            continue
        keys = sorted(pos, key=lambda k: pos[k])
        for x in range(len(keys)):
            for y in range(x + 1, len(keys)):
                a, b = keys[x], keys[y]
                if a not in interesting and b not in interesting:
                    continue
                i, j = pos[a], pos[b]
                if j - i > PROX_DISC:
                    break
                if same_company(v.label[a], v.label[b]):
                    continue
                if any(FORCE_RX.search(norm(v.label[k])) or
                       NOT_A_COMPANY.search(norm(v.label[k])) for k in (a, b)):
                    continue
                win = text[max(0, i - 120): j + 120]
                # A name is not a relationship. "Javelin Joint Venture" carries the
                # words "joint venture" inside it, and matched as a partner of six
                # different companies on the strength of its own label.
                masked = v.mask(win, a, b)
                if not REL_RX.search(masked):
                    continue
                # Discovery has no archive row behind it, so the sentence has to
                # STATE the tie: "signed", "joint venture", "acquired". A page that
                # merely uses the word "partners" near two companies is how an
                # exhibitor list becomes an alliance.
                if not STRONG_RX.search(masked):
                    continue
                pairs.setdefault((a, b), []).append(
                    (url, rel_of(masked), sentence_at(text, i, j),
                     bool(STRONG_RX.search(masked)), j - i))
    return pairs


def judge(pairs, v):
    """-> [{a, b, rel, note, src, srcnote, n}] for pairs that clear the source bar."""
    out = []
    for (a, b), hits in pairs.items():
        best_by_dom = {}
        for url, rel, quote, strong, dist in hits:
            d = st_domain(url)
            rank = (0 if strong else 1, dist)
            if d not in best_by_dom or rank < best_by_dom[d][0]:
                best_by_dom[d] = (rank, url, rel, quote)
        best = sorted(best_by_dom.values())
        ok, why, _t, n = publishable([u for _r, u, _rel, _q in best], v.label[a])
        if not ok:
            ok, why, _t, n = publishable([u for _r, u, _rel, _q in best], v.label[b])
        if not ok:
            continue
        _rank, url, rel, quote = best[0]
        # The stored quote IS the citation a reader checks. If the trimming left a
        # passage that does not name both parties, the tie may still be real but
        # this page cannot show why -- and an unverifiable line is what the archive
        # was full of.
        if not (v.names_in(quote, a) and v.names_in(quote, b)):
            continue
        out.append({"a": a, "b": b, "rel": rel, "note": quote, "src": url,
                    "srcnote": why, "n": n, "strong": best[0][0][0] == 0})
    return out


def entries(found, v, live, client):
    """-> {comp_id: [tie, ...]}, strongest first, capped."""
    by = {}
    for f in found:
        for side, other in ((f["a"], f["b"]), (f["b"], f["a"])):
            if side not in live:
                continue
            by.setdefault(side, []).append({
                "id": other, "cid": other, "label": v.label[other],
                "rel": f["rel"], "ptype": REL_PTYPE.get(f["rel"], "Partnership"),
                "note": f["note"], "date": None, "country": None,
                "src": f["src"], "srcnote": f["srcnote"], "origin": "discovered",
                "_rank": (0 if f["strong"] else 1, -f["n"]),
            })
    for cid, lst in by.items():
        lst.sort(key=lambda t: t["_rank"])
        seen, keep = set(), []
        for t in lst:
            if t["cid"] in seen:
                continue
            seen.add(t["cid"])
            t.pop("_rank", None)
            keep.append(t)
        by[cid] = keep[:MAX_TIES]
    return by


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    v, live, client = build_vocab(cur, docs)
    print("%d document(s), %d known organisation(s), %d live competitor(s)"
          % (len(docs), len(v.surf), len(live)))
    pairs = collect(docs, v, live, client)
    print("%d co-mentioned pair(s) with a relationship word" % len(pairs))
    found = judge(pairs, v)
    print("%d clear the source bar\n" % len(found))
    by = entries(found, v, live, client)
    for cid in sorted(by, key=lambda k: -len(by[k])):
        print("\n  %s (%d)" % (cid, len(by[cid])))
        for t in by[cid]:
            print("    %-30s %-26s %s" % (t["label"][:30], t["srcnote"][:26],
                                          st_domain(t["src"])))
            print("      \"%s\"" % t["note"][:200])
    covered = len(by)
    print("\n%d of %d competitors now have at least one tie" % (covered, len(live)))

    if apply:
        for cid in live:
            cur.execute("SELECT partners FROM serving.competitors WHERE comp_id=%s "
                        "AND origin='pipeline'", (cid,))
            row = cur.fetchone()
            cur_list = row[0] if row and isinstance(row[0], list) else json.loads(
                (row[0] if row else None) or "[]")
            kept = [p for p in cur_list if p.get("origin") != "discovered"]
            have = {p.get("cid") or slug(p.get("label") or "") for p in kept}
            merged = kept + [t for t in by.get(cid, []) if t["cid"] not in have]
            cur.execute("""UPDATE serving.competitors SET partners=%s, updated_at=now()
                            WHERE comp_id=%s AND origin='pipeline'""",
                        (json.dumps(merged), cid))
        con.commit()
        print("\napplied.")
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return by


def _demo():
    DF.update({"hanwha": 0.002, "rheinmetall": 0.01, "leonardo": 0.02})
    t = norm("Rheinmetall and Leonardo have signed a joint venture to produce the "
             "Panther for the Italian Army.")
    docs = [("d1", "https://rheinmetall.com/x", t), ("d2", "https://euro-sd.com/y", t)]
    v = Vocab()
    v.add("rheinmetall", "Rheinmetall")
    v.add("leonardo", "Leonardo")
    v.add("javelin", "Javelin Joint Venture")
    v.finish(docs, pinned={"rheinmetall", "leonardo"})
    pairs = collect(docs, v, {"rheinmetall": "Rheinmetall"}, None)
    assert len(pairs) == 1, pairs
    got = judge(pairs, v)
    assert got and got[0]["rel"] == "jv", got
    assert "joint venture" in got[0]["note"], got[0]["note"]
    # the quote has to hold BOTH companies, or it is not evidence of a tie
    assert "rheinmetall" in got[0]["note"] and "leonardo" in got[0]["note"], got[0]["note"]
    # two companies in one document but far apart are not a tie
    far = norm("Rheinmetall won the order. " + ("filler " * 90)
               + " Leonardo signed a joint venture with somebody else.")
    assert collect([("d3", "https://a.com/x", far)], v,
                   {"rheinmetall": "Rheinmetall"}, None) == {}
    # ...and neither is a document that names both without stating a relationship
    both = norm("Rheinmetall and Leonardo both exhibited at the show in Paris.")
    assert collect([("d4", "https://a.com/x", both)], v,
                   {"rheinmetall": "Rheinmetall"}, None) == {}
    # a single source does not publish
    one = judge({("rheinmetall", "leonardo"):
                 [("https://euro-sd.com/y", "jv", "rheinmetall and leonardo signed a joint venture", True, 20)]}, v)
    assert one == [], one
    # ...but the company's own site does
    own = judge({("rheinmetall", "leonardo"):
                 [("https://rheinmetall.com/x", "jv", "rheinmetall and leonardo signed a joint venture", True, 20)]}, v)
    assert own and own[0]["srcnote"].startswith("stated by an official"), own
    # a company whose NAME contains "joint venture" does not thereby have one
    jv = norm("Rheinmetall showed the Panther beside a Javelin Joint Venture stand.")
    assert collect([("d5", "https://a.com/x", jv), ("d6", "https://b.com/y", jv)], v,
                   {"rheinmetall": "Rheinmetall"}, None) == {}, "name read as a relationship"
    # ...and a ministry is the customer, not a partner
    assert NOT_A_COMPANY.search("ministry of defence") is not None
    assert NOT_A_COMPANY.search("oman india joint investment fund") is not None
    # a citation that does not name both parties is not a citation
    trimmed = judge({("rheinmetall", "leonardo"):
                     [("https://rheinmetall.com/x", "jv",
                       "signed a joint venture at the show", True, 20)]}, v)
    assert trimmed == [], trimmed
    # the relationship word decides the kind
    assert rel_of("signed a memorandum of understanding") == "mou"
    assert rel_of("acquired a majority stake in") == "acq"
    assert rel_of("will supply components for") == "supply"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
