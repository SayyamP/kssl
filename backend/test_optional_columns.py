# -*- coding: utf-8 -*-
"""A backend ahead of its database must lose a field, not the whole dashboard.

`country` was added to COMP_FIELDS and to db/migrations in one commit. deploy.sh
does not run migrations -- sync_from_prod.sh is the only thing that does, and it
says so itself -- so the deploy put a backend that selects serving.competitors.country
in front of a database without that column. The competitors query is the FIRST in
_dataset, so UndefinedColumn returned 500 for GET /api/dataset and every panel on
every page went blank behind "Could not load the KSSL dataset - 500".

Run: python backend/test_optional_columns.py
"""
import os
import sys

os.environ.setdefault("KSSL_CORPUS_DSN", "postgresql://unused/unused")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402


class Cur:
    """Answers the information_schema query and nothing else."""

    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def execute(self, sql, params=None):
        assert "information_schema.columns" in sql, sql
        self.sql, self.params = sql, params

    def fetchall(self):
        return list(self.rows)


def snapshot():
    return {id(f): list(f) for _, f, _ in app._SERVED}


def restore(snap):
    for _, f, _ in app._SERVED:
        f[:] = snap[id(f)]


fails = []


def check(name, ok, detail=""):
    print("  %-64s %s%s" % (name, "PASS" if ok else "FAIL",
                            "  " + str(detail) if detail else ""))
    if not ok:
        fails.append(name)


snap = snapshot()

# --- 1. the exact staging outage -------------------------------------------
# every competitors column EXCEPT country, which is what the box actually had
cols = [("competitors", c) for c in app.COMP_FIELDS if c != "country"]
dropped = app._reconcile_optional(Cur(cols), schema="serving_live")
check("country is dropped when the migration has not run",
      dropped.get("competitors") == ["country"], dropped)
check("the SELECT no longer names it",
      '"country"' not in app._cols(app.COMP_FIELDS))
check("nothing else was dropped from competitors",
      set(snap[id(app.COMP_FIELDS)]) - set(app.COMP_FIELDS) == {"country"})
c = Cur(cols)
app._reconcile_optional(c, schema="serving_live")
check("it asks about the SERVED schema, not the raw one",
      c.params == ("serving_live",), c.params)
restore(snap)

# --- 2. the normal case ------------------------------------------------------
cols = [("competitors", c) for c in app.COMP_FIELDS]
dropped = app._reconcile_optional(Cur(cols), schema="serving_live")
check("a schema that has every column drops nothing", dropped == {}, dropped)
check("country still reaches the browser when it exists",
      "country" in app.COMP_FIELDS)
restore(snap)

# --- 3. a missing REQUIRED column is not silently hidden ---------------------
# `name` is not optional. A backend whose database has no competitors.name is not
# one migration behind, it is pointed at the wrong database -- and the query that
# fails will say which column and which relation. Swallowing it here would turn a
# deploy that is badly out of step into a dashboard quietly missing every name.
cols = [("competitors", c) for c in app.COMP_FIELDS if c != "name"]
dropped = app._reconcile_optional(Cur(cols), schema="serving_live")
check("a missing NON-optional column is left in, so the query raises",
      "name" in app.COMP_FIELDS and dropped == {}, dropped)
restore(snap)

# --- 4. an absent relation is left to the query that names it ----------------
dropped = app._reconcile_optional(Cur([]), schema="serving_live")
check("an empty schema drops nothing (the query reports the missing relation)",
      dropped == {})
check("every field list is intact after an empty schema",
      all(app_f == snap[id(app_f)] for _, app_f, _ in app._SERVED))
restore(snap)

# --- 5. the registry covers every list that has an OPT set -------------------
# The bug came back if a new *_OPT is added and left out of _SERVED, so this is
# checked here rather than trusted.
opts = {n[:-4] for n in dir(app) if n.endswith("_OPT")}
covered = set()
for _, fields, optional in app._SERVED:
    for n in dir(app):
        if n.endswith("_OPT") and getattr(app, n) is optional:
            covered.add(n[:-4])
check("every *_OPT set is in _SERVED", opts == covered, sorted(opts - covered))

# --- 6. the lists are mutated in place, so _emit cannot disagree -------------
before = id(app.COMP_FIELDS)
app._reconcile_optional(Cur([("competitors", c) for c in app.COMP_FIELDS
                             if c != "country"]), schema="serving_live")
check("_emit sees the same list object the SELECT was built from",
      id(app.COMP_FIELDS) == before)
row = {f: None for f in app.COMP_FIELDS}
row.update({"name": "Nexter", "sector": "Artillery"})
out = app._emit(row, app.COMP_FIELDS, app.COMP_OPT)
check("_emit over the pruned list does not raise and omits country",
      "country" not in out and out["name"] == "Nexter")
restore(snap)

print()
if fails:
    print("%d check(s) FAILED" % len(fails))
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("all checks passed")
