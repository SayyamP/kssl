"""The news refill must run in the pass that empties it, right after the delete.

    python test_news_step_order.py          (no database needed)

THE BUG THIS PINS. serving.competitor_news.comp_id is
`REFERENCES serving.competitors(comp_id) ON DELETE CASCADE`, and step_companies opens
by deleting every origin='pipeline' competitor -- so the news table is cascaded away at
the START of every enrich pass.

The refill existed, but it was wired into extraction/entrypoint.sh AFTER the whole run.
A pass is ten steps and several hours (55 profile calls in step one alone), so the four
news panels on every competitor profile were empty for most of every two-hourly cycle.
Measured on production 2026-09-05: 0 rows for the entire time the pass was running, then
268 rows across 29 companies once it finished. The client asked "from competitor profile
where did news go?" while a pass was mid-flight, which is exactly the window.

So ORDER is the fix, and order is what this asserts:
  * the news step exists in STEPS at all -- deleting it silently restores the old bug;
  * it runs IMMEDIATELY after companies, not merely somewhere later. One step further
    down is another hour of empty panels;
  * companies still runs first, because the news step reads the competitors it writes.

Deliberately no database: this is a statement about the pass's shape, and it has to run
on a CI machine that has no Postgres. The refill's own behaviour is covered by
test_news_category.py and by fill_competitor_news.py --demo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import enrich_serving                                                 # noqa: E402

bad = 0


def check(name, ok):
    global bad
    if not ok:
        bad += 1
        print("  FAIL %s" % name)


names = [n for n, _ in enrich_serving.STEPS]

check("the news step is in STEPS", "news" in names)
check("companies is in STEPS", "companies" in names)

if "news" in names and "companies" in names:
    i_co = names.index("companies")
    i_nw = names.index("news")
    check("companies runs before news (news reads what it writes)", i_co < i_nw)
    check("news runs IMMEDIATELY after companies, got %s"
          % (" -> ".join(names[i_co:i_nw + 1]) if i_co < i_nw else names),
          i_nw == i_co + 1)

# every step is a callable taking the shared signature, or the driver's loop breaks
for n, fn in enrich_serving.STEPS:
    check("step %s is callable" % n, callable(fn))

# the step must not join the caller's transaction: a later step's rollback would take
# the news with it, which is the fault being fixed. It opens its own connection, so it
# ignores the cursor it is handed -- assert the seam exists rather than the mechanism.
check("step_news is defined", hasattr(enrich_serving, "step_news"))
if hasattr(enrich_serving, "step_news"):
    doc = enrich_serving.step_news.__doc__ or ""
    check("step_news documents WHY it is placed here",
          "CASCADE" in doc and "step_companies" in doc)

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - news refills immediately after the delete that empties it (%d steps: %s)"
      % (len(names), ", ".join(names)))
