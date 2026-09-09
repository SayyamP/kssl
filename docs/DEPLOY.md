# Deploying (CI/CD) — a developer's guide

Push to a branch, and that branch's machine deploys itself. You never ssh anywhere and you
never run a deploy by hand.

Two of the three environments run a **GitHub Actions runner on the box they deploy to**, so
the deploy is a local operation — an rsync between two directories on one disk, then
`deploy/deploy.sh`. GitHub never opens a connection *into* those machines. `deploy/RUNNERS.md`
is the operator runbook for those runners, including two diagrams of the flow; this file is
what you need to ship a change.

## The model

| branch | environment | machine | deploys when |
|---|---|---|---|
| `main` | prod | VPS-B (`srv1928858`) | every push, **and** repo variable `DEPLOY_ENABLED == 'true'` |
| `staging` | staging | VPS-A (`srv1515678`) | every push |
| `dev` | dev | data centre | every push, still over ssh (no runner there) |

Promotion is `feature → dev → staging → main`, each step a pull request. **Never push to
`main` directly** — it deploys straight to production the moment it lands.

Only `frontend` and `backend` are recreated by a deploy. The database, LLM containers,
gliner, the tunnels and the long-running extraction farm are stable infrastructure and are
never touched — compose is only ever told those two service names.

Images are SHA-pinned and immutable, published to the repository's own GHCR namespace:

    ghcr.io/137mallory/kssl-deploy/{frontend,backend,extraction}:<git-sha>

`:latest` is pushed but **never deployed** — a rollback to `latest` is a rollback to
whatever was pushed most recently, which on a bad deploy is the broken image itself. The
health gate refuses it explicitly.

## Shipping a change

**1. Run the gate before you push.** From the repository root:

    bash deploy/selfcheck.sh

This is not a rough equivalent of CI — it is the *same script* CI runs, for both the pull
request and the push. It used to be two copies of the same commands in two workflow files,
they drifted, and three checks ended up gating a PR while not gating the push to `main` that
production actually takes. Everything in it is hermetic: no database, no network, no GPU,
no model call. It takes a few minutes.

**2. Open a pull request** into `dev`, `staging` or `main`. All three targets gate the same
way. CI also runs on the push itself, because this repository is pushed to directly as well.

**3. Watch the checks**, then merge. Merging into `staging` deploys to VPS-A; merging into
`main` deploys to production.

## What CI checks, and how to run each one yourself

| job | what it proves | run it locally |
|---|---|---|
| `schema` | `db/[0-9][0-9]_*.sql` builds the database `db/schema_snapshot.txt` describes, and `db/sanitise_replica.sql` still matches that schema | `./db/schema_snapshot.sh "$DSN" \| diff db/schema_snapshot.txt -` and `./db/test_sanitise_replica.sh "$DSN"` |
| `lint-and-test` | ruff, the tender pipeline's `--demo`, **every** `backend/test_*.py`, then `deploy/selfcheck.sh` | `bash deploy/selfcheck.sh` |
| `layout` | every `frontend/test_*.mjs`, then the built bundle rendered in Chromium against the committed dataset | `cd frontend && npm ci && for t in test_*.mjs; do node "$t"; done` |
| `build-images` | all three images build. **Pull requests only** — a push already builds and pushes them in Deploy | `docker build -f backend/Dockerfile .` |

Two of these find things nothing else can. `schema` catches a migration whose result was
never snapshotted — the schema files were once eleven columns and a table behind production,
every one of them added by a hand-applied `ALTER` that no file recorded. `layout` renders the
actual page: a class name matching no CSS rule is invisible to every gate that reads source
rather than pixels.

**Backend and frontend tests are found by directory, not named.** Write
`backend/test_whatever.py` or `frontend/test_whatever.mjs` and CI picks it up — you do not
edit a workflow file. Zero backend tests found is a *failure*, not a pass.

## Reading a run

**The job graph** on the run page. `needs:` renders as a DAG, so `resolve → selfcheck →
build ×3 → deploy` is the routing drawn per run. Open `resolve` to see which runner it chose
and which box answered.

**The run summary**, at the top of the Deploy run page — `deploy.sh` writes it:

| | |
|---|---|
| runner | `kssl-staging` |
| environment | staging · prefix `kssl-stg` |
| previous image | `13b73d8` |
| health gate | pass — settled on sample 3 of 20 |
| rollback | none |
| `.DEPLOYED_SHA` | `13b73d8` → `da18318` |

On a rejected deploy the same table reads `FAIL — backend restarted 3x during the gate` and
names the tag it restored. That is the fastest way to answer "what happened", and it is
written from an `EXIT` trap precisely so the failing run has one too.

**Settings → Actions → Runners** — live `Idle`/`Active` per box. Check here first when a run
sits in `queued`.

## When a deploy goes wrong

Every deploy ends with a **health gate**: both containers up, neither restarting, and the
backend actually answering `/api/health` — sampled 20 times at 3-second intervals, with
`RestartCount` compared before and after. One sample of a liveness flag is not health; a
crash-looping container is "running" for part of every cycle, which is exactly how a backend
that could not import once went green while the dashboard served 404.

If the gate fails, the deploy **rolls itself back** to the previous SHA through the same
compose file, rewrites `TAG` in the server `.env`, rewrites `.DEPLOYED_SHA`, and exits 1. You
do not need to do anything. Read the run summary to see what it restored.

`.DEPLOYED_SHA` on the box always names what is actually running — every path that changes
what runs also writes it. If it disagrees with `docker inspect`, that is a bug worth
reporting, not a routine state.

## Rolling back, or redeploying an old build

Run the **Deploy** workflow from the Actions tab (`workflow_dispatch`) with a `sha` input.
Blank means the branch tip. The SHA must be an ancestor of the branch you dispatch from — a
`main`-only commit dispatched at `staging` is refused, so you cannot cross-deploy by accident.

Recent images stay cached on the box, so a rollback is a pull-free container swap.

**Database migrations do not roll back with the image.** They are forward-only. A rollback
puts old code in front of a newer schema, which is survivable by design — the backend drops
columns it does not recognise rather than 500-ing — but it is not free, so check what the
range of commits contained.

## Deploying by hand

Don't, unless you are recovering something. `deploy/deploy.sh` refuses to run outside
Actions unless you mean it:

    KSSL_MANUAL_DEPLOY=1 ./deploy/deploy.sh <sha> <env>

It is recorded in `/opt/kssl/app/.manual-deploys.log` with who, when, and the client IP.
This exists because staging was once found running a `main` commit that no workflow had
deployed — a `/tmp/deploy.sh` written by heredoc and run as root, a recovery action that
quietly became a deployment. What a hand-run skips is everything *outside* that script: the
ancestry check, `DEPLOY_ENABLED`, the environment approval, CI and selfcheck, and the Actions
run that would have recorded any of it. What it does **not** skip is the host marker and the
health gate — which is why it is worth keeping rather than blocking.

## Before a migration reaches production

    db/rehearse_migration.sh          # exit 0 = safe, exit 1 = diverged

It pulls production's schema **and** its `schema_version` ledger (both reads; nothing is
written there), rebuilds that state locally, runs `extraction/entrypoint.sh migrate` against
it — the real runner, not a copy of its logic — and diffs the result against
`db/schema_snapshot.txt`.

The ledger is the point. A fresh database applies every migration and looks fine; only a copy
carrying production's ledger shows what production will actually do. That is how the
2026-09-04 pass found both of its faults:

- **A migration edited after production had applied it.** The ledger keys on filename, so the
  edit was invisible — prod kept a six-column table while the next deploy shipped code
  writing nine. Once a migration has run anywhere it is history; corrections are new files.
- **The rsync has no `--delete`,** so renamed schema files pile up on the box. Harmless on an
  existing database, fatal on an empty one, until the base glob was narrowed to
  `db/[0-9][0-9]_*.sql`.

Then, on the box: **stop `extraction-enrich-1` first.** Its transaction spans LLM calls for
minutes and `competitor_news` cascades from `serving.competitors`, so an `ALTER` arriving
mid-pass waits on `ACCESS EXCLUSIVE` and blocks every reader behind it — measured at 2m37s.
Back up, deploy, then verify:

    db/schema_snapshot.sh "$KSSL_DSN" | diff - db/schema_snapshot.txt

