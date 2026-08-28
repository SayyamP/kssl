"""Keep the dashboard fresh without anyone running anything.

    python pipeline/autopilot.py                    # run forever
    python pipeline/autopilot.py --once             # one cycle, then stop
    python pipeline/autopilot.py --batch 12 --every 3600

One cycle is the whole pipeline over whatever the crawler has fetched since the
last one:

    pull new dated defence documents  ->  Layer A/B  ->  load into the VPS
    ->  the VPS model writes cards    ->  the dashboard has them

WHAT MAKES THIS SAFE TO LEAVE RUNNING
-------------------------------------
* **It never runs two cycles at once.** A cycle can take an hour; a fixed timer
  would start the next one on top of it and both would fight for the same cores.
  The wait is measured from the END of a cycle.
* **Every stage is skipped if it has nothing to do.** pull_corpus is idempotent,
  run_extraction skips documents already stored, serving_fill skips documents
  that already have a card or a recorded refusal. An idle cycle costs one query.
* **A failing stage stops that cycle, not the loop.** The next cycle starts
  clean. A stage that feeds the next one is never skipped past.
* **It paces itself against the crawler.** Extraction and crawling compete for
  the same cores at the data centre (measured: 11.4 tok/s uncontended against
  1.6 contended), so the batch size is deliberately small and the gap between
  cycles deliberately long. Turning this up will slow the crawl down.

Everything it does is recorded in metrics.stage_run under one run_id per cycle,
so "how long did the pipeline take last night" is a query, not a guess.
"""
import argparse
import io
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pull_corpus import load_env                        # noqa: E402

load_env()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PY = sys.executable


def step(name, argv, timeout, tolerate_empty=True):
    """One stage as its own process, exactly as it is run by hand."""
    t0 = time.time()
    print("   -- %s" % name, flush=True)
    r = subprocess.run([PY] + argv, cwd=str(HERE), env=dict(os.environ),
                       capture_output=True, text=True, timeout=timeout)
    dt = time.time() - t0
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode != 0:
        print("      FAILED in %.0fs: %s" % (dt, (r.stderr or "").strip()[-300:]),
              flush=True)
        raise RuntimeError("%s failed" % name)
    print("      ok in %.0fs  %s" % (dt, tail[0][:120]), flush=True)
    return r.stdout


def cycle(a):
    run_id = uuid.uuid4().hex[:12]
    os.environ["KSSL_RUN_ID"] = run_id
    since = (datetime.now(timezone.utc) - timedelta(days=a.since_days)
             ).strftime("%Y-%m-%d")
    pub_since = (datetime.now(timezone.utc) - timedelta(days=a.published_days)
                 ).strftime("%Y-%m-%d")
    print("== cycle %s  (ingested >= %s, published >= %s, batch %d)"
          % (run_id, since, pub_since, a.batch), flush=True)

    # 1. what has the crawler brought in that we have not already taken?
    out = step("select new documents from the corpus",
               ["pull_corpus.py", "--since", since,
                "--published-since", pub_since, "--limit", str(a.batch)],
               timeout=1800)
    kept = 0
    for line in (out or "").splitlines():
        if line.strip().startswith("kept"):
            try:
                kept = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    if not kept:
        print("   nothing new passed the gate -- cycle ends here", flush=True)
        return run_id, 0

    # 2. extraction. --newest matters: without it the limit takes documents in
    #    id order, which is unrelated to age, and the recency gate downstream
    #    then refuses the lot.
    # The inner budgets: run_extraction gives Layer A max(3600, kept*900) and
    # then 600 + 3600 + 3600 to the three stages after it. An outer timeout
    # SHORTER than that sum does not protect anything -- it just kills the run
    # mid-Layer-B and reports "Layer A / Layer B failed", which reads as a stage
    # that went wrong rather than a clock that was set too tight. It also
    # orphans the engine's own children, and they keep holding the single model
    # slot. So the outer number is the sum of the inner ones plus slack.
    inner = max(3600, kept * 900) + 600 + 3600 + 3600
    step("Layer A / Layer B",
         ["run_extraction.py", "--limit", str(kept), "--workers",
          str(a.workers), "--newest"],
         timeout=inner + 600)

    # 3. into the VPS database
    step("load into the VPS database",
         ["load_extracted.py", "--sets", "kssl_demo"], timeout=3600)

    # 4. the VPS model turns documents into cards
    step("the model writes signal cards",
         ["serving_fill.py", "--limit", str(max(kept * 2, 10))], timeout=7200)

    # 5. entailment gate over what was just written
    step("verify the cards are supported",
         ["verify_cards.py"], timeout=3600)

    return run_id, kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=3600,
                    help="seconds to wait AFTER a cycle finishes (default 1h)")
    ap.add_argument("--batch", type=int, default=8,
                    help="documents per cycle. Small on purpose: extraction "
                         "competes with the crawler for the same cores.")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--since-days", type=int, default=2,
                    help="how far back to look for newly INGESTED documents")
    ap.add_argument("--published-days", type=int, default=45,
                    help="how old an article may be to still be worth a card")
    a = ap.parse_args()

    for var in ("KSSL_DSN", "KSSL_CORPUS_DSN"):
        if not os.environ.get(var):
            sys.exit("%s is not set -- see DEPLOY.md" % var)
    os.environ.setdefault("KSSL_METRICS_DSN", os.environ["KSSL_DSN"])
    if not os.environ.get("KSSL_HOST_ROLE"):
        sys.exit("set KSSL_HOST_ROLE so the timings say where they were measured")

    n = 0
    while True:
        n += 1
        t0 = time.time()
        try:
            run_id, kept = cycle(a)
            print("== cycle %s done: %d document(s) in %.0fs"
                  % (run_id, kept, time.time() - t0), flush=True)
        except Exception as exc:                        # noqa: BLE001
            # One bad cycle must not end the loop -- but it must be loud, and
            # the next cycle starts from scratch rather than half-done state.
            print("== cycle FAILED after %.0fs: %s"
                  % (time.time() - t0, str(exc)[:300]), flush=True)
        if a.once:
            return 0
        # measured from the END: a fixed timer would stack cycles on top of each
        # other and they would fight for the same cores
        print("   sleeping %ds\n" % a.every, flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
