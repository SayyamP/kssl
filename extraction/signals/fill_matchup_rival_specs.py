# -*- coding: utf-8 -*-
"""Put the verified competitor workbook onto the Positioning panel.

    python fill_matchup_rival_specs.py --demo    # hermetic: the matcher and the guards
    python fill_matchup_rival_specs.py           # dry run against the DB
    python fill_matchup_rival_specs.py --apply

THE GAP THIS CLOSES. competitor_portfolio.py parses the client's competitor master and
competitor_specs.py verifies it -- 625 publishable products, 2,025 labelled
specifications, most of them the maker's own published figures. Both write
serving.competitor_product. NOTHING READS THAT TABLE: not the backend, not the frontend,
not revive_matchups. So the verification ran, the import ran, and the rival column on
Positioning stayed empty. This is the reader.

PRECEDENCE, which is the operator's own rule: "tag it as workbook, so when our pipeline
generates it will replace it". A value the extraction pipeline grounded is NEVER
overwritten here -- this only fills a rival cell that is empty. Everything it writes is
tagged `cOrigin='workbook'`, so the pipeline can recognise its own ground and replace it,
and so the panel can say where the figure came from.

MATCHING A PRODUCT IS WHERE THIS GOES WRONG. Two real traps in this data:

    CAESAR 6x6      the panel writes ASCII 'x'; the workbook writes U+00D7 MULTIPLICATION
                    SIGN. A plain compare misses all three CAESARs.
    Archer          the workbook holds "ARCHER Mobile Howitzer" AND "Archerfish Mine
                    Disposal System". A substring match puts a mine-disposal system's
                    figures on a self-propelled howitzer.
    CAESAR 6x6 /    three variants, three different guns. Anything fuzzy publishes one
    8x8 / Mk2       variant's range as another's.

So: normalise the typography, match on WHOLE TOKENS, and accept only when exactly one
product answers AND it belongs to the same competitor. Ambiguity is refused and counted.
"""
import collections
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, "/app/signals")

DOT = "·"          # the ' - ' the panel puts between maker and product


