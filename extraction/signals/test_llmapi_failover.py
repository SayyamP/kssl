"""The fallback is for a farm that is DOWN, not one that hiccuped.

    python3 test_llmapi_failover.py        (no network, no model)

llmapi.py carries its own self-check with fake transports; CI runs every test_*.py in
this directory and nothing invoked that file, so the failover logic -- which decides
WHICH MODEL writes the serving tables -- was the one piece of this pipeline with no
gate on it at all.

WHY IT MATTERS. `ask()` used to try the farm ONCE and, on any exception, black the farm
out for FARM_COOLDOWN_S (60s). The LiteLLM gateway 502s under load and recovers in
seconds, so a single transient error handed the next minute of serving-table writes to
qwen2.5:7b-instruct on a CPU box -- while the very next log line said FARM RECOVERED.
Production's enrich log on 2026-09-06 is pairs of DOWN/RECOVERED seconds apart.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    r = subprocess.run([sys.executable, os.path.join(HERE, "llmapi.py")],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        print(out)
        print("FAIL llmapi self-check exited %d" % r.returncode)
        sys.exit(1)
    # The alerts are the operator's only view of which model answered, so assert the
    # wording as well as the exit code: a silent failover is the failure mode here.
    for want in ("FARM DOWN after 3 attempt(s)", "FARM CONFIG ERROR",
                 "NOT the serving model", "FARM RECOVERED"):
        if want not in out:
            print(out)
            print("FAIL the self-check no longer reports %r" % want)
            sys.exit(1)
    print("ok - a hiccup is retried on the farm; only a real outage reaches the "
          "fallback, and it says so")


if __name__ == "__main__":
    main()
