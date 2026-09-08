# KSSL_Deploy

A deployable demo of the KSSL competitive-intelligence dashboard: React + FastAPI + Postgres,
fed by a real crawled corpus through the extraction pipeline and a local LLM.

## Run it

    docker compose up -d          # postgres :5460 (schemas auto-created) + backend :8600
    python db/seed_serving.py     # loads the reference dataset (demo works immediately)
    cd frontend && npm install && npm run build && npx vite preview --port 5178

Open http://127.0.0.1:5178 — the full dashboard, every view live from Postgres.

## The two schemas

- **extracted** — what the pipeline produces: documents, offset-checked spans, propositions
  with evidence quotes, parsed values, canonical entities. Loaded by `pipeline/load_extracted.py`.
- **serving** — tables that directly power the UI, column-for-column from the reference app's
  dataset contract (`contract_shapes.json`). Every row carries `origin`:
  `'reference'` (the hand-researched seed) or `'pipeline'` (generated from the corpus).
- **serving_live** — views over `serving` filtered to `origin='pipeline'`; this is what the
  API serves. The reference rows are ARCHIVED: still in the tables (and in
  `reference_dataset.json`) but not shown. `KSSL_SERVE_ORIGIN=all` on the backend points it
  back at the raw tables to see the archive.

## The pipeline (real data path)

    python pipeline/fetch_corpus.py      # defence-press feeds + competitor/product queries
                                         #   -> pipeline/corpus/*.json  (99 docs, 6 languages)
    python pipeline/run_extraction.py    # Layer A + Layer B via l2/comprehend (GPU, hours)
    python pipeline/load_extracted.py    # SQLite stores -> extracted schema (offset-checked)
    python pipeline/serving_fill.py      # qwen2.5:14b turns propositions into signal cards
                                         #   -> serving.signal_card/_detail, origin='pipeline'

Each step is idempotent and each has `--demo` (a runnable self-check with no side effects).

## What keeps it honest

- A document whose span offsets fail `text[start:end] == span.text` is REFUSED at load.
- The LLM only ever sees extractor-grounded propositions with quotes; every generated card's
  detail panel shows those quotes verbatim. "NONE" is a recorded outcome, not a retry.
- A generated category must be one of the reference dataset's nine; anything else refuses.
- `origin` separates seeded rows from pipeline rows everywhere, so an audit can tell them apart.

## Documents

- `PLAN.md` — architecture and the decisions already made.
- `UI_CONTRACT.md` — every view, click, filter and derived value of the reference app, and
  which globals/fields each reads. The schema and API were built against this.
- `contract_shapes.json` / `contract_samples.json` — the 35-global dataset contract.
- `docs/DEPLOY.md` — **start here to ship a change.** Branch-to-machine map, what each CI job
  proves and how to run it yourself, the health gate and automatic rollback, migrations.
- `deploy/RUNNERS.md` — the self-hosted runners: installing, arming, the trust boundary, and
  two diagrams of the deploy flow.
- `ENVIRONMENTS.md` — how one compose file runs on three machines, and how data gets to them.

## Ports

| what | where |
|---|---|
| Postgres (kssl) | 127.0.0.1:5460 |
| FastAPI backend | 127.0.0.1:8600 (`/api/dataset`, `/healthz`) |
| frontend preview | 127.0.0.1:5178 |

Nothing here touches the main Parallax stores (:5440, :9500, :9600, :9700).

## Repository layout

    backend/ frontend/ pipeline/ extraction/ llmapi/ db/   # code
    docs/                                                   # all documentation (PLAN, UI_CONTRACT, contracts)
    docker-compose.vps.yml   docker-compose.prod.yml        # base stack + GHCR image override
    deploy/deploy.sh   .github/workflows/                   # CI/CD

Documentation lives under [`docs/`](docs/) — kept out of the code tree.

## Deployment (CI/CD)

Three branches, three machines: `main` → prod (VPS-B), `staging` → VPS-A, `dev` → the data
centre. GitHub Actions builds SHA-pinned images to GHCR and the target recreates **only**
`frontend` and `backend` (the extraction farm and DB/LLM containers are never touched),
behind a health gate that rolls itself back if the new build does not answer.

`main` and `staging` deploy **from a runner on the box they deploy to**, so GitHub opens no
connection into either machine; `dev` still goes over ssh. Read
[`docs/DEPLOY.md`](docs/DEPLOY.md) before your first push — it covers running the gate
locally, reading a run, and rolling back. [`deploy/RUNNERS.md`](deploy/RUNNERS.md) is the
operator runbook for the runners themselves.
