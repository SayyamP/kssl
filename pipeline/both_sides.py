"""Publish only the spec rows where BOTH products have a sourced value.

    python both_sides.py --report
    python both_sides.py --apply
    python both_sides.py --apply --vps
    python both_sides.py --demo

A comparison needs two numbers. Positioning has been showing rows where only one side had
one, and the missing half rendered as a dash that reads like a deficiency rather than an
absence of evidence.

The matchups already carry per-field provenance on both sides — `srcK`/`tierK` for the
KSSL value and `srcC`/`tierC` for the rival's — which an earlier row-level count missed
entirely, so "9 of 204 sourced" understated what is actually here. This measures it at the
FIELD level, which is the level a comparison is actually made at.

THE RULE, PER SPEC ROW
----------------------
Keep the row when both sides can show their number:

  KSSL side     the export catalogue's value if the catalogue publishes that field
                (official, and preferred), otherwise the archived value ONLY if it
                carries at least one source in `srcK`
  rival side    a value in `cv` with at least one source in `srcC`

Anything else is dropped — not blanked, dropped, because a row with one number is not a
comparison and should not occupy a line that looks like one.

`edge` is then recomputed over the rows that survived. An edge computed across five
fields and carried onto the two that could be sourced is a claim about evidence that was
thrown away.
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
from apply_positioning import load_catalogue, match_product, norm_field  # noqa: E402
from positioning_gate import gate, product_of                            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")


def sourced(v):
    return bool(v) and (isinstance(v, list) and len(v) > 0)


def rebuild_specs(specs, cat_entry):
    """(kept, dropped, upgraded) for one matchup's spec table."""
    kept, dropped, upgraded = [], [], 0
    for sp in specs or []:
        sp = dict(sp)
        cv, cn = sp.get("cv"), sp.get("cn")
        # the rival must state a value AND show where it came from
        if not cv or not sourced(sp.get("srcC")):
            dropped.append((sp.get("l"), "rival value unsourced"))
            continue
        field = norm_field(sp.get("l"))
        src = (cat_entry or {}).get(field) if field else None
        if src:
            # KSSL's own catalogue beats anything archived about KSSL
            if (sp.get("kv") or "") != src["value"]:
                upgraded += 1
            sp["kv"] = src["value"]
            sp["kp"] = "official"
            sp["ksrc"] = {"url": src["url"], "page": src["page"], "line": src["line"]}
            sp["srcK"] = [src["url"]]
            sp["tierK"] = "official"
            sp["whyK"] = "published in KSSL's own export catalogue"
            m = re.search(r"-?\d+(?:\.\d+)?", src["value"])
            sp["kn"] = float(m.group(0)) if m else None
        elif not (sp.get("kv") and sourced(sp.get("srcK"))):
            dropped.append((sp.get("l"), "KSSL value unsourced"))
            continue
        kept.append(sp)
    return kept, dropped, upgraded


def edge_of(specs):
    """Share of directly comparable fields KSSL leads on, or None.

    Only fields where BOTH sides parsed to a number can be scored: "Gas Operated,
    Rotating Bolt" against "bolt" is a real comparison for a reader and not an arithmetic
    one, and counting it would invent a winner.
    """
    both = [s for s in specs if s.get("kn") is not None and s.get("cn") is not None]
    if not both:
        return None
    return int(round(100.0 * sum(1 for s in both if s.get("hi") is False) / len(both)))


