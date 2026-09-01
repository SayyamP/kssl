"""Remove blocked sources (Wikipedia and its mirrors) from the serving tables.

    python purge_blocked_sources.py --dry-run
    python purge_blocked_sources.py

WHAT IT DOES, and why it is not just a link-strip:

  matchup.specs   Each spec value carries `srcC`, its own citation list. Where
                  a value's ONLY citation is blocked, the VALUE is dropped, not
                  merely its link -- an unsourced number shown as though it were
                  sourced is worse than a missing row. Where a value has other
                  citations, only the blocked ones are removed.
  matchup.srcs    Blocked entries removed. A matchup left with no sources keeps
                  its comparison but is honestly uncited.
  competitors.srcs, innovation.sources, geo_presence.src/srcnote,
  company_source, source_registry
                  Blocked URLs removed; rows that exist only to hold a blocked
                  URL are deleted.

Never touches `origin='reference'` rows unless --include-reference is given:
they are invisible to the UI, and rewriting them would lose the hand-curated
baseline the pipeline is measured against.
"""
import argparse
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from source_policy import filter_sources, is_blocked                 # noqa: E402


def load_env(p):
    out = {}
    if not os.path.exists(p):
        return out
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# A spec row compares two sides and cites each separately: the competitor's
# value `cv` is backed by srcC/csrc, the client's value `kv` by srcK/ksrc.
# The rule has to apply PER SIDE -- dropping a whole row because the client's
# figure came from a blocked source would also destroy a competitor figure that
# is properly cited, and vice versa.
_SIDES = (("cv", ("srcC", "csrc"), ("cn", "cp")),
          ("kv", ("srcK", "ksrc"), ("kn", "kp", "whyK", "tierK")))


def clean_specs(specs):
    """-> (new_specs, dropped_values, stripped_links).

    A value whose ONLY citation is blocked is removed along with its citation
    and its side's annotations -- leaving the number while deleting the link
    would present an unsourced claim as a sourced one. `whyK` in particular
    says "sourced", which would become a lie.
    """
    if not specs:
        return specs, 0, 0
    rows = specs if isinstance(specs, list) else json.loads(specs)
    out, dropped, stripped = [], 0, 0
    for r in rows:
        if not isinstance(r, dict):
            out.append(r)
            continue
        r = dict(r)
        for val_key, src_keys, extra_keys in _SIDES:
            present = [k for k in src_keys if isinstance(r.get(k), list) and r.get(k)]
            if not present:
                continue
            all_src = [u for k in present for u in r[k]]
            kept = filter_sources(all_src)
            if not kept:
                # every citation for this side was blocked -> the side goes
                dropped += 1
                for k in list(src_keys) + list(extra_keys) + [val_key]:
                    r.pop(k, None)
            elif len(kept) != len(all_src):
                stripped += 1
                for k in present:
                    r[k] = filter_sources(r[k])
                    if not r[k]:
                        r.pop(k, None)
        # a row with neither side left is not a comparison any more
        if r.get("cv") is None and r.get("kv") is None:
            continue
        out.append(r)
    return out, dropped, stripped


