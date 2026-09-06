"""The curated competitor roster, and who counts as being on it.

ONE implementation, imported by both writers. enrich_serving asks it which candidate
companies may become roster rows; serving_fill asks it whether a card's company may be
called a threat. Those two answering differently is how a company ends up on the
Competitor tab with all its news filed as watch, or flagged as a threat with no profile
to click through to.

The table (serving.competitor_roster_allow) is ADVISORY: absent or empty means no
opinion, and every caller falls back to its previous behaviour. That keeps a fresh
database working and makes the whole thing reversible with a DELETE rather than a
redeploy.

MATCHING IS NOT EQUALITY, and each of the three ways below is a real case from this
corpus:
  rename      the roster says "RTX", 20 cards say "Raytheon". Not derivable from the
              spelling -- the allowlist carries both, which is why it holds 83 rows
              for 50 companies.
  suffix      "Kalashnikov Concern", "Anduril Industries", "Rheinmetall AG".
  division    "BAE Systems Bofors" is where the Archer howitzer is built; also
              "Rheinmetall MAN", "Raytheon UK", "Hanwha Aerospace Romania". Equality
              alone demoted all of these to watch -- exactly the core-line artillery
              news the roster exists to surface.
Containment is aliases._contains_word, the repo's own rule, whose word boundaries are
what keep it safe: "iwi" does not match inside "kiwi".
"""
import os
import re

from aliases import _contains_word, canonical as canon_name, fold as fold_name

_SUFFIX_RX = re.compile(
    r"\s+(ltd|limited|plc|inc|corp|corporation|company|gmbh|ag|spa|oyj|ab|nv|bv|"
    r"pvt|private|concern|group|holdings?|industries|international|"
    r"systems|technologies|defence|defense|aerospace)$", re.I)

_KEYS = None


def norm(name):
    """Every key one spelling should answer to."""
    out = set()
    for v in (name, canon_name(name)):
        f = fold_name(v)
        if f:
            out.add(f)
            bare = _SUFFIX_RX.sub("", f).strip()
            if bare:
                out.add(bare)
    out.discard("")
    return out


def keys(cur=None):
    """Match keys for the curated roster; empty set means "no opinion".

    Cached for the life of the process: this is read per card, and the roster changes
    when a human edits it, not mid-run. A caller with a cursor should pass it; without
    one a short-lived connection is opened, and any failure returns the empty set --
    the gate is a refinement, and must never be the reason a pass dies.
    """
    global _KEYS
    if _KEYS is not None:
        return _KEYS
    _KEYS = set()
    try:
        if cur is not None:
            _KEYS = _read(cur)
        else:
            import psycopg2
            with psycopg2.connect(os.environ["KSSL_DSN"]) as con:
                with con.cursor() as c:
                    _KEYS = _read(c)
    except Exception as e:                                        # noqa: BLE001
        print("roster: allowlist unavailable (%s) -- no roster opinion" % e, flush=True)
        _KEYS = set()
    return _KEYS


def _read(cur):
    cur.execute("SELECT to_regclass('serving.competitor_roster_allow')")
    if not cur.fetchone()[0]:
        return set()
    cur.execute("SELECT name FROM serving.competitor_roster_allow")
    out = set()
    for (n,) in cur.fetchall():
        if n:
            out |= norm(n)
    return out


def on_roster(company, k=None):
    """Is this company name one of the curated competitors, or a division of one?"""
    k = keys() if k is None else k
    if not k or not company:
        return False
    if norm(company) & k:
        return True
    folded = fold_name(company)
    return any(_contains_word(x, folded) for x in k if len(x) >= 3)


# ---------------------------------------------------------------------------------
# Columns that are CURATED, not rebuilt -- and therefore destroyed by any pass that
# DELETEs and re-INSERTs serving.competitors unless carried across it.
#
# step_companies' INSERT writes 16 columns. Everything below is written by something
# else: pipeline/harvest/promote.py (leadership, facilities, sales -- hand-audited at
# 12 / 39 / 8 rows) or by hand. A carry-forward already existed but listed only
# leadership, facilities and hq, so `sales` was written once and silently wiped by the
# next two-hourly pass. That is why annual revenue read 0 of 42 on the tab while the
# harvest had already extracted it.
#
# ONE list, imported by both writers. revive_partners.py kept its own copy of the same
# three columns; two lists is how the next column gets forgotten by exactly one of them.
CARRIED_COLUMNS = ("leadership", "facilities", "sales", "starting_year",
                   "global_locations", "company_size", "strategic_positioning",
                   # 2026-09-06. Origin country comes from the audited competitor
                   # workbook, not the corpus, so the rebuild cannot regenerate it.
                   "country",
                   # Partnership ties. The rebuild's INSERT wrote '[]' here, so every
                   # two-hourly pass emptied the Partnerships tab and only the
                   # competitors whose profile call FAILED kept their ties -- which is
                   # why Adani and Mahindra were the last two companies on the tab
                   # still holding data, at an updated_at eleven days behind every
                   # other row. The INSERT now writes NULL so this COALESCE can fire.
                   "partners")
