"""Re-publish archived partnership ties, with real provenance or not at all.

    python revive_partners.py --dry
    python revive_partners.py --apply
    python revive_partners.py --demo

The Partnerships tab serves 6 ties across 23 rivals. The archive holds 150 rival
ties over 28 companies plus an 11-row client roster -- and not one of them carries
a source. They were written by hand, and the `mean` / `insight` columns are
KSSL-specific judgement, not a claim a document can support.

So this republishes the FACT of a tie, never the reading of it: label, kind,
relationship, note, date, country -- and only when a document we hold names BOTH
companies close together with a relationship word between them, from sources that
clear the same bar Positioning uses (the company's own site or a government
publisher, or two independent domains). The analysis prose stays archived.

Both companies must be named. "L&T is building artillery" is not evidence of an
L&T-Hanwha tie, and the archive's own note is not evidence of anything.
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
from source_tiers import domain as st_domain, publishable      # noqa: E402
from revive_matchups import (load_docs, norm, index_df, DF,     # noqa: E402
                             COMMON)
from revive_geo import (company_at, find_at, slug, CO_GENERIC)  # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
PROX = 400           # a sentence or its neighbour, not one article
                     # (the K9 Vajra tie sits 275 characters apart in L&T's own
                     #  press release: "adapted from ... k9 thunder, is
                     #  co-developed by l&t and hanwha aerospace")
REV_ORD0 = 2000      # this writer's own ord range; enrich_serving owns 1000-1999
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A tie is a stated relationship, not two companies in one article. Both are
# named in the same defence story constantly -- as rival bidders, as two lines in
# a procurement list -- so the relationship word is what separates a partnership
# from a coincidence.
REL_RX = re.compile(
    r"(joint venture|\bjv\b|\bmou\b|memorandum of understanding|partner|"
    r"partnership|alliance|teaming|team(ed|s) with|agreement|collaborat|"
    r"co-develop|co develop|licen[cs]|consortium|tie-up|tie up|acquir|"
    r"stake in|contract (to|for) suppl|supplies|supplier|subcontract|"
    r"selected .{0,40}to suppl|signed with)")

# Words that state the tie outright, as against ones that only imply it. Used to
# order the evidence, not to gate it: the citation should be the sentence a reader
# can check, not merely the first page that matched.
STRONG_RX = re.compile(r"(joint venture|\bjv\b|\bmou\b|memorandum|agreement|"
                       r"acquir|licen|co-develop|co develop|consortium|stake in|"
                       r"signed|partnered with|partnership with|partnership between|"
                       r"partners with|in partnership with)")

# Acronyms that are ordinary words. An archive id is a filing code ("ALPHA",
# "FORCE", "SPART"), and matching those as whole words would ground a tie on any
# sentence containing "alpha" -- which is not a company.
CODE_STOP = {"alpha", "force", "delta", "eagle", "omega", "vista", "orbit",
             "arm", "air", "gun", "sea", "war", "act", "all", "the", "and",
             "core", "prime", "apex", "titan", "shield", "storm", "viper"}


# The archive names companies the way a filing system does -- a short code and an
# abbreviated name. The corpus names them the way journalists do. Where the two do
# not meet, the surface forms are listed rather than guessed at: "L&T" reduces to
# two one-letter tokens and matched NOTHING in 1,318 documents.
ALIAS = {
    "LT": ["larsen & toubro", "larsen and toubro", "larsen toubro", "l&t"],
    # keyed by the ARCHIVE code above and by the LIVE competitor id here: the two id
    # spaces meet in this table, and a lookup that knows only one of them silently
    # returns nothing (which is how the map ended up holding L&T twice)
    "l-t": ["larsen & toubro", "larsen and toubro", "larsen toubro", "l&t"],
    "MIL": ["munitions india"],
    "AWEIL": ["advanced weapons and equipment india", "aweil"],
    "AVNL": ["armoured vehicles nigam", "avnl"],
    "IRRPL": ["indo-russian rifles", "indo russian rifles", "irrpl"],
    "ASHOKLEY": ["ashok leyland"],
    "BEL": ["bharat electronics"],
    "BDL": ["bharat dynamics"],
    "WIL": ["walchandnagar"],
    "TASL": ["tata advanced systems"],
    "JINDALT": ["jindal defence"],
    # The client's own roster is keyed by its pipeline id, and the press does not
    # call it "Kalyani Strategic Systems": the JVs are filed under the parent
    # (Bharat Forge) and under the JV's own name (Kalyani Rafael).
    "kalyani-strategic-systems": ["kalyani strategic systems", "kssl",
                                  "kalyani group", "bharat forge"],
}

# A JV's name is a way of FINDING a company in text, and it is not that company's
# identity. "Kalyani Rafael Advanced Systems" is how the press refers to the
# client's missile JV -- documents about it are about the client -- but feeding it
# to the organisation clustering merged Rafael INTO the client, so the client
# became its own partner. Matching uses both lists; clustering uses ALIAS only.
ALIAS_JV = {
    "kalyani-strategic-systems": ["kalyani rafael", "bf elbit",
                                  "kalyani strategic systems limited"],
}


def surfaces(code):
    """Every string this owner is written as, JV names included."""
    return list(ALIAS.get(code, ())) + list(ALIAS_JV.get(code, ()))
# A partner is an organisation. An armed service or a ministry is the CUSTOMER on
# the other side of an order -- the archive files "Indian Navy" as a partnership,
# and serving.partner's own contract says a side may not be a country or a force.
FORCE_RX = re.compile(r"\b(army|navy|air ?force|armed forces|ministry of defen|"
                      r"\bmod\b|government of|coast guard|border security)")


def official_name(code, name):
    """The name the source tierer will recognise.

    publishable() decides a page is OFFICIAL only when the domain's maker matches
    the name we hand it -- and the archive hands it "L&T", so larsentoubro.com,
    the company's OWN press release about its own contract, was scored a
    third-party registry page and the tie was dropped as uncorroborated."""
    a = ALIAS.get(code)
    return a[0] if a else (name or code)


def code_ok(code, name):
    """Is this archive code actually the company's acronym?

    "MIL" for Munitions India matched 135 documents -- the string "mil" -- and
    "FORCE" for Force Motors matched 267, which is the word force. A code counts
    only when it is the initials of the name it stands for."""
    c = norm(code or "")
    if len(c) < 3 or c in CODE_STOP:
        return False
    ws = [w for w in re.split(r"[^a-z0-9]+", norm(name or "")) if w]
    inits = "".join(w[0] for w in ws)
    return c == norm(name or "") or inits.startswith(c) or c in inits


def owner_at(text, code, name):
    """First position where the tie's OWNER is named.

    Stricter than the geo matcher on purpose: there, the country was a second
    independent test. Here both sides are companies, so the name has to appear
    WHOLE -- every token of it, generic words included. "Solar Industries" is not
    evidenced by the word solar."""
    if code_ok(code, name):
        i = find_at(text, [norm(code)])
        if i >= 0:
            return i
    i = find_at(text, surfaces(code))
    if i >= 0:
        return i
    parts = [w for w in re.split(r"[^a-z0-9]+", norm(name or "")) if len(w) > 2]
    if not parts:
        return -1
    if len(parts) == 1:
        return find_at(text, parts)
    anchor = max(parts, key=len)
    i = text.find(anchor)
    while i != -1:
        before = text[i - 1] if i else " "
        after = text[i + len(anchor)] if i + len(anchor) < len(text) else " "
        if not (before.isalnum() or after.isalnum()):
            if all(p in text[max(0, i - 60): i + len(anchor) + 60] for p in parts):
                return i
        i = text.find(anchor, i + 1)
    return find_at(text, rare_tokens(name))


def head_org(label):
    """The organisation the label is ABOUT.

    Archive labels are compound: "IndianOil & ReNew Power", "GE Aviation (CFM
    International)". Matching on any token of those published an L&T-IndianOil tie
    on the word "renew" and a TASL-GE tie on the string "cfm". Only the first
    organisation named counts -- plus its own acronym, when the bracket holds one
    word ("(IAI)") rather than a second company ("(CFM International)")."""
    # A SPACED ampersand joins two companies; an unspaced one is inside a name
    # ("R&D", "M&M"), and splitting on it turned DRDO into "Defence R".
    txt = re.split(r"\s+[&/,]\s+|\s*/\s*|\s*,\s*", (label or "").strip())[0]
    m = re.match(r"\s*([^(]+?)\s*(?:\(([^)]*)\))?\s*$", txt)
    if not m:
        return txt
    head, paren = m.group(1) or "", (m.group(2) or "").strip()
    if paren and not re.search(r"[\s&/]", paren):
        head = head + " (" + paren + ")"
    return head


# Words that describe a line of business rather than name a company. Frequency
# alone cannot separate these from real names -- measured over this corpus,
# `aviation` (4.6%) and `electronics` (5.3%) are RARER than `saab` (6.4%) and
# `tata` (8.2%) -- so the distinction has to be what the word IS, not how often
# it appears. DF stays as a backstop for the words that are everywhere.
NAME_GENERIC = CO_GENERIC | {
    "aviation", "electronics", "dynamics", "motors", "precision", "renew",
    "power", "energy", "naval", "marine", "space", "design", "land", "mobility",
    "holdings", "ventures", "enterprises", "projects", "global", "general",
    "national", "research", "development", "organisation", "organization",
    "manufacturing", "vehicles", "armour", "armor", "ordnance", "munitions",
    # a line of business, not a name
    "industry", "products", "product", "aeronautics", "aeronautical", "microwave",
    "joint", "venture", "investment", "fund", "weapons", "weapon", "arms",
    "consortium", "alliance", "partners", "partner", "office", "centre", "center",
    # a nationality is not an identity: "Israel Aerospace Industries" and "Israel
    # Weapon Industries" are two companies, and clustering on `israel` made them one
    "india", "indian", "israel", "israeli", "russia", "russian", "america",
    "american", "europe", "european", "africa", "african", "asia", "asian",
    "korea", "korean", "france", "french", "germany", "german", "sweden",
    "swedish", "italy", "italian", "spain", "spanish", "turkey", "turkish",
    "poland", "polish", "ukraine", "ukrainian", "brazil", "brazilian", "japan",
    "japanese", "china", "chinese", "britain", "british", "nation", "force",
    "forces", "army", "navy",
}
COMMON_NAME = 0.15   # `force` 37%, `design` 38%, `power` 30% -- never a name here


def acronyms(label):
    """Upper-case surface forms inside a label: MBDA, GA-ASI, IAI, DRDO."""
    out = []
    for t in re.findall(r"\b[A-Z][A-Z0-9&\-]{2,}\b", label or ""):
        n = norm(t)
        # "R&D" is not an organisation; it would match every research paragraph.
        # Neither is "GROUP" -- an ALL-CAPS label makes every word look like an
        # acronym, which is how "STV GROUP" came to be identified by the word group.
        if (len(n) >= 3 and "&" not in n and n not in CODE_STOP
                and n not in NAME_GENERIC and n not in out):
            out.append(n)
    return out


def name_tokens(label):
    return [w for w in re.split(r"[^a-z0-9]+", norm(label or ""))
            if len(w) > 3 and w not in NAME_GENERIC]


def rare_tokens(label):
    """Tokens the corpus says are distinctive enough to name a company alone.

    `hanwha` is in 2.7% of documents and identifies a company; `aviation` is in
    4.6% and identifies nothing. This is the same document-frequency test the
    matchup reviver uses to decide whether a product name can stand on its own."""
    return [w for w in name_tokens(label) if DF.get(w, 1.0) < COMMON_NAME]


def whole_at(text, toks):
    """Position where ALL of these tokens sit within one 60-character window."""
    if not toks:
        return -1
    anchor = max(toks, key=len)
    i = text.find(anchor)
    while i != -1:
        before = text[i - 1] if i else " "
        after = text[i + len(anchor)] if i + len(anchor) < len(text) else " "
        if not (before.isalnum() or after.isalnum()):
            if all(t in text[max(0, i - 60): i + len(anchor) + 60] for t in toks):
                return i
        i = text.find(anchor, i + 1)
    return -1


def party_at(text, label, code=None):
    """First position where the partner company is named.

    One rule, applied to the head organisation only: a company is its acronym, or
    its whole name, or -- when the corpus says the token is distinctive -- one
    token of it. A common token is never a company, however rare the label."""
    head = head_org(label)
    for a in acronyms(head):
        i = find_at(text, [a])
        if i >= 0:
            return i
    toks = name_tokens(head)
    if len(toks) >= 2:
        i = whole_at(text, toks)
        if i >= 0:
            return i
    return find_at(text, rare_tokens(head))


def all_at(text, finder, limit=12):
    """Every position `finder` reports, not just the first.

    ground_tie compared ONE mention of each company, so a long interview that names
    the client in paragraph 1 and Saab in paragraph 9 failed the proximity test
    while the sentence naming both sat in paragraph 8. Which mention came first was
    an accident of the surface list, and changing an alias silently changed which
    ties could be sourced at all."""
    out, cut = [], 0
    while len(out) < limit:
        i = finder(text[cut:])
        if i < 0:
            break
        out.append(cut + i)
        cut += i + 1
    return out


def ground_tie(docs, owner_code, owner_name, label, code=None, max_domains=4):
    """-> [(document_id, url)] where both companies and a relationship word meet."""
    if not label or FORCE_RX.search(norm(label)):
        return []
    best = {}
    for did, url, text in docs:
        owners = all_at(text, lambda t: owner_at(t, owner_code, owner_name))
        if not owners:
            continue
        parties = all_at(text, lambda t: party_at(t, label, code))
        if not parties:
            continue
        # the CLOSEST pair of mentions is the one a sentence could hold
        i, j = min(((a, b) for a in owners for b in parties if a != b),
                   key=lambda p: abs(p[0] - p[1]), default=(-1, -1))
        if i < 0 or abs(i - j) > PROX:
            continue
        lo, hi = min(i, j), max(i, j)
        # The relationship word has to sit BETWEEN the two names, or just before
        # them ("a joint venture between X and Y"). Searching a wide window around
        # both instead published ties on articles that merely list rival bidders
        # and use the word "partner" somewhere else in the paragraph.
        win = text[max(0, lo - 120): hi + 120]
        m = REL_RX.search(win)
        if not m:
            continue
        # rank: a word that STATES the tie beats one that implies it, and two names
        # in one sentence beat two names two sentences apart
        # judged on the WINDOW, not on the matched word: REL_RX returns "partner"
        # for both "our industrial partners" and "partnered with", and only one of
        # those is a statement.
        rank = (0 if STRONG_RX.search(win) else 1, hi - lo)
        d = st_domain(url)
        if d not in best or rank < best[d][0]:
            best[d] = (rank, did, url)
        if len(best) > max_domains:
            break
    # The row cites hits[0], so the document that STATES the tie has to be first.
    # Taking the first page per domain instead cited a page of gallery captions
    # that merely contains the partner's name, while the JV page on the same site
    # spells the relationship out.
    hits = sorted(best.values())
    return [(did, url) for _r, did, url in hits[:max_domains]]


def same_company(a, b):
    ta = {w for w in re.split(r"[^a-z0-9]+", norm(a)) if len(w) > 3}
    tb = {w for w in re.split(r"[^a-z0-9]+", norm(b)) if len(w) > 3}
    return bool(ta & tb)


def live_ids(cur):
    """-> (slug -> live comp_id, id -> name, ids THIS writer created).

    The third set matters: write() clears its own ord range before re-inserting, so
    a company revived on the previous run looks "already live" and would be dropped
    from the rebuild -- deleted, never re-created, and its ties with it. Rows in the
    revived range are always rebuilt."""
    cur.execute("SELECT comp_id, name, ord FROM serving.competitors WHERE origin='pipeline'")
    rows = cur.fetchall()
    by_slug = {slug(n): c for c, n, _o in rows}
    for c, _n, _o in rows:
        by_slug.setdefault(c, c)
    return (by_slug, {c: n for c, n, _o in rows},
            {c for c, _n, o in rows if o is not None and o >= REV_ORD0})


def client_row(cur):
    cur.execute("SELECT comp_id, name FROM serving.competitors "
                "WHERE origin='pipeline' AND dir='client' LIMIT 1")
    r = cur.fetchone()
    return r if r else (None, None)


def archived_ties(cur):
    """-> [(owner_code, owner_name, owner_sector, owner_hq, owner_dir, tie)]."""
    cur.execute("""SELECT comp_id, name, sector, hq, dir, partners
                     FROM serving.competitors WHERE origin='reference' ORDER BY ord""")
    out = []
    for cid, name, sector, hq, direction, partners in cur.fetchall():
        pl = partners if isinstance(partners, list) else json.loads(partners or "[]")
        for t in pl:
            out.append((cid, name, sector, hq, direction, t))
    return out


def archived_roster(cur):
    """The client's own partner rows -- serving.partner is the KSSL roster."""
    cur.execute("""SELECT id, label, kind, rel, ptype, note, date, country, deal
                     FROM serving.partner WHERE origin='reference' ORDER BY ord""")
    return [dict(zip(("id", "label", "kind", "rel", "ptype", "note", "date",
                      "country", "deal"), r)) for r in cur.fetchall()]


