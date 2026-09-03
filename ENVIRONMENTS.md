# Environments

Three machines, three branches, one codebase.

| Branch | Environment | Machine | Data | Extraction fleet |
|---|---|---|---|---|
| `main` | **prod** | VPS-B `62.72.59.79` | **authoritative, read-write** | 54 + 128 + 16 |
| `staging` | **staging** | VPS-A `187.127.134.12` | replica of prod | 4 + 4 |
| `dev` | **dev** | data centre `103.126.197.150:45632` | replica of prod | 1 + 1 |

Promotion is by pull request, and each step is gated by the same CI:

```
feature branch ──PR──▶ dev ──PR──▶ staging ──PR──▶ main
     (build+lint+tests)      (deploys to DC)   (deploys to VPS-A)   (deploys to VPS-B)
```

## What "same data, different phase" means here

Every environment serves **the same corpus and the same serving tables**, so a page that
looks wrong on staging looks wrong for a reason in the code, not because the data differs.

Production owns that data. `deploy/sync_from_prod.sh <staging|dev>` pulls a dump from
VPS-B and swaps it into the target's database. It is **one way, always** — the script
refuses to run against an environment whose `KSSL_DATA_ROLE` is `source`, which is prod's.

That refusal is the reason staging and dev can be destructive: whatever they do to their
copy, the next refresh overwrites it and production never saw it.

The restore lands in `kssl_incoming` and is renamed into place only after `pg_restore`
succeeds, keeping the old copy as `kssl_previous`. A half-restored environment that still
reports itself healthy is worse than one that is plainly a version behind.

## How one compose file runs on three machines

Container names carry `${KSSL_PREFIX}` and every published port is a variable. VPS-A
already runs a container called `kssl-gliner` for the crawler dashboards — that is the
collision this exists to avoid.

| | prod | staging | dev |
|---|---|---|---|
| prefix | `kssl-` | `kssl-stg-` | `kssl-dev-` |
| Postgres | 5460 | 5461 | 5462 |
| Ollama | 11434 | 11435 | 11436 |
| llmapi | 8610 | 8611 | 8612 |

`deploy/deploy.sh <sha> [env]` reads `deploy/envs/<env>.env` and writes the prefix and
ports **into the server's `.env`**. Without that, a hand-run `docker compose` on VPS-A would
interpolate the defaults and try to take over production's container names.

`env` defaults to `prod`, so the existing production deploy path is unchanged.

## Fleet sizes are deliberate, not placeholders

Staging runs 4 workers per farm and dev runs 1. They exercise every code path an extraction
run touches — claim, lease, chunk, GLiNER, LLM, store, release — without moving volume.

**Throughput measured on staging or dev is meaningless.** They share the farms with
production's 198 workers and are sized to stay out of the way. Compare rates only within
one environment.

Dev is small for a second reason: the data centre is a **shared machine** carrying the
crawler and other people's containers. Dev is there because it sits beside the crawler
corpus, so a corpus-selection change (`select_worklist.py`, `route.py`'s classes and caps)
can be tested against the real source without moving 800 MB across the network first.

## Secrets

Host, user, SSH port and key come from a GitHub **Environment** named `prod`, `staging` or
`dev` — each holding its own `VPS_HOST`, `VPS_USER`, `VPS_SSH_PORT`, `VPS_SSH_KEY`. The
workflow does not branch on the target; it just requests the environment the branch maps to.

`DEPLOY_ENABLED` still gates **production only**. Staging and dev deploy on every push,
which is the point of having them.

## Rollback

`workflow_dispatch` with a `sha` input redeploys any past build to the branch's
environment. Images are SHA-pinned in GHCR, so the rollback is a pull, not a rebuild.
