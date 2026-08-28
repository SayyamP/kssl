"""Real patent records for the Patents tab, from Google Patents.

    python fetch_patents.py --dry
    python fetch_patents.py --apply
    python fetch_patents.py --demo

Why this exists: the archived Patents data cannot be revived. 22 of its 26 rows
carry INVENTED identifiers -- "IN-2024-EST01 (est)", "IN-EST14 (est)" -- sourced
from business-news and company marketing pages rather than a patent office.
A fabricated patent number rendered as a patent record is exactly the thing this
project refuses to publish, so those rows stay archived and the tab is filled
from a real registry instead.

Two gates, both necessary:

  * DEFENCE RELEVANCE. Bharat Forge is a diversified forging company; its
    highest-ranked patent is a "Fluid end" for oil-and-gas pumps. Querying by
    assignee alone would fill a defence tab with drilling equipment.
  * IDENTIFIER SHAPE. Only a well-formed publication number is stored, so
    nothing that is not a real record can reach the table by accident.
"""
import os
import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KSSL-corpus/1.0"}
API = "https://patents.google.com/xhr/query?url="
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A well-formed publication number: country code + digits + optional kind code.
PUBNO = re.compile(r"^(US|EP|WO|IN|CN|JP|KR|DE|FR|GB|IL|TR|RU|SE|IT|ES)\d{6,}[A-Z]?\d?$")

# Defence relevance, mapped to the client's own categories. A patent must hit one.
AREAS = {
    "Artillery": ["howitzer", "artillery", "gun barrel", "recoil", "muzzle", "ordnance",
                  "breech", "gun mount", "elevating mass", "cannon"],
    "Ammunition": ["ammunition", "projectile", "cartridge", "propellant", "warhead",
                   "fuze", "fuse assembly", "shell", "explosive", "detonat"],
    "Protected & Armoured Vehicles": ["armour", "armor", "ballistic protection",
                                      "mine blast", "hull", "turret", "armoured vehicle"],
    "UAVs & Drones": ["unmanned aerial", "uav", "drone", "rotor craft", "vtol",
                      "loitering munition", "quadcopter"],
    "Precision Components & Forgings": ["forging", "forged", "crankshaft", "front axle",
                                        "die forging", "microalloyed", "billet"],
    "Missiles & Air Defence": ["missile", "guidance system", "seeker", "air defence",
                               "air defense", "interceptor"],
    "Marine / Naval": ["naval gun", "submarine", "torpedo", "hull form", "warship"],
}
# Words that mean the patent is NOT defence even when it hits an area cue.
NOT_DEFENCE = ["oil and gas", "fluid end", "frac", "wellbore", "drilling", "downhole",
               "wind turbine", "passenger car", "automotive brake", "agricultur",
               "medical", "surgical", "cosmetic", "food"]

# Topic queries: assignee-only search misses relevant IP held by firms we do not
# list, and it is the topic that decides whether a patent matters to KSSL.
TOPICS = [
    "howitzer", "artillery barrel", "gun recoil mechanism", "artillery projectile",
    "propellant charge", "loitering munition", "counter drone", "armour plate vehicle",
    "mine blast protection hull", "gun barrel forging", "unmanned ground vehicle",
]

ASSIGNEES = [
    "Bharat Forge", "Kalyani Strategic Systems", "Kalyani Group",
    "Tata Advanced Systems", "Larsen & Toubro", "Bharat Electronics",
    "Hindustan Aeronautics", "Munitions India", "Solar Industries",
    "ideaForge", "Zen Technologies", "Adani Defence",
]


def query(q, timeout=30, tries=4):
    # "&" in a query makes the endpoint answer 500, and it answers 503 when asked
    # too quickly -- neither is a permanent failure, so both are handled rather
    # than silently costing us an assignee.
    q = q.replace("&", "and")
    url = API + urllib.parse.quote("q=" + q, safe="")
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503):
                raise
            time.sleep(3.0 * (attempt + 1))
    else:
        raise last
    out = []
    for cl in (d.get("results") or {}).get("cluster") or []:
        for item in cl.get("result") or []:
            p = item.get("patent") or {}
            if p:
                out.append(p)
    return out


def classify(title, abstract):
    """-> area name, or None when nothing defence-relevant is claimed."""
    hay = ("%s %s" % (title or "", abstract or "")).lower()
    if any(w in hay for w in NOT_DEFENCE):
        return None
    for area, cues in AREAS.items():
        if any(c in hay for c in cues):
            return area
    return None


def country_of(no):
    m = re.match(r"^([A-Z]{2})", no or "")
    return m.group(1) if m else None


