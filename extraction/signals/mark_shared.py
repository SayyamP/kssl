"""Give every organisation ONE id, so the Partnerships graph can draw the red line.

    python mark_shared.py --dry
    python mark_shared.py --apply
    python mark_shared.py --demo

The graph draws a partner in red when the tie carries `koel` or `shared` -- "this
company is also on KSSL's own roster". Not one tie had either flag, and two of
them are DRDO, which sits on KSSL's roster as "DRDO (ARDE) - ATAGS program". The
wiring compared the two labels as strings and required a common run of more than
five characters, so "drdo" (four) never matched anything.

The fix is the one this schema keeps needing: two writers, one id space. Every
label -- roster row, rival tie, competitor name -- is reduced to the identity
tokens it is actually known by (its acronym, its distinctive words), and labels
that share one are the same organisation. The cluster's id is then stamped onto
every tie as `cid`, which is what the graph, the shared index and the overlap
read all join on.

Three things fall out of one id space:
  * a rival's partner that is also KSSL's  -> the red line, plus `koel`
  * a rival that partners with KSSL itself -> `clientTie`, the shortest red line
  * one partner serving several rivals     -> the "carries N rival brands" count
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
from revive_partners import (acronyms, head_org, name_tokens, norm,  # noqa: E402
                             slug)


DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def identity(label):
    """The tokens this organisation is known by. Empty means unidentifiable.

    The whole name is always one of them. "Israel Aerospace Industries" is made
    entirely of words that name no company on their own -- a country and two
    industry words -- so token matching alone left it with no identity at all and
    it could not be joined to its own roster row, "Israel Aerospace Industries
    (IAI)". The full string matches only an identical name, which is safe, and it
    rescues every company whose name is generic in exactly this way."""
    head = head_org(label)
    bare = re.sub(r"\(.*?\)", " ", head)
    toks = set(acronyms(head)) | set(name_tokens(head))
    full = " ".join(w for w in re.split(r"[^a-z0-9]+", norm(bare)) if w)
    if full:
        toks.add("full:" + full)
    return toks


class Orgs:
    """Labels that share an identity token are one organisation.

    Deliberately not transitive-by-chaining beyond what the tokens say: a label
    joins the FIRST cluster it shares a token with, and clusters are merged only
    when a later label bridges them. The population here is small (a roster, a
    competitor list, a few dozen ties) and `report()` prints every cluster, so an
    over-merge is visible rather than silent."""

    def __init__(self):
        self.by_tok = {}          # token -> cluster index
        self.clusters = []        # [{"labels": [...], "toks": set()}]

    def add(self, label, prefer_id=None):
        toks = identity(label)
        if not toks:
            return None
        hit = sorted({self.by_tok[t] for t in toks if t in self.by_tok})
        if not hit:
            self.clusters.append({"labels": [label], "toks": set(toks),
                                  "id": prefer_id or slug(head_org(label)),
                                  "pinned": bool(prefer_id)})
            ix = len(self.clusters) - 1
        else:
            ix = hit[0]
            c = self.clusters[ix]
            for other in hit[1:]:                       # a bridging label merges
                o = self.clusters[other]
                c["labels"] += o["labels"]
                c["toks"] |= o["toks"]
                o["merged_into"] = ix
                for t in o["toks"]:
                    self.by_tok[t] = ix
                o["toks"] = set()
                o["labels"] = []
            if label not in c["labels"]:
                c["labels"].append(label)
            c["toks"] |= toks
            if prefer_id:
                # a competitor's own id wins: the tab already keys that company by it
                c["id"] = prefer_id
                c["pinned"] = True
        for t in toks:
            self.by_tok[t] = ix
        return self.clusters[ix]["id"]

    def finalise(self):
        """Name each cluster after its SHORTEST label.

        Ids are read by people in the served JSON, and the first label seen is an
        accident of load order: DRDO was about to be keyed
        `drdo-arde-atags-program` because the roster row happened to be read first."""
        for c in self.clusters:
            if c["labels"] and not c.get("pinned"):
                c["id"] = slug(head_org(min(c["labels"], key=len)))

    def key(self, label):
        toks = identity(label)
        for t in toks:
            if t in self.by_tok:
                return self.clusters[self.by_tok[t]]["id"]
        return None

    def report(self):
        out = []
        for c in self.clusters:
            if len(c["labels"]) > 1:
                out.append((c["id"], sorted(set(c["labels"]))))
        return out


def _rows(cur):
    out = []
    for cid, name, direction, partners in cur.fetchall():
        pl = partners if isinstance(partners, list) else json.loads(partners or "[]")
        out.append({"cid": cid, "name": name, "dir": direction, "partners": pl})
    return out


def load(cur):
    """Rivals from the pipeline; KSSL'S OWN SIDE FROM WHEREVER IT LIVES.

    THE CLIENT IS REFERENCE DATA AND ALWAYS WILL BE. KSSL's own pages (bharatforge /
    kssl.in) are deliberately kept off VPS-B, so nothing the pipeline writes can ever
    describe KSSL: its competitor row and all 11 rows of serving.partner are
    origin='reference'. Both queries here filtered on origin='pipeline', which is the
    correct filter for a rival and the exact wrong one for the client -- it returned
    zero roster rows and no client row, so `roster_by_key` and `client_key` were
    empty, `shared`/`koel`/`clientTie` were unreachable, and every partner on the tab
    rendered as the green "Direct Partner" fallback. Measured on staging 2026-09-06:
    11 roster rows, 0 of them visible to this function; 8 real overlaps (Rafael, Elbit,
    DRDO, Saab) drawn as though KSSL had no connection to them at all.

    The rival filter stays: a rival exists twice (Mahindra Defence is both 'mahindra'
    and 'MAHINDRA'), and feeding both to Orgs would pin two ids on one organisation.
    The client is fetched only if the pipeline did not already supply one, so the same
    duplicate cannot appear on this side either.
    """
    cur.execute("""SELECT comp_id, name, dir, partners FROM serving.competitors
                    WHERE origin='pipeline' ORDER BY ord""")
    comps = _rows(cur)
    if not any(c["dir"] == "client" for c in comps):
        cur.execute("""SELECT comp_id, name, dir, partners FROM serving.competitors
                        WHERE dir='client' ORDER BY ord LIMIT 1""")
        comps += _rows(cur)
    cur.execute("SELECT id, label, rel, ptype FROM serving.partner ORDER BY ord")
    roster = [{"id": r[0], "label": r[1], "rel": r[2], "ptype": r[3]}
              for r in cur.fetchall()]
    return comps, roster


def mark(comps, roster):
    """Stamp cid / shared / koel / clientTie / rivalCid onto every tie, in place.

    Split out of main() so the decision can be exercised without a database -- see
    _demo(). Returns (orgs, stats)."""
    client = next((c for c in comps if c["dir"] == "client"), None)
    orgs = Orgs()

    # competitors first: their own comp_id is the id the whole tab already uses
    for c in comps:
        orgs.add(c["name"], prefer_id=c["cid"])
    for r in roster:
        orgs.add(r["label"])
    for c in comps:
        for p in c["partners"]:
            orgs.add(p.get("label") or p.get("id") or "")

    orgs.finalise()
    roster_by_key = {}
    for r in roster:
        k = orgs.key(r["label"])
        if k:
            roster_by_key.setdefault(k, r)
    client_key = orgs.key(client["name"]) if client else None

    stats = {"ties": 0, "keyed": 0, "shared": 0, "client": 0, "rival": 0,
             "roster": len(roster), "client_row": bool(client)}
    rival_keys = {orgs.key(c["name"]): c["cid"] for c in comps
                  if c["dir"] != "client" and orgs.key(c["name"])}
    for c in comps:
        for p in c["partners"]:
            stats["ties"] += 1
            k = orgs.key(p.get("label") or "")
            if not k:
                continue
            stats["keyed"] += 1
            p["cid"] = k
            if client_key and k == client_key and c["dir"] != "client":
                # the rival's partner IS the client: the shortest red line there is
                p["clientTie"] = True
                p["shared"] = True
                stats["client"] += 1
            elif k in roster_by_key and c["dir"] != "client":
                r = roster_by_key[k]
                p["shared"] = True
                p["koel"] = {"rel": r["rel"] or "partner",
                             "role": r["ptype"] or "Partner", "label": r["label"]}
                stats["shared"] += 1
            if k in rival_keys and rival_keys[k] != c["cid"]:
                p["rivalCid"] = rival_keys[k]
                stats["rival"] += 1
    return orgs, stats


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    comps, roster = load(cur)
    orgs, stats = mark(comps, roster)

    # AN EMPTY ROSTER IS A BROKEN JOIN, NOT A FINDING. With no roster rows every tie
    # falls through to "not shared", which the tab renders as a confident green
    # "Direct Partner" -- the failure is silent and looks like an answer. Say so.
    if not roster:
        print("WARNING: serving.partner is empty -- no overlap can be found, and every "
              "tie will render as unshared. Check the roster is seeded.")
    if not stats["client_row"]:
        print("WARNING: no competitor row has dir='client' -- clientTie is unreachable.")

    print("%d tie(s), %d identified, %d also on the client roster, "
          "%d partner the client directly, %d are themselves rivals"
          % (stats["ties"], stats["keyed"], stats["shared"], stats["client"],
             stats["rival"]))
    print("\norganisations known by more than one name:")
    for cid, labels in orgs.report():
        print("  %-28s %s" % (cid, " | ".join(labels)))
    print("\nred lines:")
    for c in comps:
        for p in c["partners"]:
            if p.get("shared"):
                why = "partners with the client" if p.get("clientTie") else \
                      "also on the client roster"
                print("  %-26s -> %-34s %s" % (c["cid"], (p.get("label") or "")[:34], why))

    if apply:
        for c in comps:
            cur.execute("""UPDATE serving.competitors SET partners=%s, updated_at=now()
                            WHERE comp_id=%s AND origin='pipeline'""",
                        (json.dumps(c["partners"]), c["cid"]))
        for r in roster:
            k = orgs.key(r["label"])
            if k:
                cur.execute("UPDATE serving.partner SET cid=%s WHERE id=%s", (k, r["id"]))
        con.commit()
        print("\napplied.")
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return stats


def _demo():
    o = Orgs()
    o.add("Kalyani Strategic Systems", prefer_id="kalyani-strategic-systems")
    o.add("DRDO (ARDE) — ATAGS program")
    # the four-character acronym the old substring rule could not match
    assert o.key("DRDO") == o.key("DRDO (ARDE) — ATAGS program") != None
    assert o.key("Defence R&D Organisation (DRDO)") == o.key("DRDO")
    # a company known by its full name in one place and its acronym in another
    o.add("Israel Aerospace Industries (IAI)")
    assert o.key("IAI") == o.key("Israel Aerospace Industries (IAI)")
    # ...but two different companies stay apart
    o.add("Hanwha Land Systems")
    assert o.key("Hanwha Aerospace") != o.key("BAE Systems")
    assert o.key("Saab AB") != o.key("DRDO")
    # a generic word is not an identity: these must not become one organisation
    o.add("Defence Land Systems India")
    assert o.key("Advanced Defence Systems") != o.key("Kalyani Strategic Systems")
    # a name made only of generic words still has its own identity: the whole name
    o.add("Israel Aerospace Industries (IAI)")
    assert o.key("Israel Aerospace Industries") == o.key("IAI")
    assert o.key("Israel Weapon Industries") != o.key("IAI")
    # an unidentifiable label is left alone rather than merged into something
    assert o.key("Ltd") is None
    # the competitor's own id wins, so the tab's existing keys keep working
    o2 = Orgs()
    o2.add("Saab AB")
    o2.add("Saab", prefer_id="saab")
    o2.finalise()
    assert o2.key("Saab AB") == "saab", o2.key("Saab AB")
    # ...and where nothing is pinned, the shortest name wins over the load order
    o3 = Orgs()
    o3.add("DRDO (ARDE) — ATAGS program")
    o3.add("DRDO")
    o3.finalise()
    assert o3.key("DRDO") == "drdo", o3.key("DRDO")

    # --- the red line itself, on the shape staging actually has ---------------
    # This is the case the origin='pipeline' filter hid: KSSL's roster and KSSL's own
    # competitor row are reference data, the rivals are pipeline data, and the overlap
    # is only visible when both sides are loaded. Every partner below is a real row.
    roster = [{"id": "RAFAEL", "label": "Rafael Advanced Defense Systems (KRAS JV)",
               "rel": "jv", "ptype": "Missiles & air defence JV partner"},
              {"id": "ELBIT", "label": "Elbit Systems (BF Elbit Advanced Systems)",
               "rel": "jv", "ptype": "Artillery & mortar systems JV"},
              {"id": "DRDO", "label": "DRDO (ARDE) \u2014 ATAGS program",
               "rel": "tech", "ptype": "ATAGS co-development partner"}]
    comps = [
        {"cid": "kalyani-strategic-systems", "name": "Kalyani Strategic Systems",
         "dir": "client", "partners": []},
        {"cid": "mahindra", "name": "Mahindra Defence", "dir": "rival", "partners": [
            {"label": "Rafael Advanced Defense Systems"},
            {"label": "Anduril Industries"},
            {"label": "Bharat Electronics Ltd. (BEL)"}]},
        {"cid": "adani", "name": "Adani Defence", "dir": "rival", "partners": [
            {"label": "Elbit Systems"},
            {"label": "Kalyani Strategic Systems"}]},
    ]
    _, st = mark(comps, roster)
    mah = {p["label"]: p for p in comps[1]["partners"]}
    ada = {p["label"]: p for p in comps[2]["partners"]}

    # THE HEADLINE OF THE WHOLE TAB: KSSL's own JV partner also arms a rival.
    assert mah["Rafael Advanced Defense Systems"].get("shared"), \
        "Rafael is on KSSL's roster AND is Mahindra's partner -- that is the red line"
    assert mah["Rafael Advanced Defense Systems"]["koel"]["rel"] == "jv", \
        "the overlap carries the roster's own relationship, not a generic one"
    assert ada["Elbit Systems"].get("shared"), "Elbit: same shape, different rival"

    # ...and a partner KSSL has no connection to stays unshared. A rule that marks
    # everything is as useless as one that marks nothing.
    assert not mah["Anduril Industries"].get("shared")
    assert not mah["Bharat Electronics Ltd. (BEL)"].get("shared")

    # a rival partnering with the client directly is the shortest red line there is
    assert ada["Kalyani Strategic Systems"].get("clientTie"), \
        "a rival whose partner IS the client must be flagged"

    # EVERY identified tie carries cid, shared or not. The tab uses its presence to
    # tell "checked, no overlap" from "never checked" -- without it the green badge
    # is a guess. This is what 0-of-42-ties-have-cid meant on staging.
    for c in comps[1:]:
        for pt in c["partners"]:
            assert pt.get("cid"), "an identified tie must be keyed even when unshared"
    assert st["shared"] == 2 and st["client"] == 1, st

    # THE REGRESSION GUARD: this is exactly what the broken query produced.
    comps2 = [dict(c, partners=[dict(p) for p in c["partners"]]) for c in comps]
    for c in comps2:
        for pt in c["partners"]:
            pt.pop("shared", None); pt.pop("koel", None); pt.pop("clientTie", None)
    _, st2 = mark(comps2, roster=[])
    assert st2["shared"] == 0, "no roster -> nothing can be shared (the bug)"
    assert st2["keyed"] == st["keyed"], \
        "...but ties are still keyed, so an empty roster is distinguishable from an " \
        "unrun pass -- the badge needs to tell those apart"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
