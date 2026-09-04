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

Staging and dev serve **production's corpus and serving tables, minus two things they are
not allowed to hold** (below), so a page that looks wrong on staging looks wrong for a
reason in the code, not because the data differs.

Production owns that data. `deploy/sync_from_prod.sh <staging|dev>` pulls a dump from
VPS-B and swaps it into the target's database. It is **one way, always** — the script
refuses to run against an environment whose `KSSL_DATA_ROLE` is `source`, which is prod's.

That refusal is the reason staging and dev can be destructive: whatever they do to their
copy, the next refresh overwrites it and production never saw it.

The restore lands in `kssl_incoming` and is renamed into place only after `pg_restore`
succeeds, keeping the old copy as `kssl_previous`. A half-restored environment that still
reports itself healthy is worse than one that is plainly a version behind.

### The five stages of a sync

| | | Fails the sync? |
|---|---|---|
| restore | into `kssl_incoming`, never over the live database | no — `pg_restore` warns for things that do not matter |
| verify | row counts, **and** that `serving_live` arrived | yes, before the swap |
| sanitise | `db/sanitise_replica.sql` | yes, before the swap |
| slice | optional, `KSSL_SLICE_DOCS` | yes, before the swap |
| swap | rename under one lock | — |
| migrate | the `migrate` role, same ledger the deploy uses | yes |

**`serving_live` is checked by name.** `backend/app.py` rewrites every `serving.` to
`serving_live.` unless `KSSL_SERVE_ORIGIN=all`, and `serving_live` is a set of *views* — so
no row count can miss it. A dump without `-n serving_live` produced a replica that reported
every count healthy and 500'd on every page.

**Sanitise runs before the swap, not after.** The client's own pages (`bharatforge.com`,
`kalyanistrategic.com`, `kssl.in`) and their extraction output leave, and production's
`metrics.*` timings are truncated — the schema is kept, because `/api/bench` reads it, but
prod's numbers measured a 198-worker fleet on VPS-B and would be read as this
environment's. The file re-counts what it removed and raises if anything survived; `psql`
exits non-zero and the script dies **before** the rename. A replica host is a QA box other
people can reach, so an unsanitised database must never become reachable.

`db/test_sanitise_replica.sh` runs in CI beside the schema job: it plants rows the sanitise
must remove, rows it must keep, and one only its own guard can catch. A `DELETE` whose
predicate is a regex rots the moment a column moves, and a regex that matches nothing looks
exactly like a clean database.

**Migrate runs after the swap.** The restored schema is production's *as of the dump*, and
staging is by definition ahead of it — that is what staging is for. Without this step every
sync silently reverts the replica's schema and the next deploy runs new code against an old
one. It needs `extraction/.env`, which `provision_env.sh` writes.

**Slice** (`KSSL_SLICE_DOCS`, set to 20000 in `dev.env`) keeps only the newest N corpus
documents; `serving.*` is left whole, since a card carries its own url and quote. It trims
after the transfer, so it bounds the replica's disk, not what crossed the wire.

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

**Give each Environment its own host secrets.** A GitHub Environment with no secrets of its
own falls back to the *repository* secrets, and those point at production — so a push to
`staging` would deploy onto VPS-B under `kssl-stg-` names, orphaning production's frontend
and backend while reporting success. Two things stop that now:

- `provision_env.sh` stamps `.KSSL_ENV` on staging and dev hosts, and `deploy.sh` stamps
  `prod` on VPS-B the first time a production deploy runs there. A deploy naming a
  different environment than the marker is refused.
- A host with **no** marker accepts only `prod`, so an unprovisioned machine can never
  receive a staging or dev deploy.

## Rollback

`workflow_dispatch` with a `sha` input redeploys any past build to the branch's
environment. Images are SHA-pinned in GHCR, so the rollback is a pull, not a rebuild.

The SHA must be an **ancestor of the branch it deploys**. Rolling back is unaffected — an
earlier commit on `main` is an ancestor of `main` — but a commit from another branch, an
unmerged pull request or a fork is refused. Without that check, dispatching on `main` with
any commit the repository can reach put unreviewed code on VPS-B under a run that reported
itself as a production deploy of `main`.
