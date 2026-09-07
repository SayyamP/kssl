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

# EVERY HELPER RESOLVED ABSOLUTELY, AND CHECKED BEFORE ANY WORK.
# `cd extraction/signals` further down is NOT scoped to a subshell, so a path written
# relative to the repository root stops resolving halfway through this script. CI calls
# us as `bash deploy/selfcheck.sh`, so ${BASH_SOURCE[0]} is relative too: the health-gate
# test at the end resolved to a path that no longer existed and exited 127 -- AFTER eight
# minutes of passing tests -- which failed selfcheck, skipped the deploy job, and left
# production two commits behind while the run looked like an ordinary test failure.
# Resolving once, here, is what makes the tail of the script independent of the cd; the
# existence check turns a missing helper into a one-second error at the top rather than a
# 127 at the bottom.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for helper in "$SELF_DIR/test_healthgate.sh"; do
  [ -f "$helper" ] || { echo "selfcheck: helper not found: $helper" >&2; exit 1; }
done

pip install -r extraction/requirements.txt

# The presignal relevance gate (competitor roster, alias list, code stoplist).
python extraction/engine/presignal.py --demo
# Is a URL the company's OWN site, or a page that mentions it? The rule this replaced
# published four news publishers as competitors' official websites -- and put AM
# General's site on General Dynamics' profile.
python extraction/signals/company_sites.py --demo
# Both sides state a number, so compare them -- on the unit BOTH sides name. Refuses
# where a first-number parse would invert a verdict (one field, two quantities) or
# invent one (3 rounds/30 sec IS 6 rds/min).
python extraction/signals/spec_number.py
# The verified competitor workbook -> the Positioning panel. The matcher's traps are
# real data: CAESAR's U+00D7, and "Archer" against "Archerfish Mine Disposal System".
python extraction/signals/fill_matchup_rival_specs.py --demo
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

# The self-hosted deploy path's two invariants: no ssh on the local path, and no
# pull_request trigger anywhere a self-hosted runner can be reached. Neither is visible
# to actionlint, and both fail silently -- see deploy/RUNNERS.md.
# PyYAML is this check's dependency, not extraction's, so it is declared here rather
# than added to extraction/requirements.txt. It used to work by accident: GitHub's runner
# image ships PyYAML system-wide. Moving selfcheck into a fresh venv (deploy.yml) removed
# that accident and this import was the first thing to fall over -- which is the venv
# doing its job, one release earlier than it would have mattered.
python -c "import yaml" 2>/dev/null || pip install --quiet pyyaml
python deploy/test_runner_paths.py

# The frontend's Caddyfile is a printf inside frontend/Dockerfile, so it has no config
# file anyone would think to review and no syntax check of its own. Its cache rules
# decide whether a successful deploy is VISIBLE: index.html is the only unhashed file
# and it is the one that NAMES the bundles, so caching it pins viewers to the previous
# build while every other part of the deploy reports success.
echo "== deploy/test_frontend_cache.py"
python deploy/test_frontend_cache.py

# The signals modules import each other by bare filename, so they run from their own
# directory. The test_*.py loop is deliberate: a new regression test is picked up by
# being written, without also having to remember to edit this file.
cd extraction/signals
# The card writer, and the enrichment step that decides who counts as a competitor.
python serving_fill.py --demo
python enrich_serving.py --demo
# The panel's lead block, written from the article BODY rather than from the extracted
# propositions. Its checks are on the parsing and the refusals, which is where it can go
# wrong silently: a hard-wrapped paragraph split into three <p> fragments, the model's
# closing commentary served as if it were the article's, and a summary that came back in
# the source language being shown to a reader who cannot read it.
python summarize.py
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
# The event emitter: proves it records nothing and never raises without a DB.
python provenance.py
for t in test_*.py; do
  echo "== $t"
  python "$t"
done

# THE DEPLOY'S OWN HEALTH GATE. Stubbed docker, no containers, about a second -- and it
# is the only thing standing between a backend that cannot import and another 404. The
# gate it replaced was four lines inline in deploy.sh and had no way to be exercised
# short of shipping a broken backend, which is how it came to miss one.
echo "== deploy/test_healthgate.sh"
bash "$SELF_DIR/test_healthgate.sh"
