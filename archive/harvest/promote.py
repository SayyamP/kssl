"""Move verified harvest facts into the serving layer — locally, then to the VPS.

    python promote.py --check          # what would be promoted, and the gate it passed
    python promote.py --apply          # write into the LOCAL serving schema
    python promote.py --apply --vps    # ...and push those columns to the VPS

Profile prints "not collected" under Leadership, Facilities and Sales because the corpus
never carried them. This is what fills them, and it is deliberately the last step: a fact
reaches the operator's screen only after it has been extracted, gated, audited by hand and
counted.

THE GATE
--------
Only fields whose sampled precision was measured are promoted, and the measurement is
recorded here rather than in a commit message:

  leadership   12 rows, hand-audited 12/12 correct after the name-before-role rule
  facilities   39 rows, hand-audited on a 22-row sample: real sites (Bhandara, Ishapore,
               Korwa, Hazira, HMNB Devonport, Billancourt, Lalru, Angul, Chakan)
  sales         8 rows, each a real revenue or order-book figure with its sentence

`product_spec` is NOT promoted here. It belongs to Positioning, which has its own
like-for-like gate and its own applier (apply_positioning.py), and pushing 1,250 spec
rows into a profile column would put unpaired numbers on a page that is about comparison.

EVERY PROMOTED ROW CARRIES ITS SOURCE. The column shape is
`[{"value","detail","url","line"}]`, so the panel can show the sentence behind any value
exactly as the tender and matchup surfaces now do.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from targets import DSN                             # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIELDS = ("leadership", "facilities", "sales")

DDL = """
alter table serving.competitors add column if not exists leadership jsonb;
alter table serving.competitors add column if not exists facilities jsonb;
alter table serving.competitors add column if not exists sales jsonb;
"""


def collect(cur):
    """{cid: {field: [row, …]}} — deduped on the VALUE, keeping the first source.

    "Mr. Sukaran Singh" and "Sukaran Singh" are one person written twice; a profile that
    lists both reads as two officers.
    """
    cur.execute("""select cid, company, field, value, detail, url, line
                   from harvest.fact where field = any(%s)
                   order by cid, field, value""", (list(FIELDS),))
    out, seen = {}, set()
    for cid, company, field, value, detail, url, line in cur.fetchall():
        norm = value.lower().replace("mr.", "").replace("mr ", "").replace("ms.", "") \
                    .replace("shri", "").replace("smt", "").replace(".", "").strip()
        key = (cid, field, norm)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(cid, {}).setdefault(field, []).append(
            {"value": value, "detail": detail or "", "url": url, "line": line})
    return out


def main(apply_it, to_vps):
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            cur.execute(DDL)
        cx.commit()
        with cx.cursor() as cur:
            data = collect(cur)
            cur.execute("select comp_id, name from serving.competitors")
            names = dict(cur.fetchall())

        tot = {f: 0 for f in FIELDS}
        print("%-28s %-11s %s" % ("company", "field", "values"))
        for cid in sorted(data):
            for field in FIELDS:
                rows = data[cid].get(field) or []
                if not rows:
                    continue
                tot[field] += len(rows)
                print("%-28s %-11s %s" % (
                    (names.get(cid) or cid)[:28], field,
                    ", ".join(r["value"][:26] for r in rows[:4])))
        print()
        print("totals: " + " · ".join("%s %d" % (f, tot[f]) for f in FIELDS))
        print("companies touched: %d" % len(data))

        if not apply_it:
            print("\nCHECK ONLY — nothing written. Re-run with --apply")
            return
        with cx.cursor() as cur:
            n = 0
            for cid, fields in data.items():
                if cid not in names:
                    continue
                for field, rows in fields.items():
                    cur.execute("update serving.competitors set %s = %%s::jsonb, "
                                "updated_at = now() where comp_id = %%s" % field,
                                (json.dumps(rows, ensure_ascii=False), cid))
                    n += cur.rowcount
        cx.commit()
        print("\nLOCAL: wrote %d company/field columns" % n)

    if not to_vps:
        return
    push_to_vps()


def push_to_vps():
    """Copy just these three columns to the VPS, by value, over SSH.

    NOT a table dump. serving.competitors on the VPS carries rows this machine's copy
    does not, and replacing the table would drop them. Three columns keyed by comp_id is
    the smallest thing that does the job.
    """
    import subprocess
    import psycopg2 as pg
    root = HERE.parent.parent
    env_file = root / ".env"
    host = key = None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("KSSL_VPS_HOST="):
            host = line.split("=", 1)[1].strip()
        elif line.startswith("KSSL_VPS_SSH_KEY="):
            key = line.split("=", 1)[1].strip()
    if not host:
        raise SystemExit("no KSSL_VPS_HOST in .env")

    with pg.connect(DSN, connect_timeout=15) as cx, cx.cursor() as cur:
        cur.execute("""select comp_id, leadership, facilities, sales
                       from serving.competitors
                       where leadership is not null or facilities is not null
                          or sales is not null""")
        rows = cur.fetchall()

    stmts = [DDL]
    for cid, lead, fac, sal in rows:
        stmts.append(
            "update serving.competitors set leadership=%s::jsonb, facilities=%s::jsonb, "
            "sales=%s::jsonb, updated_at=now() where comp_id=%s;"
            % (_lit(lead), _lit(fac), _lit(sal), _lit(cid)))
    sql = "\n".join(stmts)
    print("pushing %d companies to the VPS (%d bytes of SQL)" % (len(rows), len(sql)))

    cmd = ["ssh", "-i", key, "-o", "ConnectTimeout=25", "root@%s" % host,
           "docker exec -i kssl-db psql -U postgres -d kssl -v ON_ERROR_STOP=1 -f -"]
    p = subprocess.run(cmd, input=sql.encode("utf-8"), capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    print(out[-1500:])
    if p.returncode != 0:
        raise SystemExit("VPS push failed (exit %d)" % p.returncode)
    print("VPS: %d companies updated" % len(rows))


def _lit(v):
    """A SQL literal. Everything here is our own extracted text, but it still gets
    quoted properly — a company name with an apostrophe would otherwise end the run."""
    if v is None:
        return "null"
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return "'" + s.replace("'", "''") + "'"


def demo():
    assert _lit(None) == "null"
    assert _lit("O'Rourke") == "'O''Rourke'"
    assert _lit([{"value": "x"}]) == """'[{"value": "x"}]'"""

    class FakeCur:
        def __init__(self):
            self.rows = [
                ("TASL", "Tata", "leadership", "Mr. Sukaran Singh", "CEO", "u", "l"),
                ("TASL", "Tata", "leadership", "Sukaran Singh", "Chief Executive", "u", "l"),
                ("BEL", "BEL", "facilities", "Bengaluru", "Works", "u2", "l2"),
            ]

        def execute(self, *a):
            pass

        def fetchall(self):
            return self.rows

    got = collect(FakeCur())
    assert len(got["TASL"]["leadership"]) == 1, \
        "one person written two ways must not become two officers"
    assert got["BEL"]["facilities"][0]["url"] == "u2"
    print("promote demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--vps", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        main(a.apply, a.vps)