def note_terms(note, *names):
    """The words in the archive's note that make a CLAIM, minus the two company
    names it is about."""
    own = set()
    for n in names:
        own |= {w for w in re.split(r"[^a-z0-9]+", norm(n or "")) if w}
    out = []
    for w in re.split(r"[^a-z0-9]+", norm(note or "")):
        if len(w) > 3 and w not in own and w not in NAME_GENERIC and w not in out:
            out.append(w)
    for t in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", note or ""):
        if norm(t) not in own and norm(t) not in out:
            out.append(norm(t))
    return out


def note_supported(text, note, *names):
    """Does the evidence document actually say what the note says?

    THE FAULT THIS EXISTS FOR. The archive filed AVNL's tie as "Planned
    Indo-Russia JV to develop the Zorawar light battle tank". Grounding found a PIB
    release that names AVNL and Rosoboronexport together -- it is about a $248m
    contract for T-72 ENGINES -- and the row went out claiming a light-tank joint
    venture, stamped "stated by an official source". The pair was grounded; the
    CLAIM never was. A document that proves two companies are tied is not thereby
    evidence for whatever the archive wrote about them."""
    terms = note_terms(note, *names)
    # Only the DISTINCTIVE words can be checked. A first pass counted any two of
    # them and the PIB engine release matched "tank" and "develop" -- both true of
    # almost every defence page -- so the Zorawar claim passed. What has to be in
    # the document is the word the claim turns on: a name the corpus rarely uses.
    rare = [t for t in terms if DF.get(t, 0.0) and DF[t] < COMMON_NAME]
    if not rare:
        return True                 # nothing checkable; the tie still stands
    return sum(1 for t in rare if t in text) * 2 >= len(rare)