def collect(limit_per=20, verbose=True):
    seen, rows, skipped = set(), [], {"irrelevant": 0, "badno": 0, "dup": 0}
    for who in ASSIGNEES + ['topic:%s' % t for t in TOPICS]:
        topic = who.startswith("topic:")
        term = who[6:] if topic else who
        try:
            got = query(term if topic else ('"%s"' % term))
        except (urllib.error.URLError, OSError, ValueError) as e:
            print("  %-34s QUERY FAILED %s" % (term[:34], type(e).__name__), flush=True)
            continue
        kept = 0
        for p in got[:limit_per]:
            no = (p.get("publication_number") or "").strip()
            if not PUBNO.match(no):
                skipped["badno"] += 1
                continue
            if no in seen:
                skipped["dup"] += 1
                continue
            area = classify(p.get("title"), p.get("snippet"))
            if not area:
                skipped["irrelevant"] += 1
                continue
            seen.add(no)
            rows.append({
                "no": no, "title": (p.get("title") or "").strip(),
                "assignee": (p.get("assignee") or who).strip(),
                "status": "granted" if p.get("grant_date") else "filed",
                "filed": p.get("filing_date") or None,
                "granted": p.get("grant_date") or None,
                "country": country_of(no), "abstract": (p.get("snippet") or "").strip(),
                "area": area, "queried_as": term,
                "url": "https://patents.google.com/patent/%s/en" % no,
            })
            kept += 1
        if verbose:
            print("  %-34s %3d result(s) -> %2d defence-relevant"
                  % (term[:34], len(got), kept), flush=True)
        time.sleep(2.5)          # a courtesy delay; this is somebody else's server
    return rows, skipped


# `ord` is the primary key and the archived rows own 1..26, so pipeline rows start
# above them. Deleting only origin='pipeline' leaves those keys occupied, and an
# insert at ord=1 collides -- the same id-space separation the matchups needed.
PATENT_ORD0 = 1000


def apply_rows(rows):
    # LAST GATE, and it lives here on purpose. The collect-time assignee check was
    # bypassed by the merge that protects against a failed run clobbering a good
    # file: it restored 79 previously-harvested rows whose owner was unknown, and
    # they were written. A row with no named owner cannot answer the only question
    # this tab exists to answer -- which rival is building IP in our space -- so it
    # is refused at the point of writing, whatever route it took to get here.
    bad = [r for r in rows if not r.get("assignee")
           or r["assignee"].strip().lower() in ("", "not stated", "unknown")]
    if bad:
        print("refusing %d row(s) with no named assignee" % len(bad))
    rows = [r for r in rows if r not in bad]
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("delete from serving.patent where origin='pipeline'")
    gone = cur.rowcount
    by_assignee = {}
    for i, r in enumerate(sorted(rows, key=lambda x: (x["assignee"], x["no"]))):
        ao = by_assignee.setdefault(r["assignee"], len(by_assignee) + 1)
        cur.execute("""insert into serving.patent
            (ord, assignee_ord, no, title, assignee, status, filed, granted, country,
             abstract, area, url, origin)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')""",
            (PATENT_ORD0 + i, ao, r["no"], r["title"], r["assignee"], r["status"], r["filed"],
             r["granted"], r["country"], r["abstract"], r["area"], r["url"]))
    con.commit()
    con.close()
    return len(rows), gone


def main(apply=False, limit_per=20):
    rows, skipped = collect(limit_per)
    print("\n%d defence-relevant patent(s); skipped %d irrelevant, %d malformed number, "
          "%d duplicate" % (len(rows), skipped["irrelevant"], skipped["badno"],
                            skipped["dup"]))
    areas = {}
    for r in rows:
        areas[r["area"]] = areas.get(r["area"], 0) + 1
    for a, n in sorted(areas.items(), key=lambda x: -x[1]):
        print("   %-34s %d" % (a, n))
    print("\nsample:")
    for r in rows[:8]:
        print("   %-16s %-46s %s" % (r["no"], r["title"][:46], r["assignee"][:24]))
    # NEVER let a failed or partial run destroy a good one. Every assignee query
    # 503'd once Google's bot block kicked in, and the unconditional write replaced
    # 9 real records with an empty list -- a full harvest clobbered by a subset,
    # which is a fault this project has already paid for once.
    out = HERE / "fetch_patents.json"
    prev = []
    if out.exists():
        try:
            prev = json.loads(io.open(out, encoding="utf-8").read())
        except ValueError:
            prev = []
    if len(rows) < len(prev):
        print("REFUSING to overwrite %s: this run found %d row(s), the file holds %d. "
              "Merging instead." % (out.name, len(rows), len(prev)))
        by_no = {r["no"]: r for r in prev}
        by_no.update({r["no"]: r for r in rows})
        rows = sorted(by_no.values(), key=lambda r: (r["assignee"], r["no"]))
    io.open(out, "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))
    if apply and rows:
        n, gone = apply_rows(rows)
        print("\napplied %d row(s), replaced %d" % (n, gone))
    else:
        print("\n(dry run -- nothing written)")
    return rows


def _demo():
    assert PUBNO.match("US11433493B2") and PUBNO.match("EP3386853A1")
    assert PUBNO.match("WO2009047795A2")
    # the archive's invented identifiers must be unrepresentable here
    assert not PUBNO.match("IN-2024-EST01")
    assert not PUBNO.match("IN-EST14") and not PUBNO.match("")
    # relevance: a forging patent for oil-and-gas is NOT a defence patent
    assert classify("Fluid end and method of manufacturing it",
                    "conventional fluid end manufacturing for frac pumps") is None
    assert classify("Gun barrel with improved recoil", "an artillery ordnance") == "Artillery"
    assert classify("Front axle beam forging", "a die forging method") \
        == "Precision Components & Forgings"
    assert classify("A better teacup", "porcelain") is None
    assert country_of("US11433493B2") == "US" and country_of("") is None
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-per", type=int, default=20)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply, a.limit_per)
