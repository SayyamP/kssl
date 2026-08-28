"""Run the whole chain once, timed, so every stage has a number.

    python pipeline/run_measured.py --limit 20
    python pipeline/run_measured.py --limit 20 --skip pull

Corpus -> select -> Layer A -> Layer B -> load -> cards -> enrich. Each step is
a separate process, exactly as it is run by hand; this only sequences them and
gives the run one id so the whole pass can be pulled back out of
metrics.stage_run together.

WHY A SEPARATE SCRIPT AND NOT A MAKEFILE
----------------------------------------
Because the interesting output is not "did it work" but "where did the time go",
and that needs one run_id shared across seven processes. KSSL_RUN_ID is set here
and inherited, so afterwards:

    SELECT stage, ms, n_items FROM metrics.stage_run
     WHERE run_id = '<the id this prints>' ORDER BY id;

A step that fails stops the chain. Each step feeds the next, so continuing would
turn one loud failure into several quiet ones -- and would silently produce a
timing for a stage that had nothing to do.
"""
import argparse
import io
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent


def load_env():
    """Read ../.env literally. A shell sourcing this file either fails on the
    metacharacters in a password or expands part of one."""
    p = HERE.parent / ".env"
    if not p.exists():
        return
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# name -> (script, args builder). Order is the pipeline order.
STEPS = [
    ("pull",    lambda a: ["pull_corpus.py", "--since", a.since,
                           "--limit", str(a.limit)]),
    ("extract", lambda a: ["run_extraction.py", "--limit", str(a.limit),
                           "--workers", str(a.workers)]),
    ("load",    lambda a: ["load_extracted.py"]),
    ("cards",   lambda a: ["serving_fill.py", "--limit", str(a.limit)]),
    ("verify",  lambda a: ["verify_cards.py"]),
    ("enrich",  lambda a: ["enrich_serving.py"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--since", default=None)
    ap.add_argument("--skip", default="", help="comma-separated step names")
    ap.add_argument("--only", default="", help="comma-separated step names")
    a = ap.parse_args()

    if not a.since:
        from datetime import datetime, timedelta, timezone
        a.since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    run_id = os.environ.get("KSSL_RUN_ID") or uuid.uuid4().hex[:12]
    os.environ["KSSL_RUN_ID"] = run_id
    os.environ.setdefault("KSSL_METRICS_DSN", os.environ.get("KSSL_DSN", ""))
    if not os.environ.get("KSSL_HOST_ROLE"):
        print("WARNING: KSSL_HOST_ROLE is not set -- these rows will be labelled")
        print("         'unknown'. Set it to workstation, datacentre or vps.")

    skip = {x.strip() for x in a.skip.split(",") if x.strip()}
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    print("run_id %s   host %s   limit %d   since %s"
          % (run_id, os.environ.get("KSSL_HOST_ROLE", "unknown"), a.limit, a.since))
    print("")

    results, t_all = [], time.time()
    for name, build in STEPS:
        if name in skip or (only and name not in only):
            print("-- %-8s skipped" % name)
            results.append((name, None, "skipped"))
            continue
        argv = [sys.executable] + [str(HERE / build(a)[0])] + build(a)[1:]
        print("== %s" % name, flush=True)
        t0 = time.time()
        r = subprocess.run(argv, cwd=str(HERE))
        dt = time.time() - t0
        ok = r.returncode == 0
        results.append((name, dt, "ok" if ok else "FAILED rc=%d" % r.returncode))
        print("   %s in %.1fs" % ("ok" if ok else "FAILED", dt), flush=True)
        if not ok:
            print("")
            print("chain stopped at %s -- each step feeds the next, so the "
                  "later timings would be meaningless" % name)
            break

    print("")
    print("=" * 52)
    print("%-10s %10s   %s" % ("step", "seconds", "outcome"))
    print("-" * 52)
    for name, dt, how in results:
        print("%-10s %10s   %s"
              % (name, ("%.1f" % dt) if dt is not None else "-", how))
    print("-" * 52)
    print("%-10s %10.1f" % ("total", time.time() - t_all))
    print("=" * 52)
    print("")
    print("per-stage detail:")
    print("  SELECT stage, ms, n_items, n_tokens FROM metrics.stage_run")
    print("   WHERE run_id = '%s' ORDER BY id;" % run_id)
    print("document journeys:")
    print("  SELECT * FROM metrics.doc_journey ORDER BY end_to_end_s DESC LIMIT 20;")
    return 0 if all(h in ("ok", "skipped") for _, _, h in results) else 1


if __name__ == "__main__":
    sys.exit(main())
