# Deployment (CI/CD)

Push-to-deploy for the KSSL / 137Parallax stack. One VPS ("VPS-B"), Docker Compose, images
built in CI and pulled by the server. Only `frontend` and `backend` are managed by CI — the
DB, LLM, gliner, tunnels and the long-running extraction farm are stable infra and are never
restarted by a deploy.


## Before a migration reaches production

    db/rehearse_migration.sh          # exit 0 = safe, exit 1 = diverged

It pulls production's schema AND its `schema_version` ledger (both reads, nothing is
written there), rebuilds that state locally, runs `extraction/entrypoint.sh migrate`
against it -- the real runner, not a copy of its logic -- and diffs the result against
`db/schema_snapshot.txt`.

The ledger is the point. A fresh database applies every migration and looks fine; only a
copy carrying production's ledger shows what production will actually do. That is how the
2026-09-04 pass found both of its faults:

  * a migration edited AFTER production had applied it. The ledger keys on filename, so
    the edit was invisible -- prod kept a six-column table while the next deploy shipped
    code writing nine. Once a migration has run anywhere it is history; corrections are
    new files.
  * the deploy's rsync has no `--delete`, so renamed schema files pile up on the box.
    Harmless on an existing database, fatal on an empty one until the base glob was
    narrowed to `db/[0-9][0-9]_*.sql`.

Then, on the box: stop `extraction-enrich-1` first (its transaction spans LLM calls for
minutes and `competitor_news` cascades from `serving.competitors`, so an ALTER arriving
mid-pass waits on ACCESS EXCLUSIVE and blocks every reader behind it -- measured at 2m37s),
back up, deploy, and verify with
`db/schema_snapshot.sh "$KSSL_DSN" | diff - db/schema_snapshot.txt`.

## Flow

```
push to kssl-deploy ─▶ GitHub Actions (deploy.yml)
                         1. build frontend + backend images
                         2. push to ghcr.io/137mallory/kssl-{frontend,backend}:<git-sha>
                         3. deploy (only if repo var DEPLOY_ENABLED == 'true'):
                              rsync the commit's source (compose, db/*.sql, deploy/) to VPS-B
                              ssh ─▶ deploy/deploy.sh <git-sha>
                                       docker compose pull frontend backend
                                       docker compose up -d --no-build frontend backend
```

**Arming:** the deploy job is gated on the repo variable `DEPLOY_ENABLED`. While it is unset
or `false`, pushes only build+push images to GHCR and the VPS is never touched. Set it to
`true` (repo → Settings → Variables → Actions) to turn on auto-deploy. Source is rsynced from
the CI checkout (the VPS needs no GitHub credentials); runtime files on the VPS (`.env`,
`PRODUCTION.html`) are excluded from the sync and never deleted.

Images are **SHA-pinned and immutable** (`:latest` is never deployed). The server `.env`
holds `TAG=<sha>`; `docker-compose.prod.yml` overrides the two services to
`ghcr.io/137mallory/kssl-<svc>:${TAG}`.

## Files

| file | role |
|------|------|
| `docker-compose.vps.yml` | base stack (source of truth), `build:` for local dev + infra |
| `docker-compose.prod.yml` | prod override: `image:` from GHCR for frontend+backend |
| `deploy/deploy.sh` | run on the VPS: checkout sha, pin TAG, pull+recreate the two services |
| `.github/workflows/deploy.yml` | build → push GHCR → SSH deploy on push to `kssl-deploy` |
| `.github/workflows/ci.yml` | PR gate: image builds + ruff + hermetic pipeline `--demo` |

## Secrets

Nothing secret is in git.

- **Runtime secrets** live on the VPS only: `/opt/kssl/app/.env` (DB password, domain, basic-auth)
  and `/opt/kssl/app/pipeline/tender_keys.env` (SAM keys) — both root-owned, `chmod 600`,
  gitignored, referenced by compose. Shapes are documented by the committed `*.example` files.
- **GitHub Actions secrets** (repo → Settings → Secrets → Actions):
  `VPS_HOST`, `VPS_USER`, `VPS_SSH_PORT` (optional), and `VPS_SSH_KEY` — a **dedicated deploy
  keypair**, not a reused root key. GHCR push/pull uses the built-in `GITHUB_TOKEN`; the VPS
  logs in with that token for the pull and logs out after.

> The SAM keys were committed to history in an earlier commit. **Rotate them at SAM.gov** —
> that is the real fix; the repo is private so history is not rewritten.

## Rollback

Re-run the **Deploy to VPS-B** workflow (`workflow_dispatch`) with a previous `sha`, or on the
VPS: set `TAG=<old-sha>` in `.env` and `docker compose -f docker-compose.vps.yml -f
docker-compose.prod.yml up -d --no-build frontend backend`. Recent images stay cached on disk.
DB schema changes are forward-only (they don't roll back with the image).

## One-time VPS bootstrap

`/opt/kssl/app` is a git checkout of `kssl-deploy`. The deploy user needs Docker access, the
`deploy` public key in `~/.ssh/authorized_keys`, and the root-owned `.env` / `tender_keys.env`
in place. After that every push deploys itself.
