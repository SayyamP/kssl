"""The COMPETITORS' product portfolios, from the audited 50-company workbook.

    python competitor_portfolio.py --xlsx <workbook>  # re-parse -> portfolio/competitor_portfolio.json
    python competitor_portfolio.py --demo     # hermetic asserts, no DB, no network
    python competitor_portfolio.py --report   # what survives the gate, by company
    python competitor_portfolio.py --dry      # what --apply would write
    python competitor_portfolio.py --apply    # serving.competitor_product + profile columns

The workbook is parsed by --xlsx, run locally, and the RESULT is committed as
portfolio/competitor_portfolio.json. Everything else -- demo, report, the tests,
the writer -- reads that JSON. Same arrangement as client_portfolio.py, and for
the same reason: openpyxl is not in extraction/requirements.txt, so a module
that reached for the spreadsheet at run time would fail in CI and on the box.

THE MIRROR OF client_portfolio.py
---------------------------------
client_portfolio.py exists because the corpus held no source for KSSL's own
specifications, so 160 served matchups carried a competitor value and a blank
where KSSL's should be. This file is the same problem on the other side: the
competitor value itself has never had a catalogue behind it. It came from the
archive, where a value never had to name its source.

Both sides now come from a workbook, through the same gate, and every value
carries the URL that states it.

WHERE THE DATA COMES FROM
-------------------------
portfolio/Defence_Competitors_50_2026-09-05.xlsx -- 50 companies, 1,083 product
rows, 1,183 source URLs. Audited before it arrived; audited again here. The
audit that matters to this module found three things it has to defend against:

  1. 134 Nammo rows carry, verbatim, a sentence describing POONGSAN's portfolio.
     On 117 of them it is the entire specification cell. Poongsan's own 37 rows
     do not contain it, which is how we know it is a paste and not a template.
  2. 8 Leonardo rows are IDV products sourced only to idvgroup.com, and IDV is
     also one of the 50 -- the same vehicle counted twice under two makers.
  3. 17 rows rest solely on a document-upload host, 16 of them Munitions India.

THE GATE IS engine/source_tiers.publishable -- NOT A NEW ONE
------------------------------------------------------------
The rule was already written and already tested: a value may be shown when its
own maker or a government publisher states it, or when two independent domains
do. This module adds no second opinion about trust. What it does add is the
`product_maker` argument, which is the part that matters for competitors:
Rheinmetall's site is an official source about a Rheinmetall gun and a NEWS
mention about a KNDS one. Without passing the maker, every rival's marketing
would rank as official for everyone's products.

WHAT IS REFUSED, AND COUNTED
----------------------------
Every refusal lands in REFUSALS by reason, and --report prints it. If that
number is ever zero, the checks are not running.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from engine import source_tiers as st                            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKBOOK = HERE / "portfolio" / "Defence_Competitors_50_2026-09-05.xlsx"
OUT_JSON = HERE / "portfolio" / "competitor_portfolio.json"
DSN = os.environ.get("KSSL_DSN", "")

REFUSALS: collections.Counter = collections.Counter()

# The workbook's Country / Region column is already one country per company, with
# four exceptions it writes as a pair or a bloc. Mapped explicitly rather than by
# splitting on a separator: "UK/US" is a dual-listed company, not two rows, and a
# split would put BAE Systems under two origins and double every count that uses
# this column.
ORIGIN = {
    "UK/US": "UK",        # BAE Systems plc is UK-incorporated; BAE Systems Inc is its US arm
    "Europe": "France",   # MBDA is registered at Le Plessis-Robinson
    "Turkey": "Turkiye",
    "Türkiye": "Turkiye",
}

# The Poongsan sentence, matched as a literal. A looser pattern would also strike
# the rows where Poongsan is legitimately named in its own products.
CONTAMINANT = ("Poongsan portfolio includes fuzes, primers and propellants; "
               "dedicated component production lines.")

# Products carried under two makers because one is the other's supplier or owner.
# The row is kept under the maker whose site sources it and dropped from the
# other -- not merged, because a merge would hide which company we can cite.
DOUBLE_COUNTED = {
    ("Leonardo", "Centauro II"), ("Leonardo", "MUV"), ("Leonardo", "VBA"),
    ("Leonardo", "SUPERAV Amphibious / VBA"), ("Leonardo", "SUPERAV Land"),
    ("Leonardo", "VBM Freccia AIFV/ATGM"), ("Leonardo", "Ariete C2"),
    ("Leonardo", "LMV2"),
}

# The workbook's Category column against the dashboard's catKey vocabulary. Two
# ID spaces, mapped explicitly and never joined on a display label -- this
# project has already lost a layer to exactly that join.
CAT_KEY = {
    "Artillery":          "art",
    "Ammunition":         "amm",
    "Small Arms":         "sa",
    "Protected Vehicles": "pav",
    "Marine/Naval":       "nav",
    "UAVs/Drones":        "uav",
    "Missiles":           "mad",
}

# A bullet is a specification only when it states a measurable value. A cell that
# says the figure is not published is an honest answer and is not a spec.
UNIT = (r"mm|cm|km/h|km|kg|g|t|tonnes?|tons?|rds/min|rounds?/min|rpm|m/s|kW|hp|"
        r"kt|kts|nm|min|hours?|h|%|mrad|MOA|cal|calibre|litres?|l|deg|°|m")
HAS_VALUE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%s)\b" % UNIT, re.I)
BULLET = re.compile(r"[••]\s*")
_YEAR = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")

# The Chairman column holds a governance SENTENCE on 13 of the 50 rows. Accurate,
# and not a name. Returning it would let a downstream join read prose as a person.
_NOT_A_NAME = re.compile(
    r"^(privately held|board-led|division managed|multinational|supervisory board|"
    r"jv governance|idv became|board/governance|private group|founder\s*:|"
    r".*leadership under)", re.I)
# ...and a cell that names someone only to say they no longer hold the office is
# prose too. Paramount's reads "Founder: Ivor Ichikowitz; stepped back from
# executive-chairman/daily-management role" -- a real person, and the sentence
# says he is NOT the chairman.
_VACATED = re.compile(r"\b(stepped back|stepped down|no longer|former|until \d{4}|"
                      r"pending|not publicly (disclosed|identified))\b", re.I)


def slug(name):
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "unnamed"


def urls_in(cell):
    return [u.strip().strip(",;") for u in re.split(r"[;\s]+", cell or "")
            if u.startswith("http")]


def specs_of(cell):
    """[{k, v, note}] -- the same bullet shape client_portfolio writes."""
    out = []
    for b in BULLET.split(cell or ""):
        b = " ".join(b.split()).strip().rstrip(";")
        if not b or not HAS_VALUE.search(b):
            continue
        if ":" in b:
            k, v = b.split(":", 1)
            k, v = k.strip(), v.strip()
            if not k or len(k) > 44:
                k, v = "", b
        else:
            k, v = "", b
        out.append({"k": k, "v": v or b, "note": b})
    return out


def load():
    """The committed result. -> (products, profiles, refusals)

    This is what every runtime path reads. Nothing here opens the spreadsheet."""
    if not OUT_JSON.exists():
        raise SystemExit("no %s -- run --xlsx to build it" % OUT_JSON.name)
    d = json.load(io.open(OUT_JSON, encoding="utf-8"))
    return d["products"], d["companies"], collections.Counter(d.get("refused", {}))


def parse_workbook(path=WORKBOOK):
    """The spreadsheet. Needs openpyxl; run locally and commit the JSON."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)

    def sheet(name):
        ws = wb[name]
        hdr = [c.value for c in ws[1]]
        rows = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            if all(c is None for c in r):
                continue
            rows.append({k: ("" if v is None else str(v))
                         for k, v in zip(hdr, r) if k})
        return rows

    return sheet("COMPANY DIRECTORY"), sheet("PRODUCT MASTER")


