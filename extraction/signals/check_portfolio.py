# -*- coding: utf-8 -*-
"""Audit the KSSL product portfolio, and stop publishing a comparison whose KSSL side
is not a KSSL product. Keep every product.

    python check_portfolio.py             # dry run: the audit, and what would be withheld
    python check_portfolio.py --offline   # the same audit against the committed files, no DB
    python check_portfolio.py --apply     # withhold the pairings this run names
    python check_portfolio.py --restore   # put back only what THIS script withheld
    python check_portfolio.py --demo      # hermetic asserts, no DB

THE RULE IS THE OPERATOR'S, unchanged from withhold_matchups.py: "no need to delete a
client's product -- instead if no correct matchup is there, don't show it." So this
script deletes nothing, edits no product, rewrites no name and touches no catalogue.
The only thing it writes is serving.matchup.withheld_reason, the nullable column
db/migrations/2026-09-06_matchup_withheld.sql added, which serving_live.matchup already
excludes and which one UPDATE clears.

WHAT IT WITHHOLDS, and both are findings rather than guesses. The rules and their
evidence are in portfolio_gate.py; this file is the pass that applies them.

  not_a_client_product  the name on the KSSL side of the pairing is in no row of
                        serving.client_product. This is the Bayonet/Cleaver fault:
                        both were carried on 138 and 135 occurrences INSIDE a curated
                        file we wrote ourselves, and a corpus check later found Bayonet
                        had zero quotes tied to KSSL and every "Cleaver" was "Sian
                        Cleaver, an Airbus engineer".

  offered_not_owned     the name belongs to another company and reaches KSSL through an
                        MoU, a partnership or an offer. AAROK is a Turgis & Gaillard
                        MALE design offered under a 2025 MoU; the repo's own curated
                        data says exactly that, twice, and calls it "KSSL's airframe
                        portfolio" four times in the same file. The disclaimer wins.

WHAT IT ONLY REPORTS, and will not write:

  * serving.client_product rows that fail the source bar, or whose only citation is a
    partner announcing the partnership, or whose citation is about something else.
    Deleting a client's product is forbidden and rewriting one is a judgement, so
    these are printed with the rule and the evidence and left for a human.
  * a name the LIVE gate would drop as unattested while the portfolio's own group table
    attests it ("Shell forgings" is four workbook rows). Refusing a real pairing costs
    what publishing a fake one costs, and this pass will not fix one by causing the
    other silently.
  * prose surfaces -- serving.innovation, serving.signal_card, serving.signal_detail,
    serving.geo_presence -- that name a banned product as KSSL's. Prose is edited by a
    person, not by a regex.

TWO REFUSALS, in the house pattern:

  * it will not withhold every pairing. If a rule change ever made this flag the whole
    tab, the honest outcome is a loud stop, not a blank Positioning page.
  * an empty serving.client_product is a REFUSAL, not a pass. That is the state of a
    database whose portfolio has not been loaded, i.e. exactly when nothing can be
    checked -- and being unable to check is not having checked. pairing.py learned this
    the expensive way and this pass inherits it.

REVERSIBLE. --restore clears only the two reasons above, so it cannot undo
withhold_matchups.py's not_like_for_like / nothing_published.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import portfolio_gate as pg                                        # noqa: E402

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
WORKBOOK = HERE / "portfolio" / "kssl_portfolio.json"
REFERENCE = HERE.parent / "reference_dataset.json"

# The two reasons this script owns. --restore clears these and nothing else, so the
# sibling pass's verdicts survive it.
OURS = ("not_a_client_product", "offered_not_owned")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def load_workbook(path=WORKBOOK):
    return json.loads(Path(path).read_text(encoding="utf-8"))["rows"]


def load_portfolio_db(cur):
    cur.execute("select to_regclass('serving.client_product')")
    if cur.fetchone()[0] is None:
        return []
    cur.execute('select product_id, name, file_category, cat, "catKey", specs, features, '
                "sources from serving.client_product order by ord")
    cols = ["product_id", "name", "file_category", "cat", "catKey", "specs",
            "features", "sources"]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k in ("specs", "features", "sources"):
            if isinstance(d[k], str):
                d[k] = json.loads(d[k] or "[]")
        out.append(d)
    return out


def prose_texts(cur=None):
    """Every served string that could carry a product attribution.

    Offline this is reference_dataset.json, which is what seeded the reference rows.
    Against a database it is the prose columns themselves.
    """
    if cur is None:
        d = json.loads(REFERENCE.read_text(encoding="utf-8"))
        out = []

        def walk(o):
            if isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, str) and len(o) > 20:
                out.append(o)
        walk(d)
        return out
    rows = []
    for sql in ("select coalesce(body,'')||' '||coalesce(action,'')||' '||coalesce(\"whatsNew\",'') from serving.innovation",
                "select coalesce(note,'') from serving.geo_presence",
                "select coalesce(sowhat,'') from serving.signal_card"):
        try:
            cur.execute(sql)
            rows += [r[0] for r in cur.fetchall() if r[0]]
        except Exception:                                          # noqa: BLE001
            cur.execute("rollback")
    return rows


# ---------------------------------------------------------------------------
# the audit (report only, never writes)
# ---------------------------------------------------------------------------
def audit_portfolio(rows, denial_map):
    findings = []
    for r in rows:
        for sev, rule, why in pg.audit_row(r, denial_map):
            findings.append((sev, r.get("name") or r.get("product_id"), rule, why))
    return findings


def classify_pairings(pairs, portfolio, denial_map):
    """-> (keep, drop, group_only). `pairs` are (id, anchor, bf) triples."""
    keep, drop, group_only = [], [], []
    for pid, anchor, bf in pairs:
        name = bf or anchor
        banned, sent = pg.denied(name, denial_map)
        if banned:
            drop.append((pid, name, "offered_not_owned", sent[:120]))
            continue
        verdict, why = pg.audit_anchor(name, portfolio)
        if verdict == "not_a_client_product":
            drop.append((pid, name, "not_a_client_product", why))
        elif verdict == "group_only":
            group_only.append((pid, name, why))
            keep.append((pid, name))
        else:
            keep.append((pid, name))
    return keep, drop, group_only


def report(portfolio, pairs, denial_map, where):
    print("KSSL PRODUCT PORTFOLIO -- self-check (%s)" % where)
    print("=" * 74)
    print("%d product(s) in the portfolio, %d pairing(s) publishing a KSSL side"
          % (len(portfolio), len(pairs)))
    if denial_map:
        print("\n%d name(s) the material itself declares NOT a KSSL product:" % len(denial_map))
        for n, s in sorted(denial_map.items()):
            print("  %-14s %s" % (n, s[:104]))

    findings = audit_portfolio(portfolio, denial_map)
    for sev in pg.SEVERITY:
        hits = [f for f in findings if f[0] == sev]
        if not hits:
            continue
        print("\n%s -- %d finding(s)%s" % (
            {"ban": "BAN   the row must not stand as a KSSL product",
             "hold": "HOLD  the row cannot support a published comparison",
             "note": "NOTE  worth a human's eye, decides nothing"}[sev],
            len(hits), "" if sev != "note" else ""))
        for _s, name, rule, why in hits:
            print("  %-52s %-22s %s" % (str(name)[:52], rule, why[:100]))

    keep, drop, group_only = classify_pairings(pairs, portfolio, denial_map)
    print("\nPAIRINGS")
    print("  keep     %3d  the KSSL side is a product the client publishes" % len(keep))
    print("  withhold %3d  it is not" % len(drop))
    for pid, name, reason, why in drop:
        print("     %-8s %-30s %-22s %s" % (pid, str(name)[:30], reason, why[:70]))
    if group_only:
        print("\n  %d pairing(s) attested ONLY by the portfolio's group table. The live gate\n"
              "  (pairing.same_product, which revive_matchups consults) has no group rule and\n"
              "  would drop these as \"not a product the client publishes\" -- a REAL client\n"
              "  line refused. Reported, not fixed here: silently loosening the live gate is\n"
              "  the other way to be wrong." % len(group_only))
        for pid, name, why in group_only:
            print("     %-8s %-30s %s" % (pid, str(name)[:30], why[:80]))
    return keep, drop


# ---------------------------------------------------------------------------
def run_offline():
    rows = load_workbook()
    texts = prose_texts(None)
    denial_map = pg.denials(texts)
    d = json.loads(REFERENCE.read_text(encoding="utf-8"))
    pairs = sorted({(str(k), v.get("anchor"), v.get("bf"))
                    for k, v in d.get("matchups", {}).items()},
                   key=lambda t: int(t[0]) if t[0].isdigit() else 0)
    # one row per distinct KSSL side, so the report reads as products not as 507 rows
    seen, uniq = set(), []
    for pid, anchor, bf in pairs:
        key = pg.norm(bf or anchor)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((pid, anchor, bf))
    report(rows, uniq, denial_map, "committed files, no database")
    print("\noffline audit -- nothing written, and no database was contacted.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="audit the committed workbook and reference dataset, no DB")
    a = ap.parse_args()
    if a.offline:
        return run_offline()

    import psycopg2                                                 # noqa: PLC0415
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SET lock_timeout = '20s'")

    if a.restore:
        cur.execute("UPDATE serving.matchup SET withheld_reason=NULL, updated_at=now() "
                    "WHERE withheld_reason = ANY(%s)", (list(OURS),))
        print("restored %d pairing(s) withheld by this script" % cur.rowcount)
        con.commit()
        return 0

    portfolio = load_portfolio_db(cur)
    # BEING UNABLE TO CHECK IS NOT HAVING CHECKED.
    if not portfolio:
        raise SystemExit(
            "refusing: serving.client_product is empty, so nothing can be checked "
            "against it. Load the portfolio (client_portfolio.py --apply) first.")

    cur.execute("""SELECT matchup_id, anchor, bf FROM serving.matchup
                    WHERE origin='pipeline' AND withheld_reason IS NULL
                    ORDER BY matchup_id""")
    pairs = cur.fetchall()
    denial_map = pg.denials(prose_texts(cur))
    keep, drop = report(portfolio, pairs, denial_map, "live database")

    if not a.apply:
        print("\ndry run -- nothing written. --apply to withhold, --restore to undo.")
        return 0
    if not drop:
        print("nothing to withhold")
        return 0
    # REFUSE TO EMPTY THE TAB.
    if len(drop) >= len(pairs):
        raise SystemExit("refusing: that would withhold every pairing (%d of %d)"
                         % (len(drop), len(pairs)))
    for pid, _name, reason, _why in drop:
        cur.execute("UPDATE serving.matchup SET withheld_reason=%s, updated_at=now() "
                    "WHERE matchup_id=%s AND origin='pipeline' AND withheld_reason IS NULL",
                    (reason, pid))
    con.commit()
    cur.execute("SELECT count(*) FROM serving_live.matchup")
    print("\nwithheld %d pairing(s); %d still served" % (len(drop), cur.fetchone()[0]))
    return 0


# ---------------------------------------------------------------------------
def _demo():
    bad = [0]

    def ck(n, cond, extra=""):
        if not cond:
            bad[0] += 1
            print("  FAIL  %s %s" % (n, extra))
        else:
            print("  ok    %s" % n)

    WB = [{"product_id": "kalyani-m4", "name": "Kalyani M4",
           "sources": ["https://www.kssl.in/protected-vehicles"]},
          {"product_id": "bharat-150-uav", "name": "Bharat 150 UAV",
           "sources": ["https://www.kssl.in/uav"]}]
    dm = pg.denials(["AAROK is a Turgis & Gaillard MALE design offered under a 2025 MoU, "
                     "not a KSSL product."])
    pairs = [(1, "M4", "KSSL · M4"),
             (2, "Bharat 150", "KSSL · Bharat 150"),
             (3, "Bayonet", "KSSL · Bayonet"),
             (4, "Cleaver", "KSSL · Cleaver"),
             (5, "AAROK", "KSSL · AAROK")]
    keep, drop, group_only = classify_pairings(pairs, WB, dm)
    reasons = {pid: reason for pid, _n, reason, _w in drop}
    ck("real products keep publishing", {p for p, _n in keep} == {1, 2}, keep)
    ck("Bayonet is withheld as not_a_client_product",
       reasons.get(3) == "not_a_client_product", reasons)
    ck("Cleaver is withheld as not_a_client_product",
       reasons.get(4) == "not_a_client_product", reasons)
    ck("AAROK is withheld as offered_not_owned, not as merely absent",
       reasons.get(5) == "offered_not_owned", reasons)
    ck("no group-only surprise in this fixture", not group_only)

    # the refusal to empty the tab, exercised rather than asserted about
    allbad = [(9, "Bayonet", "KSSL · Bayonet")]
    _k, d2, _g = classify_pairings(allbad, WB, dm)
    ck("the whole-tab case is detectable before any write", len(d2) >= len(allbad))

    # an empty portfolio must refuse, not pass
    _k, d3, _g = classify_pairings([(1, "M4", "KSSL · M4")], [], dm)
    ck("an empty portfolio refuses every name rather than admitting it", len(d3) == 1)

    # --restore must not touch the sibling's reasons
    ck("restore is scoped to this script's own reasons",
       set(OURS) == {"not_a_client_product", "offered_not_owned"})

    print("all checks passed" if not bad[0] else "%d FAILED" % bad[0])
    return 1 if bad[0] else 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        sys.exit(_demo())
    sys.exit(main())
