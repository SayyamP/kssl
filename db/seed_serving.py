"""Seed serving.* from reference_dataset.json (origin='reference').

Idempotent: TRUNCATEs every serving table it owns, then inserts. UI-vocabulary
globals go verbatim into serving.ui_config; data-bearing globals are flattened
into their tables. compOrder is NOT seeded (the API derives it from
serving.competitors ordering); PATENTS rows are stored flat with the two
orderings needed to rebuild byArea and byAssignee exactly.

Usage:  python db/seed_serving.py
Env:    KSSL_DSN      (default: host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl)
        KSSL_DATASET  (default: ../reference_dataset.json next to this file)
"""

import json
import os
import sys

# UTF-8 safe printing on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import psycopg2
from psycopg2.extras import Json, execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DSN = "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl"
DSN = os.environ.get("KSSL_DSN", DEFAULT_DSN)
DATASET = os.environ.get("KSSL_DATASET", os.path.join(HERE, "..", "reference_dataset.json"))

ORIGIN = "reference"

# Globals that live in real tables; everything else goes to ui_config verbatim.
TABLE_BACKED = {
    "competitors", "compOrder",
    "competitiveCards", "marketCards", "techCards",
    "details", "matchups", "tenders", "PATENTS",
    "geoData", "geoComps", "innovations", "KSSL_PARTNERS",
    "sourceRegistry", "companySources",
}

# All serving tables this seeder owns (truncated before insert).
OWNED_TABLES = [
    "serving.ui_config", "serving.competitors", "serving.signal_card",
    "serving.signal_detail", "serving.matchup", "serving.tender",
    "serving.patent", "serving.geo_presence", "serving.geo_comp",
    "serving.innovation", "serving.partner", "serving.source_registry",
    "serving.company_source",
]


def jz(v):
    """jsonb-wrap dicts/lists; pass scalars/None through."""
    return Json(v) if isinstance(v, (dict, list)) else v


def jall(v):
    """jsonb-wrap any non-null value (for mixed-type jsonb columns)."""
    return Json(v) if v is not None else None


def insert_rows(cur, table, columns, rows):
    if not rows:
        return
    cols = ", ".join('"%s"' % c for c in columns)
    execute_values(cur, 'INSERT INTO %s (%s) VALUES %%s' % (table, cols), rows)


