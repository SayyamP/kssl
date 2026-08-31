# VPS-B flow audit — intended vs codebase

Audit of whether the codebase implements the intended flow, with the logic written to close each gap.
Intended flow (as stated): VPS-B is the **orchestrator**; it checks VPS-A + farm are healthy, then
sends documents for processing; VPS-A + farm serve LLM/GLiNER as APIs; extraction is Layer A **and**
B; results are written to VPS-B `extracted.*`; a **selection** step drives which corpus docs go first,
per `l2_processing_list.xlsx`.

## Verdict per element

| # | Intended | Codebase reality | Status | What was written |
|---|----------|------------------|--------|------------------|
| 1 | Deployment folder on VPS-B, orchestrator + routing | `kssl-deploy/extraction/` exists; the **llmapi router** *is* the routing orchestrator (health-gated, failover, per-node budgets) but the engine bypassed it | **Fixed** | Router `/v1/chat/completions` shim + engine points at router |
| 2 | VPS-B calls **VPS-A + farm** for LLM/GLiNER | Engine used a single `OLLAMA_URL` (farm only). Router routes multi-node but engine didn't use it | **Fixed** | LLM now routes via router (`OLLAMA_URL=router`, OpenAI shim); GLiNER via `router/v1/gliner` (contract already matches) |
| 3 | Check VPS-A + farm **alive** before sending | Router `/v1/nodes` live-probes each backend; nothing gated dispatch on it | **Fixed** | `health_gate` in `entrypoint.sh` blocks worker/feeder until `KSSL_MIN_HEALTHY_NODES` backends are up |
| 4 | LLM, GLiNER, **lexicon** via API | LLM + GLiNER remote ✓. **Lexicon is local CPU** — deterministic gazetteer retyping, no GPU | **Clarified** | Lexicon correctly runs on VPS-B CPU inside the worker; "lexicon as API" is not applicable (nothing to serve remotely). No change needed. |
| 5 | Extraction = Layer A **and** B | Layer A wired to Postgres. **Layer B ported to Postgres** (`layer_b_pg.py`) — reads `extracted.span`, writes `extracted.entity`/`entity_alias` | **Fixed** | `layer_b_pg.py` (blockers 1+2, same-script) + `layerb` role/service. Cross-script (embeddings) documented as the one extension point. |
| 6 | Write to VPS-B `extracted.*` | `store_pg.save_and_commit` writes spans + done-mark to VPS-B in one transaction ✓ | **OK** | — |
| 7 | Selection from `l2_processing_list` | `route.py --enqueue` selects by crawler freshness/presignal classes (P0–P3), **not** the workbook's P1–P7 evidence lanes | **Fixed** | `worklist.json` (21,875 docs) + `select_worklist.py` enqueue by lane; `C_NODE_MAX_CLASS` lets the worker claim P1–P7 |

## How the routed flow now works

```
  l2_processing_list ─► select_worklist.py ─► documents + extract_queue (class = lane P1..P7)
  crawler freshness  ─► sync + route --enqueue ─┘         (VPS-B Postgres)
                                                          │ claim (lane order)
                          health_gate (vps-a+farm up?) ───┤
                                                          ▼
        run_node worker ──LLM+GLiNER──► llmapi router ──► vps-a  OR  farm   (failover, budgets)
        (lexicon = local CPU)                    │
                                                 ▼
                              store_pg ─► extracted.* (VPS-B)
```

- **Routing:** the engine speaks OpenAI to the router (`OLLAMA_URL=http://127.0.0.1:8610`,
  `C_OPENAI=1`); the new `/v1/chat/completions` shim runs it through the router's multi-node
  `generate()`. GLiNER goes to `router/v1/gliner`. The router's `LLM_NODE_ORDER=farm,vps-a` and
  `GLINER_NODE_ORDER` decide the spread; per-node model mapping sends `text-model` to the farm and
  `qwen2.5:7b-instruct` to vps-a automatically.
- **Health gate:** `entrypoint.sh health_gate` polls `router/v1/nodes` and refuses to start the
  worker/feeder until at least one backend is genuinely up — the "check vps-a + farm alive first" step.
- **Selection:** `select_worklist.py` walks `worklist.json` P1→P7, pulls each body from the corpus if
  absent, and enqueues it with `class = lane`, so the worker drains the strongest evidence first.

## Layer B — ported to Postgres (built)

`layer_b_pg.py` reuses `layer_b.py`'s pure blockers (fold, character 3-grams, script/identifier
gates, union-find), reads every referential span from `extracted.span`, clusters the surfaces that
name the same thing, and writes one `extracted.entity` per cluster with its `extracted.entity_alias`
rows — idempotently (entity_id is a deterministic hash, so re-runs update in place). The `layerb`
role/service runs it on a timer. The target tables already exist in the schema; `migrate` creates them.

**One documented limitation:** blocker 3 (embedding neighbours — the only CROSS-script matcher) needs
a served embedder, which VPS-B does not yet have. Until then Layer B does SAME-script canonicalisation
(the large majority of merges) and never guesses across scripts — a Chinese and an English name stay
two entities, the honest outcome without embeddings. Wiring an embedder is the remaining extension.

## Files added / changed this pass
- `worklist.json` — l2_processing_list flattened, P1-first (21,875 docs).
- `select_worklist.py` — selection logic: worklist → queue by lane (idempotent). `--demo` passes.
- `layer_b_pg.py` — Layer B on Postgres: spans → canonical entity/entity_alias. `--demo` passes.
- `engine/route.py` — `C_NODE_MAX_CLASS` override so P1–P7 lanes are claimable.
- `../llmapi/server.py` — `/v1/chat/completions` OpenAI shim so the engine's LLM routes through the router.
- `entrypoint.sh` — `health_gate`, `select` role, worklist step in `feed_once`.
- `.env.example` — router-routing config, health-gate knobs, worklist + Layer B knobs.
