# -*- coding: utf-8 -*-
"""What is CPPP actually returning, and why does the mapper reject all of it?"""
import sys, io, collections
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import fetch_tenders as F

tally = collections.Counter()
rows = []
orig = F.cppp_row
def spy(r, label):
    out = orig(r, label)
    rows.append((r, label, out))
    return out
F.cppp_row = spy
try:
    F.fetch_cppp(60, tally, F.client_factory if hasattr(F, "client_factory") else None)
except Exception as e:
    print("fetch error:", type(e).__name__, str(e)[:200])
print("rows seen: %d" % len(rows))
for r, label, out in rows[:25]:
    title = r.get("title") if isinstance(r, dict) else str(r)[:90]
    print("  label=%-26s out=%s" % (str(label)[:26], str(out)[:40]))
    print("     raw:", str(r)[:190])