def main():
    with open(DATASET, encoding="utf-8") as f:
        data = json.load(f)

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("TRUNCATE " + ", ".join(OWNED_TABLES) + " CASCADE")

    # ---- ui_config: every global without a table, plus PATENTS aux pieces ----
    ui_rows = [(k, Json(v)) for k, v in data.items() if k not in TABLE_BACKED]
    patents = data["PATENTS"]
    ui_rows.append(("PATENTS.techAreas", Json(patents.get("techAreas", []))))
    ui_rows.append(("PATENTS._meta", Json(patents.get("_meta", {}))))
    insert_rows(cur, "serving.ui_config", ["key", "value"], ui_rows)

    # ---- competitors (dict keyed by comp id; key order = compOrder) ----
    comp_fields = ["name", "dir", "sector", "hq", "threat", "assess", "updates",
                   "center", "partners", "site", "srcs", "products", "threatNote"]
    # "updates" is mixed-type (string OR empty list) -> jsonb column, always wrap.
    rows = [
        tuple([cid, i]
              + [jall(c.get(f)) if f == "updates" else jz(c.get(f))
                 for f in comp_fields]
              + [ORIGIN])
        for i, (cid, c) in enumerate(data["competitors"].items())
    ]
    insert_rows(cur, "serving.competitors",
                ["comp_id", "ord"] + comp_fields + ["origin"], rows)

    # ---- signal cards: three lanes, one table ----
    card_fields = ["id", "dir", "rank", "title", "meta", "company", "lens",
                   "sowhat", "sec", "url", "ago", "tags"]
    rows = []
    for lane, gname in (("competitive", "competitiveCards"),
                        ("market", "marketCards"),
                        ("tech", "techCards")):
        for i, c in enumerate(data[gname]):
            rows.append(tuple([lane, i] + [jz(c.get(f)) for f in card_fields] + [ORIGIN]))
    insert_rows(cur, "serving.signal_card",
                ["lane", "ord"] + card_fields + ["origin"], rows)

    # ---- details (dict keyed by card id) ----
    det_fields = ["rank", "dir", "title", "facts", "what", "why", "lens",
                  "actions", "url", "suggest", "kind", "match", "pursue"]
    rows = [
        tuple([did, i] + [jz(d.get(f)) for f in det_fields] + [ORIGIN])
        for i, (did, d) in enumerate(data["details"].items())
    ]
    insert_rows(cur, "serving.signal_detail",
                ["id", "ord"] + det_fields + ["origin"], rows)

    # ---- matchups (dict keyed by numeric-string id) ----
    m_fields = ["cat", "anchor", "global", "dir", "country", "comp", "compBy",
                "bf", "bfBy", "ks_thin", "reason", "edge", "specs", "advComp",
                "advBf", "det", "verdictH", "verdict", "catKey", "srcs", "gen"]
    rows = [
        tuple([int(mid)] + [jz(m.get(f)) for f in m_fields] + [ORIGIN])
        for mid, m in data["matchups"].items()
    ]
    insert_rows(cur, "serving.matchup",
                ["matchup_id"] + m_fields + ["origin"], rows)

    # ---- tenders (list) ----
    t_fields = ["id", "title", "issuer", "country", "cat", "value", "qty",
                "deadline", "dl", "reqNote", "req", "matches", "lean", "leanTxt",
                "status", "url", "urlKind", "srcs", "stage"]
    rows = [
        tuple([i] + [jz(t.get(f)) for f in t_fields] + [ORIGIN])
        for i, t in enumerate(data["tenders"])
    ]
    insert_rows(cur, "serving.tender", ["ord"] + t_fields + ["origin"], rows)

    # ---- PATENTS: flat rows; ord = position flattening byArea, assignee_ord =
    #      position flattening byAssignee (the same 26 rows, different order) ----
    p_fields = ["no", "title", "assignee", "status", "filed", "granted",
                "country", "ipc", "abstract", "area", "threat", "relev", "url", "p"]
    by_area_flat = [p for lst in patents.get("byArea", {}).values() for p in lst]
    by_asg_flat = [p for lst in patents.get("byAssignee", {}).values() for p in lst]
    asg_ord = {p["no"]: i for i, p in enumerate(by_asg_flat)}
    if len(asg_ord) != len(by_asg_flat):
        raise SystemExit("patent 'no' values are not unique; cannot map assignee order")
    rows = [
        tuple([i, asg_ord.get(p["no"], i)] + [jz(p.get(f)) for f in p_fields] + [ORIGIN])
        for i, p in enumerate(by_area_flat)
    ]
    insert_rows(cur, "serving.patent",
                ["ord", "assignee_ord"] + p_fields + ["origin"], rows)

    # ---- geoData (dict comp -> dict country -> list of entries) ----
    g_fields = ["name", "c", "val", "since", "qty", "stage", "note", "src", "srcnote"]
    rows = []
    for ci, (cid, countries) in enumerate(data["geoData"].items()):
        for ki, (country, entries) in enumerate(countries.items()):
            for i, e in enumerate(entries):
                rows.append(tuple([cid, ci, country, ki, i]
                                  + [jz(e.get(f)) for f in g_fields] + [ORIGIN]))
    insert_rows(cur, "serving.geo_presence",
                ["comp_id", "comp_ord", "country", "country_ord", "ord"]
                + g_fields + ["origin"], rows)

    # ---- geoComps (list) ----
    gc_fields = ["id", "name", "dir", "hq", "isBf"]
    rows = [tuple([i] + [jz(g.get(f)) for f in gc_fields] + [ORIGIN])
            for i, g in enumerate(data["geoComps"])]
    insert_rows(cur, "serving.geo_comp", ["ord"] + gc_fields + ["origin"], rows)

    # ---- innovations (dict area -> list) ----
    in_fields = ["t", "mat", "gap", "driver", "horizon", "body", "impact",
                 "whatsNew", "compNote", "action", "sources", "url"]
    rows = []
    for ai, (area, items) in enumerate(data["innovations"].items()):
        for i, it in enumerate(items):
            rows.append(tuple([area, ai, i]
                              + [jz(it.get(f)) for f in in_fields] + [ORIGIN]))
    insert_rows(cur, "serving.innovation",
                ["area", "area_ord", "ord"] + in_fields + ["origin"], rows)

    # ---- KSSL_PARTNERS (list) ----
    pa_fields = ["id", "label", "kind", "rel", "sig", "ptype", "note", "date",
                 "country", "deal", "insight", "mean"]
    rows = [tuple([i] + [jz(p.get(f)) for f in pa_fields] + [ORIGIN])
            for i, p in enumerate(data["KSSL_PARTNERS"])]
    insert_rows(cur, "serving.partner", ["ord"] + pa_fields + ["origin"], rows)

    # ---- sourceRegistry (list) ----
    sr_fields = ["company", "label", "url", "kind"]
    rows = [tuple([i] + [jz(s.get(f)) for f in sr_fields] + [ORIGIN])
            for i, s in enumerate(data["sourceRegistry"])]
    insert_rows(cur, "serving.source_registry", ["ord"] + sr_fields + ["origin"], rows)

    # ---- companySources (dict company -> list of urls) ----
    rows = []
    for ci, (company, urls) in enumerate(data["companySources"].items()):
        for i, url in enumerate(urls):
            rows.append((company, ci, i, url, ORIGIN))
    insert_rows(cur, "serving.company_source",
                ["company", "comp_ord", "ord", "url", "origin"], rows)

    conn.commit()

    # Report.
    for t in OWNED_TABLES:
        cur.execute("SELECT count(*) FROM " + t)
        print("%-28s %5d rows" % (t, cur.fetchone()[0]))
    cur.close()
    conn.close()
    print("seeded from", os.path.abspath(DATASET))


if __name__ == "__main__":
    main()
