"""Rebuild Positioning from sources that can be checked, on BOTH sides.

    python apply_positioning.py --dry      # report, write nothing
    python apply_positioning.py --apply
    python apply_positioning.py --demo

WHAT WAS WRONG
--------------
The operator read the dashboard against KSSL's own website and found the KSSL side of the
comparison was not KSSL's. Taking one live row, matchup 497, KSSL "CQB Carbine":

    on screen                          KSSL export catalogue, page 33
    -------------------------------    ------------------------------------
    Weight   3.15 kg (3.65 loaded)     Weight (without Magazine), kg  < 3.3
    Barrel   508 / 407 / 360 mm        Barrel Length, mm              300
    Action   gas, bullpup, 640-840 rpm Operation  Gas Operated, Rotating Bolt
                                       Rate of Fire, rmp              600-700
    Range    300 m (F90 family)        Effective Range, m             200-300

Three separate failures in five rows. The barrel lengths and "bullpup" belong to the
Thales F90 — a different rifle from a different company; "3.65 loaded" is real but it is
the PROTECTIVE Carbine's figure (5.56x30, page 35), a different KSSL weapon; and the
advantage bullet read "F90 CQB (Thales-partnered)", fusing the two into one product that
does not exist. None of it was invented here: it was inherited from the archive, where a
value never had to name its source.

WHAT THIS DOES
--------------
1. REFUSE pairings that are not comparisons (positioning_gate.py) - they are deleted.
2. Rewrite every KSSL-side spec value from the export catalogue, matching on the FIELD,
   and DROP any KSSL spec whose field the catalogue does not publish. A field we cannot
   source is removed, never left at its archived value.
3. Recompute `edge` from what survived, because an edge computed over five fields is not
   the edge over the two that could be sourced.
4. Record the catalogue URL and page in `srcs`, so every remaining number is checkable.

Rows whose KSSL product is not in the catalogue at all are marked, not silently kept:
if KSSL does not publish the product, we cannot state its specifications.
"""
import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from positioning_gate import gate, product_of  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
CATALOGUE = HERE / "products" / "kalyani-strategic-systems.json"

# Matchup field -> the words a catalogue uses for the same field. Matching on the FIELD
# and not on position is the point: a data sheet orders its rows however it likes, and
# lining up row 3 with row 3 is how a rate of fire ends up printed as a barrel length.
FIELD_WORDS = {
    "calibre": ("calibre", "caliber", "cartridge"),
    "weight": ("weight", "mass"),
    "effective range": ("effective range", "effective firing range", "range"),
    "barrel": ("barrel",),
    "length": ("length", "overall length"),
    # A maker's HEADLINE rate ("Rate of fire: 6 rounds per minute") is a maximum.
    # KSSL's catalogue states two rates instead, and they are different claims -- an
    # intense burst and an hour-long sustained figure -- so they stay separate fields
    # here. Deciding which of them a rival's headline rate may be set against is a
    # judgement, and it belongs in one visible place (pair_rivals), not in a lookup
    # table that would silently merge "10 rounds in 2.5 min" with "6 per minute".
    "rate of fire": ("rate of fire", "rof", "firing rate", "max rate of fire"),
    "rate intense": ("intense rate", "intense rate of fire"),
    "rate sustained": ("sustained rate", "sustained rate of fire"),
    "action": ("operation", "principle of operation", "action"),
    "magazine": ("magazine",),
    "elevation": ("elevation",),
    "traverse": ("traverse",),
    "protection": ("protection", "protection level"),
    "speed": ("speed", "max speed"),
    "crew": ("crew",),
    "engine": ("engine", "power"),
}

# A label that CONTAINS a field word but is not that field. Every one of these was a real
# mis-assignment on the first apply run, caught only because the printed diff was read:
#   "Power to Weight Ratio  28kW/T"  -> published as the M4's engine power
#   "Transmission Automatic 6 speed" -> published as its speed
# The field word being present is not the same as the label naming that field.
DISQUALIFY = {
    "engine": ("to weight", "ratio", "power pack ratio"),
    "speed": ("transmission", "gearbox", "speed gearbox", "automatic"),
    "weight": ("to weight ratio", "payload"),
    "length": ("wheelbase",),
}

def norm_field(label):
    """Which of the known fields this label is, or None.

    Two rules, both learned from a wrong value reaching the database:

    1. The field word must START the label. A data sheet names the field first and
       qualifies it afterwards - "Weight (without Magazine), kg". Matching anywhere in
       the string filed that row under `magazine`, and filed "Transmission Automatic 6
       speed" under `speed`.
    2. A disqualifier anywhere in the label vetoes the match outright, because some
       labels genuinely begin with a field word while meaning something else: "Power to
       Weight Ratio" is neither engine power nor weight.

    Unmatched is the safe answer - the caller DROPS the spec rather than showing an
    unsourced one.
    """
    s = re.sub(r"[^a-z ]+", " ", (label or "").lower())
    s = " ".join(s.split())
    best = None
    for field, words in FIELD_WORDS.items():
        if any(bad in s for bad in DISQUALIFY.get(field, ())):
            continue
        for w in words:
            if not s.startswith(w):
                continue
            # longest wins at the same start, so "effective range" beats bare "range"
            if best is None or len(w) > best[0]:
                best = (len(w), field)
    return best[1] if best else None


