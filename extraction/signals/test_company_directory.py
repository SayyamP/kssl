# -*- coding: utf-8 -*-
"""Every company detail on a profile came from the workbook, verbatim.

    python test_company_directory.py                    # against the committed JSON
    KSSL_DIRECTORY_XLSX=<path> python test_company_directory.py   # ... and the workbook

The Profile panel showed a dash for STARTING YEAR, HEADQUARTERS, GLOBAL LOCATIONS,
COMPANY SIZE and ANNUAL REVENUE on all 43 competitors. The reader for those fields
already existed -- competitor_portfolio.py has parsed the COMPANY DIRECTORY sheet
since 2026-09-05 -- so the risk in filling them is not that nothing arrives. It is
that something arrives which the workbook does not say.

So the checks here are about provenance and shape, not about coverage:

  * every value is the workbook's own cell, character for character
  * a year is a year, not an address or a sentence about incorporation
  * a country is a country, never a region or a city
  * the revenue keeps the financial year it belongs to -- "₹2,530.93 crore" means
    nothing without FY2024-25 beside it
  * nothing is invented for a company the workbook does not carry

Where the workbook itself is available the JSON is compared back to it cell by cell.
Without it the committed JSON is still checked for shape, so this runs in CI.
"""
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JSON = HERE / "portfolio" / "competitor_portfolio.json"

bad = []


def ck(name, ok, detail=""):
    print("  %-64s %s%s" % (name, "ok  " if ok else "FAIL",
                            "  " + str(detail)[:90] if not ok and detail else ""))
    if not ok:
        bad.append(name)


doc = json.load(io.open(JSON, encoding="utf-8"))
companies = doc["companies"]
ck("the JSON names the workbook it was built from",
   bool(doc.get("built_from", "").endswith(".xlsx")), doc.get("built_from"))
ck("every company carries a slug and a name",
   all(c.get("company") and c.get("slug") for c in companies))

# A YEAR IS A YEAR. The workbook writes "14 Aug 2021 incorporation; business commenced
# 1 Oct 2021" and the panel prints whatever it is handed, so a sentence in this field
# would be rendered as the founding year.
years = [(c["company"], c.get("starting_year")) for c in companies
         if c.get("starting_year") is not None]
ck("a starting year is a four-digit year, not the sentence it came from",
   all(isinstance(y, int) and 1500 <= y <= 2100 for _n, y in years),
   [(n, y) for n, y in years if not (isinstance(y, int) and 1500 <= y <= 2100)][:3])

# A COUNTRY IS NOT A REGION. The Competitor filter reads this column alone, so
# "Telangana" here becomes an origin country on the screen.
REGIONS = {"telangana", "maharashtra", "uttar pradesh", "karnataka", "gujarat",
           "bavaria", "california", "texas", "europe", "asia", "middle east"}
# The JSON carries the workbook's cell; the WRITER maps it through ORIGIN before it
# reaches the column, which is where "Europe" becomes "France" (MBDA is registered at
# Le Plessis-Robinson). So the value that has to be checked is the mapped one.
import competitor_portfolio as _cp
mapped = [(c["company"], _cp.ORIGIN.get((c.get("country") or "").strip(),
                                        (c.get("country") or "").strip()))
          for c in companies]
ck("no origin country reaches the column as a region or a continent",
   not [n for n, v in mapped if v.lower() in REGIONS],
   [(n, v) for n, v in mapped if v.lower() in REGIONS])

# REVENUE WITHOUT ITS YEAR IS NOT A FIGURE.
with_sales = [c for c in companies if (c.get("sales") or "").strip()]
ck("every revenue figure carries the financial year it belongs to",
   all((c.get("financial_year") or "").strip() for c in with_sales),
   [c["company"] for c in with_sales if not (c.get("financial_year") or "").strip()][:5])
# The workbook says "Not publicly disclosed -- privately held" for the three private
# companies, and that sentence must not reach a row headed ANNUAL REVENUE. The writer
# drops it; what the JSON carries is the workbook's own words, so the check is that
# the WRITER refuses them.
undisclosed = [c["company"] for c in with_sales if not re.search(r"\d", c["sales"])]


class _Cur:
    """Just enough cursor for plan_profiles: one blank competitor row."""

    def __init__(self, name):
        self._rows = [("cid-1", name, None, None, None, None, None)]

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return self._rows


import competitor_portfolio as _cp2                      # noqa: E402
_priv = dict(company="Roshel", slug="roshel", country="Canada", hq="Toronto",
             starting_year=2016, company_size="500", sector="vehicles",
             sales="Not publicly disclosed - privately held",
             financial_year="2024 public reporting", global_locations="Canada",
             sources=["https://roshel.ca/"], publishable=True)