def clean_srcs(srcs):
    """-> (new_srcs, removed). Entries are {url,label} objects."""
    if not srcs:
        return srcs, 0
    rows = srcs if isinstance(srcs, list) else json.loads(srcs)
    out, removed = [], 0
    for r in rows:
        u = r.get("url") if isinstance(r, dict) else r
        if is_blocked(u):
            removed += 1
            continue
        out.append(r)
    return out, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--env", default="/opt/kssl/app/extraction/.env")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-reference", action="store_true")
    a = ap.parse_args()

    import psycopg2
    env = load_env(a.env)
    dsn = a.dsn or env.get("KSSL_DSN") or env.get("KSSL_CORPUS_DSN")
    if not dsn:
        sys.exit("no DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    org = "" if a.include_reference else " AND origin='pipeline'"
    tally = {}

    # ---- matchup.specs and .srcs ----------------------------------------
    cur.execute("SELECT matchup_id, specs, srcs FROM serving.matchup WHERE true" + org)
    spec_upd, src_upd, vals_dropped, links_stripped, srcs_removed = [], [], 0, 0, 0
    for mid, specs, srcs in cur.fetchall():
        ns, d, st = clean_specs(specs)
        if d or st:
            spec_upd.append((mid, ns))
            vals_dropped += d
            links_stripped += st
        nsr, rm = clean_srcs(srcs)
        if rm:
            src_upd.append((mid, nsr))
            srcs_removed += rm
    tally["matchup: spec VALUES dropped (blocked was their only source)"] = vals_dropped
    tally["matchup: spec values keeping other sources (link stripped)"] = links_stripped
    tally["matchup: source entries removed"] = srcs_removed
    tally["matchup rows touched"] = len({m for m, _ in spec_upd} | {m for m, _ in src_upd})

    # ---- competitors.srcs -----------------------------------------------
    cur.execute("SELECT comp_id, srcs FROM serving.competitors WHERE true" + org)
    comp_upd, comp_rm = [], 0
    for cid, srcs in cur.fetchall():
        n, rm = clean_srcs(srcs)
        if rm:
            comp_upd.append((cid, n))
            comp_rm += rm
    tally["competitors: source entries removed"] = comp_rm

    # ---- flat url/text columns ------------------------------------------
    flat = []
    for tbl, key, cols in (
            ("serving.innovation", "area, ord", ("sources", "url")),
            ("serving.geo_presence", "comp_id, country, ord", ("src", "srcnote")),
            ("serving.partner", "id", ("src", "srcnote")),
    ):
        for col in cols:
            cur.execute("SELECT %s, %s FROM %s WHERE %s ILIKE '%%wikipedia%%'%s"
                        % (key, col, tbl, col, org))
            for row in cur.fetchall():
                flat.append((tbl, key, col, row))
    tally["flat url/text fields citing a blocked domain"] = len(flat)

    # ---- registry rows that exist only to hold a blocked url -------------
    cur.execute("SELECT ord, url FROM serving.source_registry WHERE true" + org)
    reg_del = [o for o, u in cur.fetchall() if is_blocked(u)]
    cur.execute("SELECT company, ord, url FROM serving.company_source WHERE true" + org)
    cs_del = [(c, o) for c, o, u in cur.fetchall() if is_blocked(u)]
    tally["source_registry rows to delete"] = len(reg_del)
    tally["company_source rows to delete"] = len(cs_del)

    print("BLOCKED DOMAINS: wikipedia.org and mirrors")
    print()
    for k, v in tally.items():
        print("  %-58s %d" % (k, v))

    if a.dry_run:
        print("\nDRY RUN -- nothing written.")
        return

    for mid, ns in spec_upd:
        cur.execute("UPDATE serving.matchup SET specs=%s, updated_at=now() "
                    "WHERE matchup_id=%s", (json.dumps(ns), mid))
    for mid, nsr in src_upd:
        cur.execute("UPDATE serving.matchup SET srcs=%s, updated_at=now() "
                    "WHERE matchup_id=%s", (json.dumps(nsr), mid))
    for cid, n in comp_upd:
        cur.execute("UPDATE serving.competitors SET srcs=%s, updated_at=now() "
                    "WHERE comp_id=%s", (json.dumps(n), cid))
    for tbl, key, col, row in flat:
        keys = [k.strip() for k in key.split(",")]
        where = " AND ".join("%s=%%s" % k for k in keys)
        cur.execute("UPDATE %s SET %s=NULL, updated_at=now() WHERE %s"
                    % (tbl, col, where), tuple(row[:len(keys)]))
    for o in reg_del:
        cur.execute("DELETE FROM serving.source_registry WHERE ord=%s", (o,))
    for c, o in cs_del:
        cur.execute("DELETE FROM serving.company_source WHERE company=%s AND ord=%s", (c, o))
    con.commit()
    print("\napplied.")


if __name__ == "__main__":
    main()
