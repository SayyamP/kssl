#!/usr/bin/env python3
"""The two claims the self-hosted deploy path rests on, asserted against deploy.yml.

Neither can be caught by actionlint or by a YAML parse, and both are the kind of thing a
later edit breaks silently:

  1. NO STEP ON THE SELF-HOSTED PATH TOUCHES SSH. The whole point of a runner on the box
     is that GitHub never opens a connection into it. A copy-paste that leaves an `ssh`
     call -- or a VPS_HOST/VPS_SSH_KEY in a step's env -- puts the failure mode back
     without changing anything visible in the log until the day it fails.

  2. deploy.yml MUST NEVER TAKE A pull_request TRIGGER, and every ci.yml job must stay on
     ubuntu-latest. This is the entire security boundary: `push` to a protected branch
     needs write access, `pull_request` does not -- a stranger's fork can open one. A
     self-hosted runner on a pull_request-triggered workflow is root on production for
     any GitHub user.

Run: python3 deploy/test_runner_paths.py     (wired into deploy/selfcheck.sh)
"""
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
SELF, SSH = "runner.environment == 'self-hosted'", "runner.environment != 'self-hosted'"
VPS_SECRETS = {"SSH_KEY", "HOST", "USER", "PORT"}


def _code(body):
    """Shell comments are prose. The ssh path is discussed in the local path's comments
    on purpose -- they explain what it replaced -- so matching raw text reports a
    failure on every run."""
    return "\n".join(l for l in (body or "").splitlines() if not l.lstrip().startswith("#"))


def main():
    deploy = yaml.safe_load((HERE / "deploy.yml").read_text())
    ci = yaml.safe_load((HERE / "ci.yml").read_text())
    steps = deploy["jobs"]["deploy"]["steps"]
    local = [s for s in steps if s.get("if", "").strip() == SELF]
    over_ssh = [s for s in steps if s.get("if", "").strip() == SSH]
    fail = []

    assert local, "no self-hosted steps found -- has the deploy job been rewritten?"
    assert over_ssh, "the ssh path is gone; it is still the only path for dev"

    for s in local:
        hits = re.findall(r"(?<![\w-])(ssh|scp)\b", _code(s.get("run", "")))
        secs = VPS_SECRETS & set(s.get("env") or {})
        if hits:
            fail.append("self-hosted step %r invokes %s" % (s["name"], set(hits)))
        if secs:
            fail.append("self-hosted step %r is handed %s" % (s["name"], sorted(secs)))

    # yaml parses a bare `on:` key as the boolean True
    if "pull_request" in list(deploy[True]):
        fail.append("deploy.yml has a pull_request trigger; a fork could reach a runner")
    for name, job in ci["jobs"].items():
        if job["runs-on"] != "ubuntu-latest":
            fail.append("ci.yml job %r is on %r; ci.yml takes pull_request and must stay "
                        "on GitHub's disposable machines" % (name, job["runs-on"]))

    for f in fail:
        print("  !! " + f)
    if fail:
        return 1
    print("runner paths: %d local step(s) free of ssh, %d ssh step(s) kept for dev, "
          "deploy.yml push-only, all %d ci.yml jobs github-hosted -- ok"
          % (len(local), len(over_ssh), len(ci["jobs"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