def keep_fields(t, src, why, note_ok=True):
    """What survives revival. The archive's `mean`, `insight` and `sig` are
    KSSL-specific analysis with no source behind them -- a document can state that
    two companies signed, it cannot state what that means for a third party. They
    stay archived; everything here is a fact the evidence carries.

    `note_ok=False` drops the archive's description too: the tie is evidenced, its
    description is not, and a sourced row carrying an unsourced sentence is worse
    than a row with no sentence."""
    return {"id": slug(t.get("label") or t.get("id")), "label": t.get("label"),
            "kind": t.get("kind"), "rel": t.get("rel") or "other",
            "ptype": t.get("ptype") or "Partnership",
            "note": t.get("note") if note_ok else None,
            "date": t.get("date") if t.get("date") not in (None, "n/d") else None,
            "country": t.get("country"), "src": src, "srcnote": why,
            "origin": "revived"}


def main(apply=False, limit=None):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    print("%d document(s) held" % len(docs))
    # every token that will be MATCHED on or CHECKED needs its corpus frequency
    index_df(docs, [w for _c, n, _s, _h, _d, t in archived_ties(cur)
                    for w in name_tokens(t.get("label")) + name_tokens(n)
                    + note_terms(t.get("note"), n, t.get("label"))]
                 + [w for r in archived_roster(cur)
                    for w in name_tokens(r["label"]) + note_terms(r["note"], r["label"])])
    by_slug, live_names, rev_ids = live_ids(cur)
    cli_id, cli_name = client_row(cur)

    ties = archived_ties(cur)
    roster = archived_roster(cur)
    print("archive: %d rival tie(s) over %d compan(y|ies), %d client roster row(s)\n"
          % (len(ties), len({t[0] for t in ties}), len(roster)))

    keep, newco = {}, {}
    drop = {"nosrc": 0, "weak": 0, "self": 0, "dupe": 0, "note": 0}
    # the evidence text, by document id, so a note can be checked against the page
    # it is about to be cited to
    doc_text = {d: t for d, _u, t in docs}
    seen = set()
    for n, (code, name, sector, hq, direction, t) in enumerate(ties):
        if limit and n >= limit:
            break
        label = t.get("label") or ""
        if not label or same_company(name or code, label):
            drop["self"] += 1
            continue
        target = by_slug.get(slug(name or ""), None) or by_slug.get(code.lower())
        key = (target or slug(name or code), slug(label))
        if key in seen:
            drop["dupe"] += 1
            continue
        hits = ground_tie(docs, code, name, label, t.get("id"))
        ok, why, _tier, _n = publishable([u for _d, u in hits],
                                         official_name(code, name))
        if not ok:
            drop["weak" if hits else "nosrc"] += 1
            continue
        seen.add(key)
        note_ok = note_supported(doc_text.get(hits[0][0], ""), t.get("note"),
                                 name, label)
        if not note_ok:
            drop["note"] += 1
        cid = target or slug(name or code)
        if not target or target in rev_ids:
            # A tie is only reachable through a COMPANY row. The archive holds 24
            # Indian competitors the crawl never profiled; one gets a live row here,
            # carrying only what the archive states as fact -- no assessment prose.
            newco.setdefault(cid, {"name": name, "sector": sector, "hq": hq,
                                   "dir": direction or "watch",
                                   "srcs": [], "code": code})
            newco[cid]["srcs"].append({"label": st_domain(hits[0][1]), "url": hits[0][1]})
        keep.setdefault(cid, []).append(keep_fields(t, hits[0][1], why, note_ok))

    rkeep = []
    for r in roster:
        if not cli_id:
            break
        if same_company(cli_name, r["label"]):
            drop["self"] += 1
            continue
        hits = ground_tie(docs, cli_id, cli_name, r["label"], r["id"])
        ok, why, _t, _n = publishable([u for _d, u in hits],
                                      official_name(cli_id, cli_name))
        if not ok:
            drop["weak" if hits else "nosrc"] += 1
            continue
        rr = keep_fields(r, hits[0][1], why,
                         note_supported(doc_text.get(hits[0][0], ""), r["note"],
                                        cli_name, r["label"]))
        rr["kind"] = r["kind"]
        rr["deal"] = r["deal"] if r["deal"] not in (None, "n/d") else None
        rkeep.append(rr)

    n_ties = sum(len(v) for v in keep.values())
    print("rival ties with real provenance : %d over %d compan(y|ies)"
          % (n_ties, len(keep)))
    print("client roster rows revived      : %d of %d" % (len(rkeep), len(roster)))
    print("  no document names both sides + a relationship : %d" % drop["nosrc"])
    print("  found but under the source bar                : %d" % drop["weak"])
    print("  same company on both sides / duplicate pair    : %d/%d"
          % (drop["self"], drop["dupe"]))
    print("  tie kept, archive DESCRIPTION dropped          : %d "
          "(the document evidences the pair, not the sentence)" % drop["note"])
    if newco:
        print("\ncompanies the archive holds and the live set does not (%d):" % len(newco))
        for cid, m in list(newco.items()):
            print("  %-28s %-26s %d tie(s)" % (cid, (m["name"] or "")[:26], len(keep[cid])))
    print("\nrevived ties:")
    for cid, v in keep.items():
        for t in v:
            print("  %-26s -> %-30s %s" % (cid[:26], (t["label"] or "")[:30], t["srcnote"]))
    for t in rkeep:
        print("  %-26s -> %-30s %s" % ("(client roster)", (t["label"] or "")[:30], t["srcnote"]))

    if apply:
        write(cur, con, keep, newco, rkeep)
        print("\napplied.")
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return keep, rkeep