def run(apply_it, to_vps):
    import psycopg2 as pg
    cat = load_catalogue()
    with pg.connect(DSN, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            cur.execute("""select matchup_id, cat, bf, comp, specs, edge
                           from serving.matchup where origin='pipeline' order by matchup_id""")
            rows = cur.fetchall()

        keep, drop_ids, stats = [], [], {"refused": 0, "no_comparable": 0,
                                         "upgraded": 0, "fields_kept": 0, "fields_dropped": 0}
        for mid, cat_name, bf, comp, specs, edge in rows:
            verdict, _, _ = gate(bf, comp)
            # UNRESOLVED IS NOT PERMISSION. positioning_gate returns "unresolved"
            # when it cannot establish a kind for either name -- which is every UAV
            # pairing in the archive, because it reads the kind off the product NAME
            # and "Bayonet", "SkyStriker" and "Shahed-136" say nothing about kind.
            # Publishing on an unresolved verdict is how the gate came to protect
            # nothing while appearing to run.
            if verdict in ("refuse", "unresolved"):
                drop_ids.append(mid)
                stats["refused"] += 1
                continue
            _, entry = match_product(product_of(bf), cat)
            kept, dropped, up = rebuild_specs(specs, entry)
            stats["upgraded"] += up
            stats["fields_kept"] += len(kept)
            stats["fields_dropped"] += len(dropped)
            if not kept:
                drop_ids.append(mid)
                stats["no_comparable"] += 1
                continue
            keep.append((mid, bf, comp, kept, edge_of(kept)))

        print("pipeline matchups: %d" % len(rows))
        print("  publishable        %4d   every spec row sourced on BOTH sides" % len(keep))
        print("  dropped: refused   %4d   not a like-for-like comparison" % stats["refused"])
        print("  dropped: no rows   %4d   nothing both sides could show" % stats["no_comparable"])
        print("  spec fields kept   %4d" % stats["fields_kept"])
        print("  spec fields cut    %4d   one side had no source" % stats["fields_dropped"])
        print("  KSSL values raised %4d   to the export catalogue's own figure" % stats["upgraded"])

        print("\n-- what a published row now looks like --")
        for mid, bf, comp, kept, e in keep[:4]:
            print("%6d  %s  vs  %s   edge=%s" % (mid, product_of(bf)[:22], product_of(comp)[:30], e))
            for s in kept[:4]:
                print("     %-18s KSSL %-22s | %-22s %s"
                      % (str(s.get("l"))[:18], str(s.get("kv"))[:22],
                         str(s.get("cv"))[:22], s.get("tierK", "")))

        if not apply_it:
            print("\nREPORT ONLY — nothing written. Re-run with --apply")
            return
        with cx.cursor() as cur:
            if drop_ids:
                cur.execute("delete from serving.matchup where matchup_id = any(%s)", (drop_ids,))
            for mid, bf, comp, kept, e in keep:
                cur.execute("update serving.matchup set specs=%s::jsonb, edge=%s, "
                            "updated_at=now() where matchup_id=%s",
                            (json.dumps(kept, ensure_ascii=False), e, mid))
        cx.commit()
        print("\nLOCAL: %d matchups deleted, %d rewritten" % (len(drop_ids), len(keep)))

    if to_vps:
        push()


def push():
    import subprocess
    root = HERE.parent
    host = key = None
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KSSL_VPS_HOST="):
            host = line.split("=", 1)[1].strip()
        elif line.startswith("KSSL_VPS_SSH_KEY="):
            key = line.split("=", 1)[1].strip()
    dump = subprocess.run(
        ["docker", "exec", "kssl-db", "pg_dump", "-U", "postgres", "-d", "kssl",
         "-Fc", "-t", "serving.matchup"], capture_output=True)
    if dump.returncode != 0:
        raise SystemExit("pg_dump failed")
    remote = ("cat > /tmp/mu.dump && "
              "docker exec -i kssl-db psql -U postgres -d kssl -c 'truncate serving.matchup;' && "
              "docker exec -i kssl-db bash -c 'cat > /tmp/mu.dump' < /tmp/mu.dump && "
              "docker exec kssl-db pg_restore -U postgres -d kssl --data-only -t matchup /tmp/mu.dump && "
              "docker exec kssl-db psql -U postgres -d kssl -tAc "
              "\"select origin, count(*) from serving.matchup group by 1;\"")
    p = subprocess.run(["ssh", "-i", key, "-o", "ConnectTimeout=25", "root@%s" % host, remote],
                       input=dump.stdout, capture_output=True)
    print((p.stdout + p.stderr).decode("utf-8", "replace")[-600:])
    if p.returncode != 0:
        raise SystemExit("VPS push failed")


def demo():
    entry = {"weight": {"value": "< 3.3", "url": "https://www.kssl.co.in/x",
                        "page": 33, "line": "Weight, kg < 3.3"}}
    specs = [
        # both sides sourced, and KSSL's catalogue publishes the field -> upgraded
        {"l": "Weight", "kv": "3.15 kg", "kn": 3.15, "srcK": ["a"],
         "cv": "7 kg", "cn": 7, "srcC": ["b"], "hi": False},
        # rival value with no source -> dropped, however good KSSL's side is
        {"l": "Calibre", "kv": "5.56", "srcK": ["a"], "cv": "7.62", "srcC": []},
        # KSSL value with no source and no catalogue field -> dropped
        {"l": "Barrel", "kv": "508 mm", "srcK": [], "cv": "610 mm", "srcC": ["b"]},
    ]
    kept, dropped, up = rebuild_specs(specs, entry)
    assert len(kept) == 1 and kept[0]["kv"] == "< 3.3", kept
    assert kept[0]["tierK"] == "official" and up == 1
    assert {d[0] for d in dropped} == {"Calibre", "Barrel"}, dropped
    assert edge_of(kept) == 100
    # a row nobody can score gives no edge rather than a made-up one
    assert edge_of([{"l": "Action", "kv": "gas", "cv": "bolt"}]) is None
    print("both_sides demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--vps", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        run(a.apply, a.vps)
