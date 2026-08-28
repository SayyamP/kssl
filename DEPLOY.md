# Deploying KSSL_Deploy on a Hostinger VPS (32 GB / 8 vCPU)

## The recommendation, in one line

**Put the serving stack AND the signal LLM on the VPS. Keep the crawler and
Layer A/B extraction off it.**

The VPS runs Postgres + backend + the built frontend, published through the Traefik
already on that server — about **3 GB of RAM and well under one core at rest**. Extraction (Layer A/B) and the LLM run where
the GPU is, and write their results into the VPS database over an SSH tunnel. The
VPS then cannot be taken down by the work that actually loads a machine, because
that work is not on it.

## The LLM on the VPS: measured, and the earlier answer was wrong

An earlier version of this file said a 14B on these cores answers one prompt in
3-5 minutes, that a pipeline pass would take **days**, and that the LLM must
never run here. That was wrong, and the mistake is worth naming: it assumed
600-token answers. A real signal card is about **145 tokens**.

Measured with `deploy/remote/bench_cpu_llm.py`, which reads Ollama's own token
counts rather than timing with a stopwatch, on the VPS with no GPU:

| Model | Disk | Resident | gen tok/s @6 cores | One real card |
|---|---|---|---|---|
| `qwen3:4b` | 2.5 GB | 3.9 GB | 13.2 | 45 s -- it is a reasoning model and spends ~600 tokens thinking |
| **`qwen2.5:7b-instruct`** | 4.7 GB | **5.5 GB** | **10.5** | **14 s** |
| `qwen2.5:14b-instruct` | 9.0 GB | 10.0 GB | 5.3 | 28 s |

A few hundred cards at 14-28 s each is **under two hours**, not days. The 7B is
the choice: the 4B is faster per token but slower per *answer*, and the 14B
costs twice the RAM for half the speed on output this short.

### Cores, and the thread-pool bug

| CPU cap | default threads | `num_thread` = cap |
|---|---|---|
| 2 | 2.5 tok/s | -- |
| 3 | 4.1 tok/s | **9.0 tok/s** |
| 4 | 6.0 tok/s | **11.4 tok/s** |
| 6 | 9.9 tok/s | -- |
| 8 | 17.4 tok/s | -- |

The default-threads column scales *superlinearly*, which no compute-bound
workload does. Ollama sizes its thread pool from the **host's** core count and
ignores the container's CPU quota, so a capped container spends its slice
context-switching between threads it cannot run. Pinning `num_thread` to the cap
roughly doubles throughput -- four pinned cores beat six unpinned ones, and that
is what let the LLM fit on an 8-core box alongside the database.

Set via `KSSL_LLM_THREADS`, consumed in `pipeline/serving_fill.py:llm_opts`.

### The data centre is the slow one — and what fixed it

> **Update, 2026-08-25.** The contention described below has been dealt with and
> extraction now runs at the data centre permanently, in containers, under
> `deploy/datacentre/`. The crawler fleet was cut from twelve instances to seven
> and pinned back to `0-19`; the box went from load ~140 to the 60s, and the L2
> lane `20-29` is extraction's alone. Nothing runs on a workstation any more.
> Read the rest of this section as the reasoning that led there, not as current
> state.


The same model, same benchmark, on the 40-core data centre: **1.06 tok/s**
with default threads, **1.61 tok/s** with them pinned -- against 11.4 on four
VPS cores. Not a hardware limit.

Note what the pinning tells you. On the VPS, pinning threads to the cap *doubled*
throughput, because the loss there was thread thrash. Here it buys only half
again, because the loss is contention for cores another process is already
using -- and no amount of pinning fixes that. The documented box division
is crawler `0-19` / L2 `20-29` / SFL `30-34`, but the twelve running
`crawler-api` containers are pinned `0-34`, so they spill across the extraction
lane and the box was at load 87 with the news crawl running. **Extraction and
crawling currently compete for the same cores.** Either pin the crawlers back to
`0-19` or schedule extraction against a quiet fleet; do not read the 1.06 as the
machine's capability.

## The split

```
                    VPS (32 GB / 8 vCPU)                  Data centre (40 cores)
        ┌──────────────────────────────────────┐        ┌────────────────────────────┐
        │  Traefik :443 ─►  frontend (static)   │        │  crawler fleet   0-19      │
        │  (already there) └► /api ► backend    │        │  corpus Postgres 35-39     │
        │                        │             │        │  Layer A + Layer B  20-29  │
        │                   Postgres           │◄───────┤  qwen2.5:7b + GLiNER       │
        │                (extracted+serving)   │  ssh   │  kssl-autopilot            │
        │                        │             │ tunnel │  kssl-bench                │
        │      kssl-llm  qwen2.5:14b-instruct  │───────►│                            │
        └──────────────────────────────────────┘  the   └────────────────────────────┘
             reads, and writes the cards        same tunnel     all the heavy work
```