def write(cur, con, keep, newco, rkeep):
    # Own range only. enrich_serving.step_companies / step_partnerships delete
    # every pipeline row they see; both were taught to stop at REV_ORD0 so the two
    # writers cannot take each other's rows with them.
    # Carry interim OSINT columns across this rebuild too (see enrich_serving.step_companies).
    cur.execute("""SELECT comp_id, leadership, facilities, hq FROM serving.competitors
                     WHERE origin='pipeline' AND ord >= %s
                       AND (leadership IS NOT NULL OR facilities IS NOT NULL)""",
                (REV_ORD0,))
    _carry = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    cur.execute("DELETE FROM serving.competitors WHERE origin='pipeline' AND ord >= %s",
                (REV_ORD0,))
    for i, (cid, m) in enumerate(sorted(newco.items())):
        cur.execute("""INSERT INTO serving.competitors
                         (comp_id, ord, name, dir, sector, hq, threat, assess, updates,
                          center, partners, site, srcs, products, "threatNote", origin)
                       VALUES (%s,%s,%s,%s,%s,%s,NULL,'',NULL,NULL,'[]'::jsonb,NULL,
                               %s,'[]'::jsonb,NULL,'pipeline')
                       ON CONFLICT (comp_id) DO NOTHING""",
                    (cid, REV_ORD0 + i, m["name"], m["dir"], m["sector"], m["hq"],
                     json.dumps(m["srcs"][:4])))
    for cid, (ld, fac, hq0) in _carry.items():
        cur.execute("""UPDATE serving.competitors
                         SET leadership = COALESCE(%s::jsonb, leadership),
                             facilities = COALESCE(%s::jsonb, facilities),
                             hq         = COALESCE(NULLIF(hq,''), %s)
                       WHERE comp_id=%s AND origin='pipeline'""",
                    (json.dumps(ld) if ld is not None else None,
                     json.dumps(fac) if fac is not None else None,
                     hq0, cid))
    for cid, plist in keep.items():
        # keep whatever the pipeline itself found; replace only revived entries
        cur.execute("SELECT partners FROM serving.competitors WHERE comp_id=%s "
                    "AND origin='pipeline'", (cid,))
        row = cur.fetchone()
        if row is None:
            continue
        cur_list = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
        merged = [p for p in cur_list if p.get("origin") != "revived"]
        have = {slug(p.get("label") or p.get("id") or "") for p in merged}
        merged += [p for p in plist if p["id"] not in have]
        cur.execute("""UPDATE serving.competitors SET partners=%s, updated_at=now()
                        WHERE comp_id=%s AND origin='pipeline'""",
                    (json.dumps(merged), cid))
    cur.execute("DELETE FROM serving.partner WHERE origin='pipeline' AND ord >= %s",
                (REV_ORD0,))
    # The pipeline may already have found the same company from a news story. One
    # roster row per company, or the tab shows Paramount twice.
    cur.execute("SELECT label FROM serving.partner WHERE origin='pipeline' AND ord < %s",
                (REV_ORD0,))
    have = {slug(r[0]) for r in cur.fetchall()}
    fresh = []
    for r in rkeep:
        k = slug(head_org(r["label"]))
        if k in have:
            continue
        have.add(k)
        fresh.append(r)
    rkeep = fresh
    for i, r in enumerate(rkeep):
        cur.execute("""INSERT INTO serving.partner
                         (id, ord, label, kind, rel, sig, ptype, note, date, country,
                          deal, insight, mean, src, srcnote, origin)
                       VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,NULL,NULL,%s,%s,
                               'pipeline')
                       ON CONFLICT (id) DO NOTHING""",
                    ("rvp_%02d" % (i + 1), REV_ORD0 + i, r["label"], r["kind"],
                     r["rel"], r["ptype"], r["note"], r["date"], r["country"],
                     r.get("deal"), r["src"], r["srcnote"]))
    con.commit()


