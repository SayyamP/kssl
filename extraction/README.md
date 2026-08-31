# VPS-B Extraction — automatic, self-contained deployment

Everything needed to run the extraction pipeline **unattended on VPS-B**, writing to VPS-B Postgres.
No SQLite, no local files, no manual steps after `up`. LLM + GLiNER run on the GPU farm over HTTP.

This folder is the **authoritative copy for VPS-B**. The engine under `engine/` was built from
`comprehend/` at the point every audit fix landed; edit it here and redeploy, don't fork it again.

---

## What runs (the automatic loop)

```
  data-centre corpus (crawler, 81 GB)                 GPU farm (LLM + GLiNER)
         │  sync_documents.py (dated, gated)                    ▲
         ▼                                                      │ HTTP
  ┌──────────────────────────  VPS-B Postgres  ──────────────────────────┐
  │  documents ──enqueue──▶ extract_queue ──claim──▶ [worker] ──store──▶ │
  │   (route.py)             (presignal gate)      run_node.py  extracted.*│
  └───────────────────────────────────────────────────────────────────────┘
                                   ▲ reap expired leases (route.py --reap)
```

Three long-running roles from one image, hand-off through the queue in Postgres:

| role     | what it does                                                              |
|----------|---------------------------------------------------------------------------|
| `worker` | claim → extract (farm) → store spans + done-mark in one transaction, forever |
| `feeder` | every `FEED_EVERY_S`: sync new corpus docs → enqueue (presignal gate) → reap |
| `migrate`| one-shot: apply `db/*.sql` (documents, extracted.*, serving.*)             |

Why `documents` lives on VPS-B: the store writes spans **and** the queue done-mark in **one
transaction on one connection**, so the document text, the queue, and `extracted.*` must be in the
same database. `sync_documents.py` copies only the small, dated, length-banded subset we extract —
it never scans the crawler's 81 GB TOAST columns.

---

## Deploy

**1. Corpus tunnel** (host, once) — the DC Postgres reached on loopback, never exposed:
```bash
ssh -f -N -o ServerAliveInterval=15 -L 127.0.0.1:15432:localhost:5432 -p 45632 sysadmin@<DC_HOST>
```

**2. Config:**
```bash
cp .env.example .env && $EDITOR .env      # fill DSNs + farm key
```

**3. Schema** (creates tables in VPS-B Postgres):
```bash
docker compose run --rm migrate
```

**4. Run forever:**
```bash
docker compose up -d worker feeder
docker compose logs -f            # watch it work
```

Scale workers (each claims its own docs via `FOR UPDATE SKIP LOCKED`):
```bash
docker compose up -d --scale worker=3 worker
```

**Without Docker** (systemd): `engine/` + `sync_documents.py` need only Python 3.11 + `psycopg2` +
`httpx`. Run `entrypoint.sh worker` and `entrypoint.sh feeder` as two units; set the env in the unit.

---

## Verify it's healthy

```bash
docker compose run --rm worker sh -c 'cd engine && python3 route.py --status'   # queue depth, deficit
python3 test_fixes.py                                                            # audit fixes intact
```
In Postgres: `SELECT state, count(*) FROM extract_queue GROUP BY 1;` and
`SELECT count(*) FROM extracted.document;` should climb.

---

## How it's wired to the farm

The engine calls the farm directly (not the llmapi router): `OLLAMA_URL` + `C_OPENAI=1` +
`C_MODEL=text-model` + `C_GLINER_URL`. The worker's node identity is **`farm`** (`KSSL_NODE=farm`) so
it claims farm-scale documents and its lease TTLs are sized for farm throughput (`C_TOK_S=50`).
Set `C_CTX_MAX` to the farm's real context — leaving it at 4096 truncates dense chunks.

---

## Maintenance

- **One authoritative tree.** Edit `engine/*.py` here and redeploy. Do not re-copy from `comprehend/`
  without re-checking `test_fixes.py` — that file pins the audit fixes.
- **Poison documents self-heal:** a doc that crashes a worker is released and, after
  `MAX_ATTEMPTS`, parked with a reason (`SELECT document_id, reason FROM extract_queue WHERE
  state='parked';`) — it never loops a worker forever.
- **Schema changes:** add a numbered file to `db/` and re-run `migrate` (idempotent DDL).
- **Regression gate:** run `python3 test_fixes.py` before every deploy.

See `../../AUDIT_TODO.md` for the full audit, what was fixed, and what remains (mediums/lows).