Both directions ride one ssh session, held by the `kssl-tunnel` container at the
data centre: `kssl-tunnel:5460` is the VPS database and `kssl-tunnel:11500` is the
VPS model. The data centre never accepts an inbound connection, and neither VPS
port is on the internet.

The pipeline scripts already take their target from one environment variable
(`KSSL_DSN`), so pointing them at the VPS is a one-line change on the machine that
runs them — no code moves.

## Resource budget on the VPS

Every limit below is a **hard** cap in `docker-compose.vps.yml` (`cpus:` and
`mem_limit:`), not a share. A weight is not a cap: `cpu_shares` only decides who
wins when the box is already contended, which is too late.

| Service | Cores | RAM | Notes |
|---|---|---|---|
| Postgres | 2.0 | 8 GB | `shared_buffers=2GB`; the database is small and read-mostly |
| Backend (FastAPI) | 1.0 | 1 GB | one dataset read per page load |
| Frontend (static) | 0.5 | 256 MB | serves a built bundle |
| Signal LLM | 4.0 | 8 GB | 11.4 tok/s with threads pinned to the cap |
| TLS front door | -- | -- | the server's existing Traefik, not ours to run |
| **Total** | **7.5** | **~17.3 GB** | leaves 0.5 core and ~14 GB for the OS and co-tenants |

That 0.5-core margin is thin, and it is a deliberate trade: the LLM is the only
thing on this box that can use cores, and it is idle except while a fill runs.
If a co-tenant ever suffers, `KSSL_LLM_CPUS=3` costs about 20% of card
throughput (9.0 vs 11.4 tok/s, both with threads pinned) and hands a core back.

Headroom is deliberate. The failure this layout prevents is not "we ran out of
RAM once" — it is a background job taking every core while somebody is looking at
the dashboard.

## What the database holds

214 MB total, and 171 MB of that is `extracted.span` — the provenance layer. It
transfers in seconds and restores in under a minute, so the deployment does not
need a replication story yet: `pg_dump` from here, `pg_restore` there.

## What is already on 62.72.59.79 (checked, read-only)

`python deploy/vps_check.py` connects and reports. On 2026-08-25 it found:

| | |
|---|---|
| CPU | AMD EPYC 9354P, **8 cores** |
| Memory | **31 GB total, 30 GB available**, and **no swap** |
| Disk | 387 GB, 385 GB free |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8 |
| Docker | 29.7.2 with Compose v5.5.0, already installed |
| Already running | **`traefik-traefik-1`**, on the HOST network, holding :80 and :443 |
| Firewall | ufw inactive |
| Postgres client | not installed |

**The front door is already taken, and that changed the plan.** Traefik runs with
`--providers.docker=true`, `exposedbydefault=false`, a Let's Encrypt HTTP-challenge
resolver and an HTTP→HTTPS redirect. Bringing up our own Caddy on :80/:443 would
have collided with it and taken down whatever else it serves. So the stack
publishes nothing on 80/443: the two web containers carry Traefik labels
(`Host(...)` for the app, `Host(...) && PathPrefix(/api)` at a higher priority for
the backend) and Traefik routes to them. The Caddyfile that used to be here is
gone.

`srv1928858.hstgr.cloud` already resolves publicly to 62.72.59.79, so it works as
`KSSL_DOMAIN` without buying a name; point a real domain at the same address when
you have one.

**Three things to fix on that server before it holds anything real:**
1. **Root logs in with a password over SSH.** Add a key, then set
   `PasswordAuthentication no`. Until then the whole box is one guess away.
2. **Rotate that password.** It was pasted into `.env.example` — the file that gets
   committed — so treat it as exposed. It is now in `.env`, which is gitignored.
3. **No swap.** 31 GB is ample for this stack, but a single unbounded process
   currently OOM-kills instead of slowing down. 4 GB of swap is cheap insurance.

## Order of operations (nothing is run until you say so)

1. Fill in `.env` (copy from `.env.example`) — the only file with credentials, and
   it is gitignored. `python deploy/vps_check.py` proves the connection works
   before anything is built.
2. `docker compose -f docker-compose.vps.yml up -d db` — schemas create themselves
   on a fresh volume.
3. Load the data: `pg_dump` here → `pg_restore` there (`deploy/deploy_vps.sh dump` /
   `tunnel` / `restore` do exactly this and nothing else).
4. `docker compose -f docker-compose.vps.yml up -d` — backend and frontend; the
   existing Traefik picks them up from their labels.
5. Point the DNS A record at the VPS (or use `srv1928858.hstgr.cloud`, which
   already resolves there); Traefik fetches the certificate on the first request.
6. On the machine that runs extraction, export `KSSL_DSN` through the tunnel and
   run the pipeline as usual.

## What is deliberately NOT on the VPS

(The signal LLM used to be on this
list. It no longer is -- see the measurements above.)

- **The crawler.** It is I/O-heavy, it gets rate-limited, and it needs the browser
  fleet.
- **Layer A / Layer B extraction.** Hours of GPU work per batch.
- **The corpus Postgres** (1.1M documents, 219 GB). Only the KSSL slice ships.