**Who applies a migration depends on the environment**, and the asymmetry is deliberate:

    if [ "$KSSL_ENV_NAME" != "prod" ] && [ -d db/migrations ]; then
      _apply_pending_migrations || echo "!! migrations: step did not complete. The deploy continues."
    fi

`staging` and `dev` migrate **themselves** on every deploy, so a column lands the moment
the branch does — that is what makes staging a real rehearsal. **Production does not.** A
migration reaches prod through `sync_from_prod.sh`, deliberately, so no push can take an
`ACCESS EXCLUSIVE` lock on the live database as a side effect.

That gap is the reason the rehearsal above matters: on staging the failure is a red deploy,
on prod it is a blocked reader.

**A migration that adds a column to a table under a view must refresh the view too.**
Postgres expands `SELECT *` at `CREATE VIEW` time into a fixed column list, so
`serving_live.*` does **not** gain a column because `serving.*` did. CI cannot catch this —
it builds every object from scratch, so the view is created after the `ALTER` and picks the
column up. Only a database where the view already exists — staging and production — keeps
serving the old list, and `backend/app.py` reads `serving_live`. End every such migration
with `CREATE OR REPLACE VIEW`.

## Things that will bite you

**A run stuck in `queued` is usually the runner, not GitHub.** A job asking for labels no
runner carries queues for **24 hours** rather than failing, which looks exactly like a slow
deploy. Check Settings → Actions → Runners.

**One runner per box means jobs serialise.** `resolve → selfcheck → build ×3 → deploy` used
to fan out across four disposable VMs; it now queues on one machine, so a Deploy takes ~12
minutes rather than ~7, and CI queues alongside it. The build is not slower — the queue is.

**A docs-only push does not deploy.** Deploy's paths filter is `frontend/ backend/ bench/
pipeline/ extraction/ db/ docker-compose*.yml deploy/ .github/workflows/deploy.yml`. CI still
runs on everything.

**`main`'s CI runs on the staging box**, deliberately. CI builds three images and starts a
postgres service container, and neither belongs on the machine serving production. It is
never offered prod's runner.

**`ssh-check.yml` is still billed.** It is the one workflow that cannot move to a runner — its
whole job is proving inbound ssh works *from a GitHub machine*. It is `workflow_dispatch`-only
and reports which layer fails (DNS, TCP, banner, key) without ever printing the host or port.
Use it before assuming a `dev` deploy failure is your change.

## Variables and secrets

Nothing secret is in git.

| repo variable | effect |
|---|---|
| `DEPLOY_ENABLED` | production only. `false` means a push to `main` builds and pushes images and leaves VPS-B alone |
| `SELF_HOSTED_PROD` / `SELF_HOSTED_STAGING` | route that environment's Deploy to its own box. Unset = back to ssh on the next run, no commit needed |
| `SELF_HOSTED_CI` | route `ci.yml` to the staging runner |

**Runtime secrets live on the boxes only** — `/opt/kssl/app/.env` and
`/opt/kssl/app/pipeline/tender_keys.env`, both root-owned `600` and gitignored. Their shapes
are documented by the committed `*.example` files.

**Actions secrets** (`VPS_HOST`, `VPS_USER`, `VPS_SSH_PORT`, `VPS_SSH_KEY`) are per-Environment
and now used **only by `dev`**, which still deploys over ssh. GHCR uses the built-in
`GITHUB_TOKEN`; the box logs in for the pull and logs out after.

## Rules

- **Never add a `pull_request` trigger to `deploy.yml`.** `push` to a protected branch needs
  write access; `pull_request` does not. A self-hosted runner on a `pull_request`-triggered
  workflow is root on production for whoever can open the pull request. `ci.yml` does take one,
  which is why it carries three tripwires and falls back to `ubuntu-latest` if any fails.
  `deploy/test_runner_paths.py` asserts both halves of this.
- **Never edit a migration that has already run anywhere.** Corrections are new files.
- **Never push to `main`.** Promote by pull request.
- **If this repository ever becomes public, remove the runners first.**
