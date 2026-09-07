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

  3. NO DEPLOY JOB MAY PIN ubuntu-latest. Every job routes through the runner `resolve`
     picks, so that the workflow lands entirely on one environment's runner or entirely
     on GitHub's. A job left pinned would still be billed -- and while the account's
     spending limit is reached it would block the whole workflow, silently, from a line
     that looks like the old default.

  4. RESOLVE'S OWN MAPPING MUST MATCH THE ONE IT PUBLISHES. `resolve` cannot consume
     `needs.resolve.outputs.runner` -- it is the job that computes it -- so the branch
     -> runner mapping is written twice: once in its `runs-on`, once in the case
     statement that sets the output. Drift between them puts resolve on a GitHub runner
     while every downstream job waits on a self-hosted one, or the reverse.

  5. THE SELFCHECK JOB MUST BUILD A FRESH VENV. selfcheck.sh pip-installs, and a
     self-hosted runner's tool cache outlives the job: without a per-run venv a package
     deleted from requirements.txt stays importable and the gate passes anyway.

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

    # 3. no Deploy job pinned to GitHub's machines
    for name, job in deploy["jobs"].items():
        if "ubuntu-latest" in str(job["runs-on"]) and "fromJSON" not in str(job["runs-on"]):
            fail.append("deploy.yml job %r pins ubuntu-latest; it must route through the "
                        "runner resolve picks" % name)
        if name != "resolve" and "needs.resolve.outputs.runner" not in str(job["runs-on"]):
            fail.append("deploy.yml job %r does not follow resolve's runner choice" % name)

    # 3b. the ancestry guard, which is what stops a dispatched `sha` from deploying a
    # commit that was never merged to the branch it claims to be deploying. Verified
    # live on 2026-09-07 (a main-only sha dispatched at staging was refused), and
    # asserted here because it is one `if:` away from being silently skipped.
    anc = [st for st in deploy["jobs"]["resolve"]["steps"]
           if "ancestor" in (st.get("name") or "").lower()]
    if not anc:
        fail.append("resolve has no ancestry check; a dispatched sha could deploy a "
                    "commit that is not on the branch")
    else:
        body = anc[0].get("run") or ""
        if "merge-base --is-ancestor" not in body:
            fail.append("the ancestry step no longer uses `git merge-base --is-ancestor`")
        if "workflow_dispatch" not in (anc[0].get("if") or ""):
            fail.append("the ancestry step is not gated on workflow_dispatch")

    # 4. resolve's inline mapping vs the mapping it publishes
    # The two are written in different languages -- a workflow expression
    # (`vars.SELF_HOSTED_PROD == 'true'`) and a shell test (`= "true"`) -- so the pattern
    # matches on the variable name and the label array near it, not on the comparison.
    def pairs(text):
        return set(re.findall(
            r'SELF_HOSTED_(PROD|STAGING)[\s\S]{0,240}?\["self-hosted","(\w+)"\]', text))

    inline = pairs(str(deploy["jobs"]["resolve"]["runs-on"]))
    pick = next(s for s in deploy["jobs"]["resolve"]["steps"] if s.get("id") == "pick")
    published = pairs(pick["run"])
    if inline != published:
        fail.append("resolve's runs-on mapping %s disagrees with the runner= it publishes %s"
                    % (sorted(inline), sorted(published)))
    elif len(inline) != 2:
        fail.append("expected a prod and a staging mapping in resolve, found %s" % sorted(inline))

    # 5. the selfcheck job must isolate its pip installs from a reused tool cache
    # Both halves, not the word "venv": creating the venv without putting it on $PATH
    # leaves selfcheck.sh installing into the tool cache exactly as before, and a check
    # that matched the word alone passed that broken arrangement.
    sc = "\n".join((s.get("run") or "") for s in deploy["jobs"]["selfcheck"]["steps"])
    if not re.search(r"python\s+-m\s+venv", sc):
        fail.append("the selfcheck job never runs `python -m venv`; on a persistent "
                    "runner a stale package lets a missing requirement pass the gate")
    elif "GITHUB_PATH" not in sc:
        fail.append("the selfcheck job builds a venv but never puts it on $GITHUB_PATH, "
                    "so selfcheck.sh still pip-installs into the persistent tool cache")

    for f in fail:
        print("  !! " + f)
    if fail:
        return 1
    print("runner paths: %d local step(s) free of ssh, %d ssh step(s) kept for dev, "
          "deploy.yml push-only, all %d deploy job(s) follow resolve, resolve's two "
          "mappings agree, selfcheck venv present, all %d ci.yml jobs github-hosted -- ok"
          % (len(local), len(over_ssh), len(deploy["jobs"]), len(ci["jobs"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