_up, _un, _have = _cp2.plan_profiles(_Cur("Roshel"), [_priv])
_set = _up[0][2] if _up else {}
ck("a revenue with no figure in it is never written",
   "sales" not in _set, sorted(_set))
ck("... and the rest of that company's details still are",
   {"hq", "starting_year", "company_size"} <= set(_set), sorted(_set))
_fig = dict(_priv, sales="EUR 5.8 billion revenue")
_up2, _, _ = _cp2.plan_profiles(_Cur("Roshel"), [_fig])
ck("... while a real figure is", "sales" in (_up2[0][2] if _up2 else {}))
print("       %d compan(ies) publish no revenue figure: %s"
      % (len(undisclosed), ", ".join(undisclosed)))

# NOTHING IS FILLED FROM AN EMPTY CELL. An empty string reaching the panel prints as
# a blank row rather than the honest dash, which is how "not collected" becomes
# "collected and empty".
for field in ("hq", "company_size", "global_locations", "sector"):
    blanks = [c["company"] for c in companies
              if field in c and isinstance(c[field], str) and not c[field].strip()]
    ck("no company carries an empty string for %s" % field, not blanks, blanks[:4])

# THE ROSTER MATCH IS UNAMBIGUOUS OR IT DOES NOT HAPPEN.
import competitor_portfolio as cp          # noqa: E402
import aliases as A                        # noqa: E402
keys = [cp.key_of(c["company"]) for c in companies]
ck("no two workbook rows fold onto one key", len(keys) == len(set(keys)),
   [k for k in keys if keys.count(k) > 1][:4])

# "RTX (Raytheon)" reaches both the RTX and the Raytheon roster rows; "KNDS Germany"
# and "Nexter (KNDS France)" both reach "KNDS". The fallback must refuse those.
# The real ambiguity, measured: "Nexter (KNDS France)" reaches both KNDS and Nexter,
# which are two separate roster rows. "RTX (Raytheon)" reaches only Raytheon -- "RTX"
# is three characters, below same_org's containment floor -- so it is not the example
# it looked like.
ck("an ambiguous workbook row reaches more than one roster name",
   len([n for n in ("KNDS", "Nexter")
        if A.same_org("Nexter (KNDS France)", n)]) == 2)
ck("... and an unambiguous one reaches exactly one",
   len([n for n in ("Hanwha Aerospace", "Rheinmetall", "Saab")
        if A.same_org("Hanwha (Aerospace/Group)", n)]) == 1)
ck("an HTML-escaped roster name still resolves",
   A.same_org("Larsen & Toubro (L&T)", "Larsen & Toubro"))

# ---- against the workbook itself, when it is to hand ----------------------
xlsx = os.environ.get("KSSL_DIRECTORY_XLSX")
if not xlsx:
    print("  --   set KSSL_DIRECTORY_XLSX to compare every cell back to the workbook")
else:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["COMPANY DIRECTORY"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h or "").strip() for h in rows[0]]
    sheet = {}
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        if d.get("Company"):
            sheet[str(d["Company"]).strip()] = d
    ck("the JSON carries every company the sheet does",
       {c["company"] for c in companies} == set(sheet),
       sorted(set(sheet) ^ {c["company"] for c in companies})[:4])

    FIELDS = [("hq", "Headquarters"), ("company_size", "Company Size"),
              ("sales", "Annual Revenue / Sales"),
              ("global_locations", "Global Locations"),
              ("financial_year", "Financial Year"), ("country", "Country / Region")]
    wrong = []
    for c in companies:
        src = sheet.get(c["company"]) or {}
        for key, col in FIELDS:
            got, want = c.get(key), src.get(col)
            if got in (None, "") and want in (None, ""):
                continue
            if str(got or "").strip() != str(want or "").strip():
                wrong.append((c["company"], key, str(got)[:40], str(want)[:40]))
    ck("every stored value is the workbook's cell, character for character",
       not wrong, wrong[:3])

    # And the year, which IS derived -- from a sentence, so it has to be checked.
    yr_wrong = []
    for c in companies:
        src = sheet.get(c["company"]) or {}
        cell = str(src.get("Starting Year / Corporate Origin") or "")
        if c.get("starting_year") is not None and str(c["starting_year"]) not in cell:
            yr_wrong.append((c["company"], c["starting_year"], cell[:60]))
    ck("every starting year appears in the sentence it was read from",
       not yr_wrong, yr_wrong[:3])

print("\n%s" % ("all checks passed" if not bad else "%d FAILED" % len(bad)))
sys.exit(1 if bad else 0)
