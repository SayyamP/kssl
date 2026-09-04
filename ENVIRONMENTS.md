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
| preflight | `extraction/.env` exists and the extraction compose **parses** | yes, before anything expensive |
| restore | into `kssl_incoming`, never over the live database | no — `pg_restore` warns for things that do not matter |
| verify | row counts, **and** that `serving_live` arrived | yes, before the swap |
| sanitise | `db/sanitise_replica.sql` | yes, before the swap |
| slice | optional, `KSSL_SLICE_DOCS` | yes, before the swap |
| migrate | the `migrate` role, against `kssl_incoming` | yes, before the swap |
| swap | rename under one lock | — |

**Everything that can fail, fails before the swap.** A sync that dies leaves the
environment on the database it was already serving. The preflight matters more than it
looks: Compose interpolates the *whole* `extraction/docker-compose.yml` at parse time, so
one missing `${VAR:?}` breaks `run --rm migrate` — and checking that at the migrate step
meant discovering it after a multi-minute restore *and* after the rename.

**`serving_live` is checked by name.** `backend/app.py` rewrites every `serving.` to
`serving_live.` unless `KSSL_SERVE_ORIGIN=all`, and `serving_live` is a set of *views* — so
no row count can miss it. A dump without `-n serving_live` produced a replica that reported
every count healthy and 500'd on every page.

**Sanitise runs before the swap, not after.** The client's own pages (`bharatforge.com`,
`kalyanistrategic.com`, `kssl.in`), their extraction output, and the `signal_card` /
`signal_detail` rows written *from* them leave together — deleting the body and keeping the
card would remove the evidence and keep the claim. Production's `metrics.*` timings are
truncated; the schema is kept, because `/api/bench` reads it, but prod's numbers measured a
198-worker fleet on VPS-B and would be read as this environment's.

A **citation is not the material**: `serving.competitors`, `card`, `partner` and the rest
cite client URLs as sources for KSSL's own products, which is what the dashboard is for.
Those stay.

The pattern is **anchored to the host** and defined once. Unanchored, `kssl\.in` also
matches `https://economictimes.com/news?ref=bharatforge.com` — a third-party article
deleted with all its extraction output because a client domain appears in a query string.

The file re-counts what it removed and raises if anything survived; `psql` exits non-zero
and the script dies **before** the rename. It also refuses to run against any database but
the restored copy — it is rsynced onto VPS-B with the rest of the tree, and its statements
delete corpus rows.

What that does **not** promise: `kssl_incoming` is a real database on the host for the
whole restore, and the copy it replaces survives as `kssl_previous` until the sync after
next. Anyone holding the box's database password can read both. The guarantee is that an
unsanitised database is never reachable **as `kssl`** — the one the backend, the frontend
and every operator actually open.

`db/test_sanitise_replica.sh` runs in CI beside the schema job: it plants rows the sanitise
must remove, rows it must keep, and one only its own guard can catch. A `DELETE` whose
predicate is a regex rots the moment a column moves, and a regex that matches nothing looks
exactly like a clean database.

**Migrate runs against `kssl_incoming`, before the swap.** The restored schema is
production's *as of the dump*, and staging is by definition ahead of it — that is what
staging is for. Without this step every sync silently reverts the replica's schema and the
next deploy runs new code against an old one. Running it before the rename means a
migration that fails leaves the environment on its previous database instead of on a fresh
copy of production's schema. The DSN is the host's own with only the database name
changed, and the script refuses to run if that substitution did not bite.

**Slice** (`KSSL_SLICE_DOCS`, set to 20000 in `dev.env`) keeps the newest N rows of
`public.documents` **and** the newest N of `extracted.document`, each by its own clock.
Slicing extraction output by which *bodies* survived would delete most of it — the corpus
subset rolls over while the extraction output accumulates — and orphan `serving.card` from
the spans it was built from. `serving.*` is left whole, since a card carries its own url
and quote. It trims after the transfer, so it bounds the replica's disk, not what crossed
the wire.

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
  receive a staging or dev deploy. This is the arm that actually covers the fallback
  today; the stamp is defence in depth for once a marker exists.
- `provision_env.sh` **refuses to re-stamp** a machine already provisioned as something
  else (`KSSL_RESTAMP=1` to override). Without that, `provision_env.sh staging` run on
  VPS-B would flip prod's marker and *admit* the staging deploy it exists to refuse.
- `.KSSL_ENV` is gitignored and rsync-excluded. It names *which machine this is*; shipping
  one box's copy to every box would lock hosts out or, worse, misidentify them.

## Rollback

`workflow_dispatch` with a `sha` input redeploys any past build to the branch's
environment. Images are SHA-pinned in GHCR, so the rollback is a pull, not a rebuild.

The SHA must be an **ancestor of the branch it deploys**. Rolling back is unaffected — an
earlier commit on `main` is an ancestor of `main` — but a commit from another branch, an
unmerged pull request or a fork is refused. Without that check, dispatching on `main` with
any commit the repository can reach put unreviewed code on VPS-B under a run that reported
itself as a production deploy of `main`.
