# -*- coding: utf-8 -*-
"""A column the SELECT does not name can never reach the browser.

MEASURED ON PRODUCTION 2026-09-06: serving.patent has published, grant_no, pub_kind
and doc_id -- db/migrations/2026-09-06_patent_grant_status.sql added them to the table
AND re-created serving_live.patent to expose them -- and all four read 0/1183. The
harvester's write_db() probes for them and says so in its log when they are missing,
so the write side was wired. The read side was not: backend PATENT_FIELDS is what
_cols() turns into "SELECT ...", and it named none of the four. The frontend card
already branched on r.published; that branch could never fire, because the API had no
way to send the key.

The lesson this pins is the seam, not the four names: a migration that adds a column
to a served table and a backend that does not select it look identical from the
dashboard -- an empty tile either way -- and only one of them is a data problem. So
this test does not carry a hand-written list of columns. It READS db/migrations/*.sql,
takes every column those files add to serving.patent, and requires the backend to
select each one. Add a column to that table tomorrow without wiring the read side and
this goes red on its own.

Run: python backend/test_patent_fields.py
"""
import io
import os
import re
import sys

os.environ.setdefault("KSSL_CORPUS_DSN", "postgresql://unused/unused")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import app  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print("  %-66s %s%s" % (name, "PASS" if ok else "FAIL",
                            "  " + str(detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


# --- what the migrations added to serving.patent ----------------------------------
ADD_RX = re.compile(
    r"ALTER\s+TABLE\s+serving\.patent\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'"?([a-z_]+)"?', re.I)
mig_dir = os.path.join(ROOT, "db", "migrations")
added = {}
for fn in sorted(os.listdir(mig_dir)):
    if not fn.endswith(".sql"):
        continue
    sql = io.open(os.path.join(mig_dir, fn), encoding="utf-8").read()
    for col in ADD_RX.findall(sql):
        added.setdefault(col, fn)

check("the migrations directory does add columns to serving.patent", bool(added),
      sorted(added))

# DELIBERATELY NOT SERVED, with the reason recorded here rather than inferred from a
# naming convention. A bookkeeping column the browser has no use for should not be
# selected -- serving.signal_detail.translated set that precedent and is likewise absent
# from its field list -- but "not served" has to be a decision somebody made, not the
# default. Anything NOT in this map must reach the frontend or this test goes red.
INTERNAL = {
    "title_en_v": "translation window bookkeeping: the prompt version the row's title "
                  "was last examined under. Operational, not a fact about the filing.",
}
for col in list(added):
    if col in INTERNAL:
        print("  %-66s (not served: %s)" % (col, INTERNAL[col][:40]))
        added.pop(col)

sel = app._cols(app.PATENT_FIELDS)
for col, fn in sorted(added.items()):
    check('%s (%s) is selected' % (col, fn),
          col in app.PATENT_FIELDS and ('"%s"' % col) in sel,
          "not in PATENT_FIELDS" if col not in app.PATENT_FIELDS else "not in SELECT")
    # A column that a database one migration behind has not got must be droppable,
    # or the FIRST query in _dataset raises UndefinedColumn and the whole dashboard
    # goes blank -- which is exactly what `country` did on staging the same day.
    check("... and is optional, so a database without it still serves",
          col in app.PATENT_OPT)

# The four this was written for, named explicitly: the regex above could be broken in
# a way that finds nothing, and "found nothing, asserted nothing" would pass.
for col in ("published", "grant_no", "pub_kind", "doc_id"):
    check("%s reaches the frontend" % col, col in app.PATENT_FIELDS)

# --- _emit must be able to omit them, not send null -------------------------------
# "not measured" and "measured as empty" are different findings and the card renders
# them differently. An optional field that is NULL is dropped from the payload.
row = {f: None for f in app.PATENT_FIELDS}
row.update({"no": "US10254091", "title": "T", "assignee": "A", "status": "granted",
            "area": "X", "grant_no": "10254091"})
out = app._emit(row, app.PATENT_FIELDS, app.PATENT_OPT)
check("a measured grant_no is sent", out.get("grant_no") == "10254091", out.get("grant_no"))
check("an unmeasured pub_kind is ABSENT, not null", "pub_kind" not in out)
check("an unmeasured published is ABSENT, not null", "published" not in out)
check("a non-optional null is still sent (absence there is a real answer)",
      "filed" in out and out["filed"] is None)

# --- the pruning path keeps SELECT and _emit in step ------------------------------
# _reconcile_optional mutates the list in place; if it were rebound, _cols() would have
# been built from one list and _emit from another.


class Cur(object):
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        assert "information_schema.columns" in sql, sql

    def fetchall(self):
        return list(self.rows)


snap = list(app.PATENT_FIELDS)
have = [("patent", c) for c in app.PATENT_FIELDS if c != "pub_kind"]
dropped = app._reconcile_optional(Cur(have), schema="serving_live")
check("a database without pub_kind drops just that field",
      dropped.get("patent") == ["pub_kind"], dropped)
check("... and the SELECT no longer names it",
      '"pub_kind"' not in app._cols(app.PATENT_FIELDS))
check("... and everything else survives",
      set(snap) - set(app.PATENT_FIELDS) == {"pub_kind"})
app.PATENT_FIELDS[:] = snap

print()
if fails:
    print("%d check(s) FAILED" % len(fails))
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("all checks passed")