def norm_tokens(name):
    """'CAESAR 6x6' and 'CAESAR 6x6' (U+00D7) -> the same token list."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("×", "x").replace("–", "-").replace("—", "-")
    s = re.sub(r"\(.*?\)", " ", s).lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def product_of(label):
    """'KNDS - CAESAR 6x6' -> 'CAESAR 6x6'."""
    s = str(label or "")
    return s.split(DOT)[-1].strip() if DOT in s else s.strip()


def match_product(name, index, comp_id=None):
    """-> (row, why). Exact tokens, then a UNIQUE whole-token prefix. Never fuzzy.

    When comp_id is given, only that competitor's products are considered: two makers
    can ship a product of the same name, and the panel already knows whose it is.
    """
    t = tuple(norm_tokens(name))
    if not t:
        return None, "no product name"

    def scoped(rows):
        return [r for r in rows if comp_id is None or r.get("comp_id") == comp_id]

    eq = scoped(index.get(t) or [])
    if len(eq) == 1:
        return eq[0], None
    if len(eq) > 1:
        return None, "%d products share this exact name" % len(eq)
    pre = [r for k, rows in index.items() if len(k) >= len(t) and k[:len(t)] == t
           for r in scoped(rows)]
    if len(pre) == 1:
        return pre[0], None
    if len(pre) > 1:
        return None, "%d products start with this name" % len(pre)
    return None, "no workbook product"


def fold_label(s):
    return " ".join(norm_tokens(s))


def too_similar(label, existing):
    """Would appending `label` sit a near-duplicate beside a row already on the panel?

    "range" next to "Max range" reads as two measurements and is one. Whole-token
    containment either way is enough to hold it back -- the value is not lost, it is
    just not published twice under two names.
    """
    a = fold_label(label).split()
    if not a:
        return True
    for e in existing:
        b = fold_label(e).split()
        if not b:
            continue
        if a == b:
            return True
        n, m = len(a), len(b)
        if n < m and any(b[i:i + n] == a for i in range(m - n + 1)):
            return True
        if m < n and any(a[i:i + m] == b for i in range(n - m + 1)):
            return True
    return False


def spec_rows(prod):
    """The workbook specs for one product, as {folded label: (label, value, srcs, tier)}."""
    out = {}
    for s in (prod.get("specs") or []):
        if not isinstance(s, dict):
            continue
        lab = str(s.get("k") or "").strip()
        val = str(s.get("v") or "").strip()
        if not lab or not val:
            continue                      # an unlabelled bullet cannot join a panel row
        out.setdefault(fold_label(lab), (lab, val, s.get("srcs") or [], s.get("tier")))
    return out


def plan_one(matchup_specs, prod):
    """-> (filled, appended, skipped). Pure, so the guards are testable without a DB."""
    have = {}
    for s in matchup_specs:
        if isinstance(s, dict):
            have.setdefault(fold_label(s.get("l") or s.get("k")), s)
    filled, appended, skipped = [], [], collections.Counter()
    for key, (lab, val, srcs, tier) in sorted(spec_rows(prod).items()):
        row = have.get(key)
        if row is not None:
            if row.get("cv") is not None:
                skipped["the pipeline already states this"] += 1
                continue
            filled.append((row, lab, val, srcs, tier))
            continue
        if too_similar(lab, [s.get("l") or s.get("k") for s in matchup_specs
                             if isinstance(s, dict)]):
            skipped["a near-duplicate label is already on the panel"] += 1
            continue
        appended.append((lab, val, srcs, tier))
    return filled, appended, skipped


def _why(tier, srcs):
    n = len(srcs or [])
    where = "the maker's or a government publisher's own page" if tier == "official" \
        else "%d independent source(s)" % n if n else "the client's competitor workbook"
    return "stated in the client-supplied competitor workbook, from %s" % where


def _write(row, lab, val, srcs, tier):
    row["cv"] = val
    row["srcC"] = list(srcs or [])
    row["tierC"] = tier or "workbook"
    row["whyC"] = _why(tier, srcs)
    row["cOrigin"] = "workbook"          # the pipeline may replace this; it never may the reverse
    row.setdefault("l", lab)
    return row


def _new_row(lab, val, srcs, tier):
    return {"k": lab, "l": lab, "u": "", "cv": val, "cn": None, "kv": None, "kn": None,
            "hi": None, "p": "s", "cp": "s",
            "srcC": list(srcs or []), "srcK": [], "tierC": tier or "workbook",
            "tierK": None, "whyC": _why(tier, srcs), "whyK": None,
            "cOrigin": "workbook", "noCounterpart": True}


# ---------------------------------------------------------------------------------


def _demo():
    ok = True

    def ck(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-64s %s" % (label, "ok" if good else "FAIL got=%r want=%r" % (got, want)))

    print("the typography that hid every CAESAR:")
    ck("the panel's 6x6 and the workbook's 6×6 are the same tokens",
       norm_tokens("CAESAR 6x6"), norm_tokens("CAESAR 6×6"))
    ck("the maker is stripped off the panel label",
       product_of("KNDS · CAESAR 6x6"), "CAESAR 6x6")

    idx = {}
    for p, cid in [("ARCHER Mobile Howitzer", "bae-systems"),
                   ("Archerfish Mine Disposal System", "bae-systems"),
                   ("CAESAR 6×6", "knds"), ("CAESAR 8×8", "knds"),
                   ("CAESAR Mk2", "knds")]:
        idx.setdefault(tuple(norm_tokens(p)), []).append({"name": p, "comp_id": cid})

    print("matching, and the ways it must refuse:")
    ck("an exact name matches through the typography",
       match_product("CAESAR 6x6", idx)[0]["name"], "CAESAR 6×6")
    ck("a unique whole-token prefix matches",
       match_product("Archer", idx)[0]["name"], "ARCHER Mobile Howitzer")
    ck("...and never reaches Archerfish, which only SHARES letters",
       match_product("Archerf", idx)[0], None)
    ck("a bare CAESAR is three different guns and is refused",
       match_product("CAESAR", idx)[0], None)
    ck("a product belonging to another competitor is not borrowed",
       match_product("CAESAR 6x6", idx, comp_id="saab")[0], None)

    print("precedence -- the operator's own rule:")
    specs = [{"l": "Calibre", "cv": "155/52", "kv": "155 mm"},
             {"l": "Max range", "cv": None, "kv": "Up to ~30 km"}]
    prod = {"specs": [{"k": "Calibre", "v": "WRONG", "srcs": ["u"], "tier": "official"},
                      {"k": "Max range", "v": "40 km", "srcs": ["u"], "tier": "official"}]}
    filled, appended, skipped = plan_one(specs, prod)
    ck("a value the pipeline already states is NOT overwritten", len(filled), 1)
    ck("...and the one it filled is the empty one", filled[0][1], "Max range")
    ck("...and the refusal is counted, not silent",
       skipped["the pipeline already states this"], 1)

    print("appending, and the near-duplicate guard:")
    specs2 = [{"l": "Max range", "cv": None, "kv": "30 km"}]
    prod2 = {"specs": [{"k": "range", "v": "40 km", "srcs": [], "tier": "official"},
                       {"k": "Crew", "v": "3", "srcs": [], "tier": "official"}]}
    filled2, appended2, skipped2 = plan_one(specs2, prod2)
    ck("'range' is not appended beside 'Max range'",
       [a[0] for a in appended2], ["Crew"])
    ck("...and that is counted too",
       skipped2["a near-duplicate label is already on the panel"], 1)

    print("what gets written:")
    r = _write({"l": "Max range"}, "Max range", "40 km", ["https://x"], "official")
    ck("the value lands", r["cv"], "40 km")
    ck("it is tagged workbook so the pipeline can replace it", r["cOrigin"], "workbook")
    ck("it carries its source", r["srcC"], ["https://x"])
    ck("an unlabelled bullet cannot join a panel row",
       spec_rows({"specs": [{"k": "", "v": "155 mm/52 cal"}]}), {})

    print("\n%s" % ("all checks passed" if ok else "FAILED"))
    return 0 if ok else 1


def _run(apply_it):
    import psycopg2
    import spec_number
    from aliases import same_org
    from revive_matchups import edge_of, verdict_of

    con = psycopg2.connect(os.environ["DSN"])
    cur = con.cursor()
    # `company` is selected because the maker guard below reads it. Leaving it out made
    # same_org() compare against None, which refused all 51 matches -- failing CLOSED,
    # which is the direction a guard should fail, but refusing everything all the same.
    cur.execute("SELECT comp_id, name, company, specs FROM serving.competitor_product "
                "WHERE withheld_reason IS NULL AND specs IS NOT NULL")
    index = {}
    for comp_id, name, company, specs in cur.fetchall():
        index.setdefault(tuple(norm_tokens(name)), []).append(
            {"comp_id": comp_id, "name": name, "company": company, "specs": specs or []})

    cur.execute("SELECT matchup_id, comp, bf, \"compBy\", \"bfBy\", specs, edge "
                "FROM serving.matchup WHERE origin='pipeline' ORDER BY matchup_id")
    rows = cur.fetchall()

    changes, nofill, skipped = [], collections.Counter(), collections.Counter()
    n_fill = n_new = 0
    for mid, comp, bf, compby, bfby, specs, edge in rows:
        specs = specs or []
        prod, why = match_product(product_of(comp), index)
        if prod is None:
            nofill[why] += 1
            continue
        # THE PRODUCT IS RIGHT; IS THE MAKER? A workbook product only speaks for the
        # company that built it. Five of the matches are the SAME company under two
        # names -- KNDS / "Nexter (KNDS France)", and the panel's "Advanced Weapons and
        # Equipment India" against the workbook's "AWEIL" -- and aliases.same_org, the
        # repo's own identity layer, is what knows that.
        #
        # The rest are joint ventures: IRRPL builds Kalashnikov's AK-203 under licence,
        # Adani builds Elbit's SkyStriker. Very likely the same hardware -- but saying so
        # is a judgement about corporate structure, not a fact this workbook states, and
        # publishing it would put one company's sourced figures under another's name on
        # a competitor profile. Refused, counted, and named, for a human to decide.
        if not same_org(compby or product_of(comp), prod.get("company")):
            nofill["different maker: %s vs workbook %s"
                   % (str(compby)[:28], str(prod.get("company"))[:28])] += 1
            continue
        filled, appended, skip = plan_one(specs, prod)
        skipped.update(skip)
        if not filled and not appended:
            nofill["nothing left to add"] += 1
            continue
        for row, lab, val, srcs, tier in filled:
            _write(row, lab, val, srcs, tier)
            n_fill += 1
        for lab, val, srcs, tier in appended:
            specs.append(_new_row(lab, val, srcs, tier))
            n_new += 1
        spec_number.fill(specs)
        changes.append((mid, comp, bf, specs, edge, edge_of(specs),
                        verdict_of(specs, compby or comp, bfby or bf),
                        len(filled), len(appended)))

    print("matchups: %d | filled from the workbook: %d" % (len(rows), len(changes)))
    print("rival cells filled: %d | rival specs appended: %d" % (n_fill, n_new))
    print()
    print("why the rest were not filled:")
    for k, v in nofill.most_common(8):
        print("   %-46s %d" % (str(k)[:46], v))
    print()
    print("values the workbook offered and this refused:")
    for k, v in skipped.most_common(8):
        print("   %-46s %d" % (str(k)[:46], v))
    print()
    print("%-6s %-34s %-20s %6s %7s %s" % ("id", "competitor", "KSSL", "edge", "->edge", "fill/new"))
    for mid, comp, bf, _s, e0, e1, _v, nf, na in changes[:20]:
        print("%-6s %-34s %-20s %6s %7s %d/%d"
              % (mid, str(comp)[:34], str(bf)[:20], e0, e1, nf, na))

    # NOTHING THE PIPELINE GROUNDED MAY MOVE. plan_one refuses to overwrite, and this
    # is the second reading of the same promise, over the rows as they will be stored.
    if not apply_it:
        print("\ndry run -- nothing written. Re-run with --apply")
        return 0
    for mid, _c, _b, specs, _e0, e1, verd, _nf, _na in changes:
        cur.execute("UPDATE serving.matchup SET specs=%s, edge=%s, verdict=%s "
                    "WHERE matchup_id=%s AND origin='pipeline'",
                    (json.dumps(specs), e1, verd, mid))
    con.commit()
    print("\napplied to %d matchup(s)" % len(changes))
    return 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        sys.exit(_demo())
    sys.exit(_run("--apply" in sys.argv))
