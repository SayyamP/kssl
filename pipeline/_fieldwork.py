"""Field-level worklist: which (product, field) pairs Gap Analysis is waiting on.

Imported by fetch_for_products.py. Kept separate from the product-level worklist
because the two answer different questions: that one asks "who is missing from
Positioning at all", this one asks "which single number would turn an existing
row into a comparable one".

A gap needs the SAME directional field sourced for BOTH products. So a product
whose partner already has the field is worth twice one whose partner does not --
one page closes the pair, instead of leaving it half-open.
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from revive_matchups import product_of      # noqa: E402

# What to actually type into a search box for each spec label. The archive's
# labels are column headings ("Crew / pax"); a spec sheet writes them out.
FIELD_Q = {
    "Combat weight": "combat weight tonnes gross vehicle weight",
    "Weight": "weight kg tonnes",
    "Crew": "crew members gun detachment",
    "Crew / pax": "crew capacity seats personnel",
    "Max range": "maximum firing range km",
    "Range": "range km",
    "Effective range": "effective range metres",
    "Rate of fire": "rate of fire rounds per minute",
    "Power / speed": "engine power hp maximum speed km/h",
    "Endurance": "endurance hours",
    "Payload / ceiling": "payload kg service ceiling",
}


def sourced(specs, label, side):
    """Is `label` published for this side ('c' or 'k') in a live row?"""
    for s in specs or []:
        if (s.get("l") or "") == label:
            return s.get(side + "n") is not None or s.get(side + "v") is not None
    return False


def field_worklist(cur, top=80):
    """-> [(product, maker, field, query, score, n_rows)] worst-blocking first."""
    cur.execute("""select comp, bf, specs from serving.matchup
                    where origin='pipeline' and matchup_id >= 20000""")
    live = {(c, b): sp for c, b, sp in cur.fetchall()}
    cur.execute("""select comp, "compBy", bf, "bfBy", specs from serving.matchup
                    where origin='reference'""")
    score = collections.Counter()
    rows = collections.Counter()
    meta = {}
    for comp, compby, bf, bfby, specs in cur.fetchall():
        cur_specs = live.get((comp, bf))
        for s in specs or []:
            lab = s.get("l") or ""
            if s.get("hi") is None or lab not in FIELD_Q:
                continue                      # no direction -> no gap to measure
            have_c = sourced(cur_specs, lab, "c")
            have_k = sourced(cur_specs, lab, "k")
            if have_c and have_k:
                continue                      # already comparable
            for name, mk, mine, theirs in ((comp, compby, have_c, have_k),
                                           (bf, bfby, have_k, have_c)):
                if mine:
                    continue
                p = product_of(name)
                if len(p) < 3:
                    continue
                key = (p, lab)
                # the partner already has it: one page makes the pair comparable
                score[key] += 2 if theirs else 1
                rows[key] += 1
                meta.setdefault(key, mk or "")
    out = []
    for (p, lab), sc in score.most_common(top):
        mk = meta.get((p, lab), "")
        # the maker has to be in the query: half of these product names are bare
        # acronyms ("MPV", "ATC", "LTV") that mean nothing to a search engine on
        # their own, and the top of the worklist is exactly those.
        out.append((p, mk, lab, ("%s %s %s" % (mk, p, FIELD_Q[lab])).strip(),
                    sc, rows[(p, lab)]))
    return out


def _demo():
    sp = [{"l": "Crew", "cn": 3, "kn": None}, {"l": "Max range", "cv": None, "kv": "40 km"}]
    assert sourced(sp, "Crew", "c") and not sourced(sp, "Crew", "k")
    assert sourced(sp, "Max range", "k") and not sourced(sp, "Max range", "c")
    assert not sourced(sp, "Weight", "c")      # absent field is not sourced
    assert not sourced(None, "Crew", "c")
    assert "rounds per minute" in FIELD_Q["Rate of fire"]
    print("ok (%d field queries)" % len(FIELD_Q))


if __name__ == "__main__":
    _demo()
