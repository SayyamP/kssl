# KSSL_Deploy — deployable demo

A self-contained, deployable version of the KSSL competitive-intelligence dashboard.
React frontend + FastAPI backend + one Postgres with **two schemas**:

- `extracted` — what our extraction pipeline produces (documents, spans, propositions, parsed
  values, resolved entities). Same shapes as the existing Layer A/B store.
- `serving` — tables that DIRECTLY power the UI. Column design follows `reference.html`
  (the shipped KSSL-Parallax app, dataset contract in `contract_shapes.json` /
  `contract_samples.json`, full data in `reference_dataset.json`).

## Layout

    KSSL_Deploy/
      PLAN.md                  this file
      UI_CONTRACT.md           every tab/view/click of reference.html and the globals it reads
      reference.html           the app whose behaviour is the specification
      reference_dataset.json   its 35-global dataset (hand-researched; used to SEED serving)
      contract_shapes.json     per-global shape + field union (machine-readable contract)
      contract_samples.json    two real entries per global
      db/
        schema_extracted.sql   Postgres port of the extraction store
        schema_serving.sql     serving tables + serving.ui_config for interface vocabulary
        seed_serving.py        loads reference_dataset.json into serving (demo works day one)
      backend/
        app.py                 FastAPI: GET /api/dataset assembles all 35 globals from serving
        requirements.txt
      frontend/                React app (adapted from the existing KSSL-Parallax/web)
      pipeline/
        fetch_corpus.py        fetch real defence articles -> extracted.document
        run_extraction.py      Layer A + Layer B over new documents -> extracted schema
        serving_fill.py        local LLM turns extracted claims into serving rows
      docker-compose.yml       postgres :5460 + backend :8600 + frontend

## Decisions (made, not open)

- One Postgres, two schemas, port **5460** (5440 is the parallax store; do not touch it).
- Backend port **8600**; frontend dev proxy `/api` -> 8600.
- Data-bearing globals become real tables (competitors, cards, details, matchups, tenders,
  patents, geo, innovations, partners, sources). Interface vocabulary (CAT_KEY, POS_CATS,
  FIELDSYN, REL_LABEL, actLabel, chatSuggest, client, overviewConfig, ...) lives in
  `serving.ui_config(key text primary key, value jsonb)` seeded from the reference dataset —
  it describes the interface, not the world, and the pipeline never writes it.
- Arrays the UI consumes as arrays (a detail's `lens` pairs, a matchup's spec rows) are JSONB
  columns; things the pipeline writes row-by-row are real columns.
- The API returns the SAME 35-global shape the app already binds to; the frontend change is
  only "fetch instead of embedded".
- The serving seed from reference_dataset.json marks every row `origin='reference'`; pipeline
  rows are `origin='pipeline'`. The UI can show both; the audit must be able to tell them apart.

## Hard rules

- The 35 globals and their field names in contract_shapes.json ARE the contract; presence is
  not shape — the API must emit usable shapes for every global (an empty groups list or a
  string where a list belongs blanks the whole app; both have happened).
- Never render a number the store cannot support; carry the reference app's honest-state
  patterns through.
- Windows PowerShell 5.1 runs .ps1 as ANSI: any .ps1 here is ASCII-only.
- The existing stores (5440 parallax, the SQLite stores, :9500/:9600/:9700 services) are not
  to be modified by this project.
