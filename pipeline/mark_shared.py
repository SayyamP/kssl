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


def load(cur):
    cur.execute("""SELECT comp_id, name, dir, partners FROM serving.competitors
                    WHERE origin='pipeline' ORDER BY ord""")
    comps = []
    for cid, name, direction, partners in cur.fetchall():
        pl = partners if isinstance(partners, list) else json.loads(partners or "[]")
        comps.append({"cid": cid, "name": name, "dir": direction, "partners": pl})
    cur.execute("""SELECT id, label, rel, ptype FROM serving.partner
                    WHERE origin='pipeline' ORDER BY ord""")
    roster = [{"id": r[0], "label": r[1], "rel": r[2], "ptype": r[3]}
              for r in cur.fetchall()]
    return comps, roster


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    comps, roster = load(cur)
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

    stats = {"ties": 0, "keyed": 0, "shared": 0, "client": 0, "rival": 0}
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
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