def build(directory, products):
    """The gate. -> (products, profiles). Pure: no DB, no network, no spreadsheet."""
    REFUSALS.clear()

    out = []
    for r in products:
        comp, name = r["Company"], r["Product"]
        if (comp, name) in DOUBLE_COUNTED:
            REFUSALS["counted under its actual maker instead"] += 1
            continue

        spec_cell = r.get("Technical Specifications", "")
        if CONTAMINANT in spec_cell:
            REFUSALS["another company's text removed from the spec cell"] += 1
            spec_cell = spec_cell.replace(CONTAMINANT, "").strip(" \n\t••")

        srcs = urls_in(r.get("Sources", ""))
        ok, why, tier_used, n_indep = st.publishable(srcs, product_maker=comp)
        if not ok:
            REFUSALS[why] += 1
            continue

        specs = specs_of(spec_cell)
        if not specs:
            REFUSALS["no measurable value in the spec cell"] += 1
            continue

        cat = r.get("Category", "")
        out.append({
            "product_id": "cp_%s_%s" % (slug(comp), slug(name)),
            "company": comp,
            "name": name,
            "file_category": cat,
            "catKey": CAT_KEY.get(cat),
            "specs": specs,
            "features": specs_of(r.get("Features & Capabilities", "")),
            "sources": srcs,
            "evidence": {"why": why, "tier": tier_used, "independent": n_indep},
        })

    profiles = []
    for d in directory:
        srcs = urls_in(d.get("Sources", ""))
        ok, why, tier_used, n = st.publishable(srcs, product_maker=d["Company"])
        chair = (d.get("Chairman") or "").strip()
        yr = _YEAR.search(d.get("Starting Year / Corporate Origin", "") or "")
        profiles.append({
            "company": d["Company"],
            "slug": slug(d["Company"]),
            "country": d.get("Country / Region", ""),
            "hq": d.get("Headquarters", ""),
            "starting_year": int(yr.group(1)) if yr else None,
            "company_size": d.get("Company Size", ""),
            "sales": d.get("Annual Revenue / Sales", ""),
            "financial_year": d.get("Financial Year", ""),
            "sector": d.get("Industry / Sector", ""),
            "ceo": d.get("CEO / Managing Director", ""),
            "chairman": None if (not chair or _NOT_A_NAME.match(chair)
                                 or _VACATED.search(chair)) else chair,
            "global_locations": d.get("Global Locations", ""),
            "facilities": d.get("Facilities & Operating Units", ""),
            "sources": srcs,
            "publishable": ok,
            "evidence": why,
        })
    return out, profiles


