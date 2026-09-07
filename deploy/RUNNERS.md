# Self-hosted deploy runners

`prod` and `staging` deploy **from the box they deploy to**. A runner installed on VPS-B
and VPS-A picks the deploy job up, and the deploy becomes a local operation: an rsync
between two directories on one disk, then `deploy/deploy.sh`. GitHub never opens a
connection into either machine.

`dev` has no runner and still deploys over ssh from a GitHub-hosted machine. Both paths
live in `deploy.yml` side by side, selected by `runner.environment`.

## Why

**Cost.** Actions minutes are billed on private repositories. Measured 2026-09-01..07:
366 runs, ~2,100 billable minutes in seven days — a 9,000 min/month pace against a
2,000 min Free allowance, 4.5× over. Self-hosted minutes are not billed at all.

**Inbound ssh was the single largest source of deploy failures.** Every staging deploy
from 2026-09-06 14:28 onward failed at the reachability probe
(`kex_exchange_identification: Connection reset by peer`), and a production deploy failed
the same morning with `Connection timed out` after two retries — the provider's edge does
not admit every GitHub runner IP every time. The runner dials **out** to GitHub on 443 and
long-polls, the same direction as `git push`, so none of that applies any more.

## Install

One command per box, run **as root on that box**. Mint the token at
`Settings → Actions → Runners → New self-hosted runner`; it is valid for one hour and one
registration, and it is not a PAT — it cannot read the repository.

```
RUNNER_TOKEN=AXXXX... deploy/install-runner.sh prod      # on VPS-B
RUNNER_TOKEN=AXXXX... deploy/install-runner.sh staging   # on VPS-A
```

The token is passed in the environment and never written to a file, so it cannot reach
git. The script refuses to register a machine whose `/opt/kssl/app/.KSSL_ENV` marker
disagrees with the label you asked for — see the guards below.

It installs under `/opt/actions-runner`, registers with labels `self-hosted,<env>`,
installs the systemd service, and adds a `Restart=always / RestartSec=10` drop-in.

Verify: the runner shows **Idle** at `…/settings/actions/runners`, and
`systemctl status actions.runner.*` is active on the box.

## Arming an environment (do this in order)

Merging the workflow change does **not** switch anything over, on purpose. A job asking
for `[self-hosted, prod]` when no such runner exists does not fail — it queues for up to
24 hours, looking exactly like a slow deploy. So each environment is armed by its own repo
variable, the same way `DEPLOY_ENABLED` gates production:

| variable | when to set it to `true` |
|---|---|
| `SELF_HOSTED_STAGING` | after the VPS-A runner reads **Idle** |
| `SELF_HOSTED_PROD` | after a staging deploy has actually completed on the runner |

Unset — or anything other than `true` — keeps the ssh path. That is also the kill switch:
a runner that is uninstalled, unreachable or mid-rebuild is one variable away from being
routed around, with no revert and no redeploy.

The order that keeps a working path at every step:

1. Install the runner on **VPS-A** and confirm it reads Idle.
2. Set `SELF_HOSTED_STAGING=true`.
3. Push to `staging`. Confirm the run's job header names the `kssl-staging` runner, that
   the log shows `Sync source + recreate frontend/backend (local)` and **not** the ssh
   step, and that the health gate passes.
4. Only then install the **VPS-B** runner and set `SELF_HOSTED_PROD=true`.

## Three guards against deploying to the wrong environment

They are layered on purpose; each catches what the one before it cannot.

| # | Where | What it checks |
|---|---|---|
| 1 | `install-runner.sh` | Refuses to register unless `/opt/kssl/app/.KSSL_ENV` equals the requested label. A mislabelled runner cannot be created in the first place. |
| 2 | `runs-on: [self-hosted, prod]` | GitHub only offers the job to a runner registered with **both** labels, so the staging runner is never eligible for a prod job. |
| 3 | "This runner must be the environment being deployed" | Reads the marker on the machine **before the rsync**. Catches a runner mislabelled by hand. |

`deploy.sh` checks the marker a fourth time, but by then the tree has already been
written — which is why guard 3 exists as a separate step rather than being left to it.

## Trust boundary — read this before adding a runner anywhere else

**Anyone who can push to `main`, `staging` or `dev` can execute code as root on that
box.** That is the whole security model, and it is acceptable here only because
`deploy.yml` fires exclusively on `push` to those branches and on `workflow_dispatch`,
both of which require write access to the repository.

- **`ci.yml` must stay on `ubuntu-latest`.** It has a `pull_request` trigger, which a
  stranger's fork can open. Moving it onto a self-hosted runner would hand any GitHub
  user root on production. Never add a `pull_request` trigger to `deploy.yml` either.
- **The runner runs as root, deliberately.** `deploy.sh` drives `docker compose`, which
  reads `/opt/kssl/app/.env` (`root:root 600`), and writes `/opt/kssl/app`. That is what
  the ssh path already did as `root@`, so this is parity rather than escalation. A
  non-root user in the `docker` group would not be an improvement: `docker run -v /:/host`
  is root with extra steps.
- **If this repository ever becomes public, remove the runners first.**

## Rolling back to ssh

Change the `runner=` line for that environment in `deploy.yml`'s `resolve` job back to
`["ubuntu-latest"]`. The ssh steps take over on the next run with nothing else changed;
they are still in the file and still the only path for `dev`. Nothing needs to be
uninstalled from the box.

## Removing a runner

```
cd /opt/actions-runner && ./svc.sh stop && ./svc.sh uninstall
./config.sh remove --token <a fresh removal token>
```

## Operational notes

- **A box that is down is a pipeline that is down** for its environment. It fails closed:
  the job queues rather than deploying something wrong.
- **Build cache grows.** `docker builder prune -f` monthly, or the disk creeps.
- **The workspace persists** at `/opt/actions-runner/_work`. `actions/checkout` cleans it
  each run (`git clean -ffdx`), so a stale tree is not a failure mode, but it does hold a
  full checkout permanently.
- **Two runners, one repository.** They are independent; neither can take the other's
  jobs, because the labels do not overlap.