# hq is carried only to fill a BLANK: the rebuild's own value wins when it has one,
# because the corpus is fresher than a hand edit.
CARRY_IF_BLANK = ("hq",)


def carry_snapshot(cur, where="origin='pipeline'", args=()):
    """Read the curated columns before a rebuild deletes them."""
    cols = CARRIED_COLUMNS + CARRY_IF_BLANK
    cur.execute("SELECT comp_id, %s FROM serving.competitors WHERE %s"
                % (", ".join('"%s"' % c for c in cols), where), args)
    return {r[0]: dict(zip(cols, r[1:])) for r in cur.fetchall()}


def carry_restore(cur, snap):
    """Put them back onto the freshly rebuilt rows.

    COALESCE in this direction on purpose: a carried value fills a column the rebuild
    left NULL and never overwrites one the rebuild managed to populate.
    """
    import json as _json
    n = 0
    for cid, vals in snap.items():
        sets, args = [], []
        for c in CARRIED_COLUMNS:
            v = vals.get(c)
            if v is None:
                continue
            sets.append('"%s" = COALESCE("%s", %%s)' % (c, c))
            args.append(_json.dumps(v) if isinstance(v, (dict, list)) else v)
        for c in CARRY_IF_BLANK:
            v = vals.get(c)
            if v in (None, ""):
                continue
            sets.append('"%s" = COALESCE(NULLIF("%s", \'\'), %%s)' % (c, c))
            args.append(v)
        if not sets:
            continue
        args.append(cid)
        cur.execute("UPDATE serving.competitors SET %s WHERE comp_id=%%s "
                    "AND origin='pipeline'" % ", ".join(sets), args)
        n += cur.rowcount
    return n


def is_roster_name(company, k=None):
    """STRICT identity: is this spelling one of the curated companies itself?

    Deliberately not on_roster(). The two questions differ, and conflating them put 79
    candidates on a 50-company tab: containment claims "Leonardo DRS" and "Rheinmetall
    MAN" for their parents, which is right when deciding whether a NEWS CARD is about a
    tracked rival, and wrong when deciding whether to create a competitor ROW -- there
    the division would stand as a rival in its own right, beside its parent.
    """
    k = keys() if k is None else k
    return bool(k) and bool(company) and bool(norm(company) & k)


def allows(merged, k=None):
    """Filter a merge_candidates() result {survivor: {spellings}} to the roster.

    Strict, per is_roster_name: a roster ROW is a company, not a division of one.
    """
    k = keys() if k is None else k
    if not k:
        return merged
    return {name: sp for name, sp in merged.items()
            if any(is_roster_name(s, k) for s in set(sp) | {name})}


def _demo():
    k = set()
    for a in ("RTX", "Raytheon", "Rheinmetall", "Leonardo", "Anduril", "Kalashnikov",
              "BAE Systems", "Hanwha Aerospace", "IWI"):
        k |= norm(a)
    # a rename is listed, never derived
    assert not (norm("Raytheon") & norm("RTX"))
    assert on_roster("RAYTHEON", k)
    # suffixes fold
    for s in ("Anduril Industries", "Kalashnikov Concern", "Rheinmetall AG", "RHEINMETALL"):
        assert on_roster(s, k), s
    # divisions count
    for s in ("BAE Systems Bofors", "Rheinmetall MAN", "Raytheon UK", "Leonardo DRS",
              "American Rheinmetall", "Hanwha Aerospace Romania"):
        assert on_roster(s, k), s
    # strangers do not
    for s in ("Thales", "Thales Alenia Space", "Saildrone", "Terma", "NATO",
              "Indian Army", "Polska Grupa Zbrojeniowa", "Boeing"):
        assert not on_roster(s, k), s
    # word boundaries, not substrings
    assert not on_roster("Kiwi Aerospace", norm("IWI"))
    # empty roster = no opinion, and allows() must not empty the world
    assert on_roster("Thales", set()) is False
    assert allows({"Thales": {"Thales"}}, set()) == {"Thales": {"Thales"}}
    # allows() is STRICT: a division is not its own roster row, even though its news
    # counts as its parent's. Conflating the two is the 79-candidates-on-a-50-company-
    # tab bug.
    assert allows({"Thales": {"Thales"}, "Raytheon UK": {"Raytheon UK"},
                   "RTX": {"RTX"}}, k) == {"RTX": {"RTX"}}
    assert on_roster("Raytheon UK", k) and not is_roster_name("Raytheon UK", k)
    assert is_roster_name("Kalashnikov Concern", k), "a suffix variant IS the company"
    print("roster demo ok - rename/suffix/division matched, strangers held out, "
          "empty allowlist is a no-op")


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


if __name__ == "__main__":
    _demo()