# ── writing ──────────────────────────────────────────────────────────────────
def write_json(products, profiles, path=OUT_JSON, write=True):
    doc = {
        "built_from": WORKBOOK.name,
        "gate": "engine/source_tiers.publishable, product_maker aware",
        "products": products,
        "companies": profiles,
        "refused": dict(REFUSALS),
    }
    if write:
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return doc


def norm(name):
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = re.sub(r"\b(ltd|limited|inc|corp|corporation|plc|gmbh|sa|ag|as|oyj|"
               r"private|pvt|group|holdings|company|co)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


ALIAS = {"larsentoubro": "lt", "nexterknds": "knds", "kndsfrance": "knds",
         "rtxraytheon": "rtx", "idviveco": "iveco",
         "israelaerospaceindustries": "iai", "hutastalowawola": "hsw",
         "thyssenkruppmarine": "tkms", "rafaeladvanceddefense": "rafael"}


def key_of(name):
    k = norm(name)
    return ALIAS.get(k, k)


def plan_profiles(cur, profiles):
    """Which competitor rows have a blank this workbook can fill. Reads only."""
    cur.execute("SELECT comp_id, name, hq, starting_year, company_size, sales, country "
                "FROM serving.competitors WHERE origin='pipeline'")
    have = {key_of(n): (cid, n, hq, yr, sz, sl, ctry)
            for cid, n, hq, yr, sz, sl, ctry in cur.fetchall()}
    updates, unmatched = [], []
    for p in profiles:
        row = have.get(key_of(p["company"]))
        if not row:
            unmatched.append(p["company"])
            continue
        cid, _n, hq, yr, sz, sl, ctry = row
        set_ = {}
        # Origin country. The Competitor filter reads this column alone, so it must
        # be the country the company IS FROM -- never the geo footprint, which is
        # where it does business. The workbook states it per company; a region
        # ("Telangana") is never promoted to a country.
        if not (ctry or "").strip() and p.get("country"):
            set_["country"] = ORIGIN.get(p["country"].strip(), p["country"].strip())
        # FILL a blank, never replace. A value already there came from the corpus
        # with its own provenance; swapping it silently would leave nobody able to
        # say which number is on screen.
        if not (hq or "").strip() and p["hq"]:
            set_["hq"] = p["hq"]
        if yr is None and p["starting_year"]:
            set_["starting_year"] = p["starting_year"]
        if not (sz or "").strip() and p["company_size"]:
            set_["company_size"] = p["company_size"]
        if not sl and p["sales"] and p["publishable"]:
            set_["sales"] = {"text": p["sales"], "fy": p["financial_year"],
                             "srcs": p["sources"][:3]}
        if p["global_locations"]:
            set_["global_locations"] = [x.strip() for x in
                                        re.split(r"[;\n]|,(?=\s*[A-Z])",
                                                 p["global_locations"]) if x.strip()]
        if set_:
            updates.append((cid, p["company"], set_))
    return updates, unmatched, have


def apply_profiles(cur, updates):
    for cid, _name, set_ in updates:
        cols, vals = [], []
        for k, v in set_.items():
            if k in ("sales", "global_locations"):
                cols.append('"%s" = %%s::jsonb' % k)
                vals.append(json.dumps(v, ensure_ascii=False))
            else:
                cols.append('"%s" = %%s' % k)
                vals.append(v)
        vals.append(cid)
        cur.execute("UPDATE serving.competitors SET %s, updated_at=now() "
                    "WHERE comp_id=%%s AND origin='pipeline'" % ", ".join(cols), vals)
    return len(updates)


def apply_products(cur, products):
    cur.execute("DELETE FROM serving.competitor_product WHERE origin='pipeline'")
    for i, p in enumerate(products):
        cur.execute(
            """INSERT INTO serving.competitor_product
               (product_id, ord, company, name, file_category, cat, "catKey",
                specs, features, sources, evidence, origin)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,'pipeline')""",
            (p["product_id"], i, p["company"], p["name"], p["file_category"],
             p["file_category"], p["catKey"],
             json.dumps(p["specs"], ensure_ascii=False),
             json.dumps(p["features"], ensure_ascii=False),
             json.dumps(p["sources"], ensure_ascii=False),
             json.dumps(p["evidence"], ensure_ascii=False)))
    return len(products)


# ── reporting ────────────────────────────────────────────────────────────────
def report():
    products, profiles, refused = load()
    by = collections.Counter(p["company"] for p in products)
    specs = collections.Counter()
    for p in products:
        specs[p["company"]] += len(p["specs"])
    print("COMPETITOR PORTFOLIO, through engine/source_tiers.publishable")
    print("  products admitted            : %d" % len(products))
    print("  specification values         : %d" % sum(specs.values()))
    print("  companies with any product   : %d of %d" % (len(by), len(profiles)))
    print("\n  refused:")
    for why, n in refused.most_common():
        print("    %5d  %s" % (n, why))
    print("\n%-36s %6s %6s  %s" % ("company", "prods", "specs", "evidence"))
    for comp, n in by.most_common():
        ev = collections.Counter(p["evidence"]["tier"] for p in products
                                 if p["company"] == comp)
        print("%-36s %6d %6d  %s" % (comp[:35], n, specs[comp], dict(ev)))
    nop = [p["company"] for p in profiles if p["company"] not in by]
    print("\ncompanies with NO publishable product (%d): %s" % (len(nop), ", ".join(nop)))


def demo():
    # The committed result, not the spreadsheet: openpyxl is not in
    # extraction/requirements.txt, so a demo that opened the workbook would fail
    # in CI while passing on the machine that wrote it.
    products, profiles, REFUSED = load()
    assert len(profiles) == 50, len(profiles)

    # 1. the maker is official about its OWN product and a news mention about a
    #    rival's. Without this, one company's marketing sets another's numbers.
    ok, why, t, _n = st.publishable(["https://www.rheinmetall.com/x"],
                                    product_maker="Rheinmetall")
    assert ok and t == st.OFFICIAL, (ok, why, t)
    ok, why, t, _n = st.publishable(["https://www.rheinmetall.com/x"],
                                    product_maker="KNDS Germany")
    assert not ok, "a rival's site must not be official for our product: %s" % why

    # 2. a single uncorroborated non-official source is refused outright
    ok, why, _t, _n = st.publishable(["https://www.scribd.com/document/1/x"],
                                     product_maker="Munitions India Ltd (MIL)")
    assert not ok and "uncorroborated" in why, why

    # 3. no admitted product carries the Poongsan sentence, and the rows where it
    #    was the whole cell do not survive as specification-less products
    for p in products:
        blob = " ".join(s["note"] for s in p["specs"])
        assert "Poongsan portfolio includes fuzes" not in blob, p["name"]
    assert REFUSED["another company's text removed from the spec cell"] == 134, REFUSED

    # 4. the Leonardo/IDV vehicles are counted once, under IDV
    leo = {p["name"] for p in products if p["company"] == "Leonardo"}
    idv = {p["name"] for p in products if p["company"] == "IDV (Iveco Defence)"}
    assert "Centauro II" not in leo, "Centauro II still counted under Leonardo too"
    assert not (leo & idv), sorted(leo & idv)

    # 5. every admitted product has a catKey the dashboard understands, a value
    #    and a source
    for p in products:
        assert p["catKey"] in ("art", "amm", "sa", "pav", "nav", "uav", "mad"), p
        assert p["specs"] and p["sources"], p["name"]
        assert p["evidence"]["tier"] in (st.OFFICIAL, st.REGISTRY, st.NEWS), p

    # 6. a cell that only says the figure is unpublished yields nothing
    assert specs_of("• Uncrewed air system in BAE portfolio\n"
                    "• detailed public numeric specifications not established.") == []
    got = specs_of("• Calibre: 155 mm\n• Max range: 40 km with ERFB-BB")
    assert [g["k"] for g in got] == ["Calibre", "Max range"], got

    # 7. a governance SENTENCE is never returned as a chairman. The narrower
    #    claim on purpose: this gate removes prose, it does not check that a
    #    named person actually holds the office. Oshkosh's cell names the PARENT
    #    company's President & CEO, which is a real person in the wrong column --
    #    a data defect for the corrections list, not something to null silently.
    by_name = {p["company"]: p for p in profiles}
    assert by_name["IDV (Iveco Defence)"]["chairman"] is None
    assert by_name["Paramount Group"]["chairman"] is None
    assert by_name["MBDA"]["chairman"] is None
    assert by_name["BAE Systems"]["chairman"].startswith("Cressida Hogg")
    for p in profiles:
        c = p["chairman"]
        assert c is None or not (_NOT_A_NAME.match(c) or _VACATED.search(c)), (
            p["company"], c)

    # 8. the match key must not collapse two companies into one
    keys = {}
    for p in profiles:
        k = key_of(p["company"])
        assert k not in keys, (k, keys[k], p["company"])
        keys[k] = p["company"]

    # 9. the refusal counter must actually be counting -- a zero here means the
    #    checks above are not running at all
    assert sum(REFUSED.values()) > 0, "nothing was refused; the gate is not running"

    print("ok - %d products admitted, %d specification values, %d refused, "
          "%d company profiles"
          % (len(products), sum(len(p["specs"]) for p in products),
             sum(REFUSED.values()), len(profiles)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--xlsx", nargs="?", const=str(WORKBOOK),
                    help="re-parse the workbook and write portfolio/competitor_portfolio.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.demo:
        return demo()
    if a.report:
        return report()

    if a.xlsx:
        directory, raw = parse_workbook(Path(a.xlsx))
        products, profiles = build(directory, raw)
        write_json(products, profiles)
        print("wrote %s: %d products from %d rows, %d companies, %d refused"
              % (OUT_JSON.name, len(products), len(raw), len(profiles),
                 sum(REFUSALS.values())))
        return
    if not (a.dry or a.apply):
        ap.error("choose --demo, --report, --xlsx, --dry or --apply")
    products, profiles, _refused = load()

    import psycopg2
    con = psycopg2.connect(DSN or "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
    cur = con.cursor()
    updates, unmatched, have = plan_profiles(cur, profiles)
    print("products publishable : %d" % len(products))
    print("competitor rows      : %d, matched %d, blanks to fill %d"
          % (len(have), len(profiles) - len(unmatched), len(updates)))
    print("in the workbook but not tracked (%d, NOT created): %s"
          % (len(unmatched), ", ".join(unmatched)))
    if a.apply:
        n1 = apply_products(cur, products)
        n2 = apply_profiles(cur, updates)
        con.commit()
        print("applied: %d products, %d profiles" % (n1, n2))
    else:
        print("--dry: nothing written")
    cur.close()
    con.close()


if __name__ == "__main__":
    main()