def _demo():
    # the corpus decides which single tokens name a company; stand in for it here
    DF.update({"hanwha": 0.002, "bharat": 0.095, "electronics": 0.20,
               "renew": 0.024, "indianoil": 0.0, "aviation": 0.046,
               "mbda": 0.001, "alpha": 0.30})
    t = norm("Larsen & Toubro and Hanwha Defense signed a technology partnership "
             "to localise the K9 Vajra self-propelled howitzer at Hazira.")
    docs = [("d1", "https://larsentoubro.com/news", t),
            ("d2", "https://armyrecognition.com/x", t)]
    assert len(ground_tie(docs, "LT", "Larsen & Toubro", "Hanwha Defense")) == 2
    # both companies must be named: one side alone is not a tie
    solo = norm("larsen and toubro signed a technology partnership at hazira")
    assert ground_tie([("d3", "https://a.com/x", solo)], "LT", "Larsen & Toubro",
                      "Hanwha Defense") == []
    # ...and so must the relationship. Two rivals listed in one procurement story
    # is the commonest way a false tie gets published.
    both = norm("the army evaluated guns from larsen & toubro and hanwha defense "
                "at pokhran during the summer trials")
    assert ground_tie([("d4", "https://a.com/x", both), ("d5", "https://b.com/y", both)],
                      "LT", "Larsen & Toubro", "Hanwha Defense") == []
    # two companies in one long article are not a tie. This is the shape that put
    # BEL next to RRP: a "partnership" sentence about somebody else, 400 characters
    # away from the other company's own paragraph.
    far = norm("bharat electronics limited won the sights contract. " + ("filler " * 90)
               + " rrp defense signed a technology transfer agreement with meprolight")
    assert ground_tie([("d6", "https://a.com/x", far), ("d7", "https://b.com/y", far)],
                      "BEL", "BEL", "RRP Defense") == []
    # a distinctive token stands for the company; a common one does not
    assert party_at(norm("l&t and hanwha aerospace co-developed the k9"),
                    "Hanwha Land Systems") >= 0, "name drift must still match"
    assert party_at(norm("bharat forge won the atags order"),
                    "Bharat Electronics Limited") < 0, "a common token is not a name"
    # only the HEAD organisation of a compound label may match. Both of these
    # published a tie that does not exist: an L&T-IndianOil partnership grounded on
    # the word "renew", and a TASL-GE one on the string "cfm" in an equipment list.
    assert party_at(norm("l&t signed an agreement to renew the k9 contract"),
                    "IndianOil & ReNew Power") < 0, "secondary token matched"
    assert party_at(norm("tata advanced systems and cfm international at the show"),
                    "GE Aviation (CFM International)") < 0, "second company matched"
    assert head_org("Defence R&D Organisation (DRDO)") == "Defence R&D Organisation (DRDO)"
    assert "drdo" in acronyms(head_org("Defence R&D Organisation (DRDO)"))
    assert "r&d" not in acronyms("Defence R&D Organisation")
    # a filing code is not a company: "ALPHA" must not ground on the word alpha
    al = norm("the alpha variant of the radar was shown by adani defence and a partner")
    assert party_at(al, "Alpha Design Technologies", "ALPHA") < 0, "code matched a word"
    # an acronym the corpus actually uses does count
    mb = norm("l&t and mbda formed a joint venture for missile integration")
    assert party_at(mb, "MBDA Missile Systems") >= 0
    # the analysis prose does not survive revival
    kept = keep_fields({"label": "Hanwha", "mean": "<b>Threat:</b> ...",
                        "insight": "[CORE] ...", "sig": 3, "date": "n/d"},
                       "https://x.com/a", "corroborated by 2 independent sources")
    assert "mean" not in kept and "insight" not in kept and "sig" not in kept
    assert kept["date"] is None and kept["origin"] == "revived"
    # A DOCUMENT THAT PROVES THE PAIR IS NOT EVIDENCE FOR THE ARCHIVE'S SENTENCE.
    # The archive filed AVNL's tie as a Zorawar light-tank JV; grounding found a
    # PIB release about T-72 ENGINES that names both companies, and the row went
    # out claiming the JV, stamped "stated by an official source".
    DF.update({"planned": 0.4, "develop": 0.6, "light": 0.5, "battle": 0.4,
               "tank": 0.5, "zorawar": 0.001, "transfer": 0.3, "engines": 0.2})
    pib = norm("the ministry of defence has signed a contract with rosoboronexport "
               "worth $248 million for procurement of 1000 hp engines for t-72 tanks, "
               "including transfer of technology to armoured vehicles nigam limited")
    assert not note_supported(pib, "Planned Indo-Russia JV to develop the “Zorawar” light battle tank",
                              "AVNL", "Rosoboronexport")
    assert note_supported(pib, "Transfer of technology for T-72 tank engines",
                          "AVNL", "Rosoboronexport")
    # a note made only of the two company names has nothing to check
    assert note_supported(pib, "AVNL and Rosoboronexport", "AVNL", "Rosoboronexport")
    # a company is not its own partner
    assert same_company("Adani Defence", "Adani Defence & Aerospace")
    assert not same_company("Adani Defence", "Elbit Systems")
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply, a.limit)