def load_catalogue():
    """{normalised product name: {field: (value, label, page, url)}}"""
    if not CATALOGUE.exists():
        raise SystemExit("no catalogue at %s - run fetch_brochures.py first" % CATALOGUE)
    d = json.load(io.open(CATALOGUE, encoding="utf-8"))
    out = {}
    for p in d["products"]:
        name = key_of(p.get("product") or "")
        if not name:
            continue
        fields = out.setdefault(name, {})
        for s in p["specs"]:
            f = norm_field(s["label"])
            if not f or f in fields:
                continue
            fields[f] = {
                "value": s["value"], "label": s["label"],
                "page": (p.get("pages") or [p["page"]])[0], "url": p["source_url"],
                "line": s["line"],
            }
    return out


def key_of(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


# The matchup names a product the way an analyst writes it; the catalogue names it the
# way the maker prints it. EXPLICIT, one line each, no fuzzy matching - a wrong alias
# here silently attributes one weapon's specifications to another, which is the exact
# fault being repaired ("3.65 loaded" was the Protective Carbine's weight on the CQB
# Carbine's row).
#
# What is deliberately NOT here matters as much: Bharat 52, Bharat 45, Bharat 150,
# Sniper, Bayonet, Cleaver, Omega and Shell forgings have no entry because KSSL's export
# catalogue does not publish them. That is a finding, not a gap to paper over - we cannot
# state the specifications of a product its maker does not specify.
ALIAS = {
    "mpv": "Mine Protected Vehicle",
    "m4": "Kalyani M4",
    "ltv": "Light Tactical Vehicle",
    "lbpv": "Light Bullet Proof Vehicle",
    "ulsv": "Light Specialist Vehicle",
    "atc": "Kalyani Maverick",              # catalogue p18: "Armour Troop Carrier"
    "lamv": "Light Armoured Multipurpose Vehicle",
    "lapv": "Light Armoured Personnel Vehicle",
}

# "MArG 155" is not one product: the catalogue carries MArG 39-BR, MArG 45 and MArG 52,
# which differ in exactly the barrel length a comparison is about. Resolving it to any
# one of them would put a 52-calibre figure under a 39-calibre name. It stays unmatched.
AMBIGUOUS = {"marg155": "MArG is a family (39-BR / 45 / 52); the catalogue specifies each "
                        "separately and they differ in calibre length"}


def match_product(name, cat):
    """The catalogue entry for a matchup's KSSL product name, or None.

    Exact key first, then containment either way — the matchup says "MArG 155" where the
    catalogue says "MArG 52". Containment is allowed only when one is at least 4
    characters, so "M4" does not match "Kalyani M4" AND "MArG 45" at once.
    """
    k = key_of(name)
    if not k or k in AMBIGUOUS:
        return None, None
    if k in ALIAS:
        k = key_of(ALIAS[k])
    if k in cat:
        return k, cat[k]
    if len(k) >= 4:
        hits = [c for c in cat if k in c or (len(c) >= 4 and c in k)]
        if len(hits) == 1:
            return hits[0], cat[hits[0]]
    return None, None


def rebuild(specs, entry):
    """KSSL's side of a spec table, rewritten from the catalogue.

    Returns (kept, dropped, changed). A spec whose field the catalogue does not publish
    is DROPPED — it cannot be shown, and leaving the archived value there is exactly the
    fault being repaired.
    """
    kept, dropped, changed = [], [], []
    for sp in specs or []:
        f = norm_field(sp.get("l"))
        src = entry.get(f) if f else None
        if not src:
            dropped.append(sp.get("l"))
            continue
        old = sp.get("kv")
        sp = dict(sp)
        sp["kv"] = src["value"]
        sp["kp"] = "official"
        sp["ksrc"] = {"url": src["url"], "page": src["page"], "line": src["line"]}
        n = re.search(r"-?\d+(?:\.\d+)?", src["value"])
        sp["kn"] = float(n.group(0)) if n else None
        if (old or "") != sp["kv"]:
            changed.append((sp.get("l"), old, sp["kv"]))
        kept.append(sp)
    return kept, dropped, changed


def recompute_edge(specs):
    """Edge over the fields that SURVIVED, never the archived number.

    An edge of 60 computed across five fields, carried onto the two that could be
    sourced, is a claim about evidence that was thrown away.
    """
    cmpble = [s for s in specs if s.get("kn") is not None and s.get("cn") is not None]
    if not cmpble:
        return None
    wins = sum(1 for s in cmpble if s.get("hi") is False)
    return int(round(100.0 * wins / len(cmpble)))


def main(apply_it):
    import psycopg2 as pg
    cat = load_catalogue()
    print("catalogue: %d products, fields per product: %s" % (
        len(cat), ", ".join("%s:%d" % (k, len(v)) for k, v in list(cat.items())[:4])))

    with pg.connect(DSN, connect_timeout=10) as cx:
        with cx.cursor() as cur:
            cur.execute("select matchup_id, bf, comp, specs, edge, srcs "
                        "from serving.matchup where origin='pipeline' order by matchup_id")
            rows = cur.fetchall()

        drop_ids, stats = [], {"refuse": 0, "unresolved": 0, "no_product": 0,
                               "rewritten": 0, "specs_dropped": 0, "specs_changed": 0}
        updates, examples = [], []
        for mid, bf, comp, specs, edge, srcs in rows:
            verdict, kind, note = gate(bf, comp)
            if verdict == "refuse":
                drop_ids.append(mid)
                stats["refuse"] += 1
                continue
            if verdict == "unresolved":
                stats["unresolved"] += 1
            _, entry = match_product(product_of(bf), cat)
            if not entry:
                stats["no_product"] += 1
                continue
            kept, dropped, changed = rebuild(specs, entry)
            stats["specs_dropped"] += len(dropped)
            stats["specs_changed"] += len(changed)
            if not changed and not dropped:
                continue
            stats["rewritten"] += 1
            src = {"label": "KSSL export catalogue", "url": entry[list(entry)[0]]["url"],
                   "tier": "official"}
            new_srcs = [s for s in (srcs or []) if s.get("url") != src["url"]] + [src]
            updates.append((mid, json.dumps(kept), recompute_edge(kept),
                            json.dumps(new_srcs), note or None))
            if len(examples) < 6 and changed:
                examples.append((mid, product_of(bf), changed, dropped))

        print("\nrows: %d" % len(rows))
        for k in ("refuse", "unresolved", "no_product", "rewritten",
                  "specs_changed", "specs_dropped"):
            print("  %-14s %d" % (k, stats[k]))
        print("\n-- what changed on the KSSL side --")
        for mid, prod, changed, dropped in examples:
            print("%6d  %s" % (mid, prod))
            for l, old, new in changed:
                print("        %-18s %-28s -> %s" % (l, (old or "-")[:28], new))
            if dropped:
                print("        dropped (catalogue does not publish): %s" % ", ".join(
                    str(x) for x in dropped))

        if not apply_it:
            print("\nDRY RUN - nothing written. Re-run with --apply")
            return
        with cx.cursor() as cur:
            if drop_ids:
                cur.execute("delete from serving.matchup where matchup_id = any(%s)",
                            (drop_ids,))
            for mid, specs_j, edge, srcs_j, note in updates:
                cur.execute(
                    "update serving.matchup set specs=%s::jsonb, edge=%s, srcs=%s::jsonb, "
                    "reason = case when %s is null then reason "
                    "else reason || ' Comparison caveat: ' || %s end, updated_at=now() "
                    "where matchup_id=%s",
                    (specs_j, edge, srcs_j, note, note, mid))
        cx.commit()
        print("\nAPPLIED: %d deleted, %d rewritten" % (len(drop_ids), len(updates)))


def demo():
    assert norm_field("Effective Range, m") == "effective range"
    assert norm_field("Range") == "effective range"
    assert norm_field("Kerb Weight 14.5 Tons 11 Tons") is None,         "a field word must START the label, or a variant table leaks in"
    assert norm_field("Power to Weight Ratio") is None, "not engine power, not weight"
    assert norm_field("Transmission Automatic 6 speed") is None, "not a speed"
    assert norm_field("Protection Level") == "protection"
    assert norm_field("Weight (without Magazine), kg") == "weight"
    assert norm_field("Rate of Fire, rmp") == "rate of fire"
    assert norm_field("No. of Grooves") is None, "an unknown field must not map anywhere"

    cat = {"cqbcarbine": {"weight": {"value": "< 3.3", "label": "Weight, kg",
                                     "page": 33, "url": "u", "line": "Weight, kg < 3.3"}}}
    k, e = match_product("CQB Carbine", cat)
    assert k == "cqbcarbine"
    # a two-character name must not fuzzy-match its way into the wrong product
    # an alias resolves; an ambiguous family name never does
    assert match_product("M4", {"kalyanim4": {"weight": 1}, "marg45": {}})[0] == "kalyanim4"
    assert match_product("MArG 155", {"marg45": {}, "marg52": {}})[0] is None,         "a family name must not resolve to one of its members"

    kept, dropped, changed = rebuild(
        [{"l": "Weight", "kv": "3.15 kg (3.65 loaded)", "cn": 7, "hi": False},
         {"l": "Barrel", "kv": "508 / 407 / 360 mm"}], e)
    assert len(kept) == 1 and kept[0]["kv"] == "< 3.3", kept
    assert kept[0]["kn"] == 3.3
    assert dropped == ["Barrel"], "an unsourceable field must be dropped, not kept"
    assert changed and changed[0][1] == "3.15 kg (3.65 loaded)"
    assert recompute_edge(kept) == 100
    assert recompute_edge([{"l": "x"}]) is None, "no comparable field means no edge"
    print("demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        main(a.apply)
