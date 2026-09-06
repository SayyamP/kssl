#!/usr/bin/env bash
# THE HERMETIC GATE. Run from the repository root.
#
# One script, two callers: ci.yml gates a pull request with it, deploy.yml gates a direct
# push to main/staging/dev with it. It used to be two copies of the same commands, and the
# copies drifted -- deploy.yml's still ran the five checks that existed when it was
# written, so mark_shared, backfill_tie_status and translate.py gated a PR and did NOT
# gate a push to main, which is the route production actually takes. A comment in
# deploy.yml claimed "the same hermetic checks run here as in ci.yml" while three of them
# did not. Duplication that has to be kept in step by hand does not stay in step.
#
# Every command is hermetic: no database, no network, no GPU, no model call.
set -euo pipefail

pip install -r extraction/requirements.txt

# The presignal relevance gate (competitor roster, alias list, code stoplist).
python extraction/engine/presignal.py --demo
# The queue router.
C_DS_JSON=extraction/engine/ds.json \
C_TIERS_PATH=extraction/engine/source_tiers.py \
  python extraction/engine/route.py --demo
# The audit regressions.
(cd extraction && python test_fixes.py)
# The gap loop: which serving column is empty on which competitor, and which corpus
# documents answer it. Its judgement is one function -- does this document speak to
# THIS field for THIS company -- and getting it wrong either floods the queue or
# silently queues nothing, both of which look identical in a log line.
(cd extraction && python backfill_gaps.py --demo)

# The signals modules import each other by bare filename, so they run from their own
# directory. The test_*.py loop is deliberate: a new regression test is picked up by
# being written, without also having to remember to edit this file.
cd extraction/signals
# The card writer, and the enrichment step that decides who counts as a competitor.
python serving_fill.py --demo
python enrich_serving.py --demo
# The overlap join behind the red line -- "this rival's partner is also KSSL's". Its two
# queries filtered on origin='pipeline', which is right for a rival and wrong for the
# client: KSSL's own rows are reference data by design, so the roster came back empty and
# every partner on the tab rendered as an unqualified green "Direct Partner".
python mark_shared.py --demo
# Reads the status a tie states in its own words. The trap it guards is a founding year
# read as an end year -- "Historical JV (established 2007 as JML, now JCBL South)" is a
# going concern, and "ended 2007" would be a false claim published about a real company.
python backfill_tie_status.py --demo
# The translation layer: which strings are sent to the model, which answers are allowed to
# be stored, and that a failure returns the original rather than an invention. Its gate is
# measured, not asserted -- 0 of 600 real English lead-ins are refused, where is_english()
# refused 16.3% of them.
python translate.py
for t in test_*.py; do
  echo "== $t"
  python "$t"
done
