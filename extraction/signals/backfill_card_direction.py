"""Re-run the threat gate over the cards already on the dashboard.

    python backfill_card_direction.py             # dry run -- prints, changes nothing
    python backfill_card_direction.py --apply     # demote / re-point the rows it prints
    python backfill_card_direction.py --levels    # only audit serving.competitors.threat

serving_fill.py is fixed for every card written from now on, and it will never revisit
these: a card is keyed pl_<document_id> and the document queue excludes any document that
already produced one. So the 74 threat cards standing today were all graded by the gate
that was wrong, and nothing in the normal pipeline will regrade them.

WHAT IT CHANGES, and what it refuses to.

  RESOLVE   "Anduril Industries" -> "Anduril", "BAE Systems Bofors" -> "BAE Systems".
            The card is about a tracked rival written under a division or suffix. It stays
            a threat and its company is re-pointed at the parent, which is also what makes
            it appear on that rival's profile -- the join there is on the name.

  DEMOTE    Huntington Ingalls Industries, Northrop Grumman, L3Harris, Czechoslovak
            Group, Edge Group, Diehl Defence, F3 Group. Real defence companies; none of
            them is a rival KSSL's reader tracks, and a threat badge on one points at a
            profile that does not exist. dir becomes watch and dir_reason records why.

  DEMOTE    a card whose event is outside every KSSL line. A rival winning a naval radar
            contract is news about a rival, not a threat to a maker of guns and shells.

  NEVER     delete. The badge was the wrong claim; the article is fine. A demoted card
            keeps its place in the feed, its evidence and its link -- it stops being red.

  NEVER     touch a card it could not grade. A card with no category and a competitor row
            with no products is UNASSESSED, and this pass has no opinion on it: severity
            null already sorts it below every graded card wherever cards are ordered.

It also audits serving.competitors.threat, which is a three-value column with no
constraint on it and holds a paragraph of partnership prose on two rows. The repair for
that lives in db/migrations/2026-09-06_threat_severity.sql, because moving prose between
columns is a schema change's job and this script's --apply should not smuggle one in;
here it is only reported, loudly.
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import threat_gate  # noqa: E402

DSN = os.environ.get(
    "KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")


def load_competitors(cur):
    """name -> {threat, products}. The roster the badge is a claim about."""
    cur.execute("SELECT name, threat, products FROM serving.competitors "
                "WHERE origin='pipeline' AND name IS NOT NULL")
    out = {}
    for name, threat, products in cur.fetchall():
        if isinstance(products, str):
            import json
            try:
                products = json.loads(products or "[]")
            except ValueError:
                products = []
        out[name.strip()] = {"threat": threat, "products": products or []}
    return out


def load_cards(cur):
    cur.execute("SELECT id, dir, company, tags, meta, sec, lane, title "
                "FROM serving.signal_card WHERE origin='pipeline'")
    return [{"id": r[0], "dir": r[1], "company": r[2], "tags": r[3], "meta": r[4],
             "sec": r[5] if isinstance(r[5], list) else [], "lane": r[6], "title": r[7]}
            for r in cur.fetchall()]


def plan(cards, comps, gate):
    """-> (resolves, demotions, unassessed, kept). Pure, so it is testable without a DB."""
    resolves, demotions, unassessed, kept = [], [], [], []
    for card in cards:
        if card["dir"] != "threat":
            continue
        name = gate.resolve(card["company"])
        comp = comps.get(name) if name else None
        newdir, why, imp, sev = threat_gate.grade(card, comp, gate)
        if newdir != "threat":
            demotions.append((card, why, imp))
            continue
        if name and name != card["company"]:
            resolves.append((card, name, imp, sev))
        elif not imp.assessed:
            unassessed.append((card, imp))
        else:
            kept.append((card, sev, imp))
    return resolves, demotions, unassessed, kept


def audit_levels(cur):
    """Rows whose `threat` is not a level. Reported, never repaired here."""
    cur.execute("SELECT comp_id, name, threat FROM serving.competitors "
                "WHERE threat IS NOT NULL")
    return [(cid, name, t) for cid, name, t in cur.fetchall()
            if threat_gate.looks_like_prose(t)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the demotions and re-points (default: dry run)")
    ap.add_argument("--levels", action="store_true",
                    help="only audit serving.competitors.threat")
    ap.add_argument("--dsn", default=DSN)
    args = ap.parse_args()

    import psycopg2
    con = psycopg2.connect(args.dsn)
    cur = con.cursor()

    bad_levels = audit_levels(cur)
    if bad_levels:
        print("serving.competitors.threat holds %d value(s) that are not a level:"
              % len(bad_levels))
        for cid, name, t in bad_levels:
            print("  %-24s %s" % (cid[:24], (str(t)[:96] + "...") if len(str(t)) > 96 else t))
        print("  -> db/migrations/2026-09-06_threat_severity.sql moves these to "
              "threatNote and adds the CHECK that stops the next one.\n")
    else:
        print("serving.competitors.threat: every stored value is a level.\n")
    if args.levels:
        con.close()
        return

    comps = load_competitors(cur)
    try:
        gate = threat_gate.RosterGate(list(comps))
    except threat_gate.EmptyRosterError as e:
        # Refuse the run. A backfill that cannot read the roster would demote the entire
        # feed, and "everything is watch now" is not a safer wrong answer than the one
        # being fixed -- it is a different one.
        print("REFUSING: %s" % e)
        con.close()
        sys.exit(2)

    cards = load_cards(cur)
    threats = [c for c in cards if c["dir"] == "threat"]
    resolves, demotions, unassessed, kept = plan(cards, comps, gate)

    print("%d card(s) stored, %d claiming dir=threat" % (len(cards), len(threats)))
    print("\nRE-POINTED to the parent on the served roster (%d):" % len(resolves))
    for card, name, imp, sev in resolves:
        print("  %-28s -> %-24s  %-8s %s"
              % (card["company"][:28], name[:24], sev or "unassessed", imp.state))
    print("\nDEMOTED to watch (%d):" % len(demotions))
    for card, why, imp in demotions:
        print("  %-28s  %-24s %s" % (card["company"][:28], why, card["title"][:44]))
    print("\nSTILL a threat, impact NOT ASSESSED (%d) -- left alone, sorts last:"
          % len(unassessed))
    for card, imp in unassessed:
        print("  %-28s  %s" % (card["company"][:28], "; ".join(imp.basis)[:70]))
    print("\nSTILL a threat, graded (%d):" % len(kept))
    for card, sev, imp in kept:
        print("  %-28s  %-8s %s" % (card["company"][:28], sev or "unassessed", imp.state))

    after = len(threats) - len(demotions)
    print("\nthreat cards: %d before -> %d after (%d demoted, %d re-pointed)"
          % (len(threats), after, len(demotions), len(resolves)))

    if not args.apply:
        print("\n(dry run -- nothing written. Re-run with --apply.)")
        con.close()
        return

    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='serving' "
                "AND table_name='signal_card' AND column_name='dir_reason'")
    has_reason = bool(cur.fetchone())
    n = 0
    for card, why, _imp in demotions:
        if has_reason:
            cur.execute("UPDATE serving.signal_card SET dir='watch', dir_reason=%s, "
                        "updated_at=now() WHERE id=%s", (why, card["id"]))
        else:
            cur.execute("UPDATE serving.signal_card SET dir='watch', updated_at=now() "
                        "WHERE id=%s", (card["id"],))
        # The panel behind the card carries the same direction. Leaving it would make the
        # drawer contradict the row it was opened from -- the fault fix_card_dates.py
        # documents for the date.
        cur.execute("UPDATE serving.signal_detail SET dir='watch', updated_at=now() "
                    "WHERE id=%s", (card["id"],))
        n += 1
    for card, name, _imp, _sev in resolves:
        cur.execute("UPDATE serving.signal_card SET company=%s, updated_at=now() "
                    "WHERE id=%s", (name, card["id"]))
        n += 1
    con.commit()
    con.close()
    print("\napplied to %d row(s)." % n)
    if not has_reason:
        print("dir_reason column absent -- demotions applied, reasons NOT stored. "
              "Run db/migrations/2026-09-06_threat_severity.sql, then re-run to record them.")


if __name__ == "__main__":
    main()
