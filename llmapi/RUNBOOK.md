# Final run test — code here, models on vps-a / vps-b / DC

Your workstation runs `llmapi` and the pipeline. **No model runs here.** Ollama and GLiNER
both live on the three boxes; this machine reaches all six services through local ssh
forwards.

```
  THIS MAC                              vps-b            vps-a            DC
  llmapi + pipeline
    :11501 ──ssh -L──▶ ollama :11434
    :11511 ──ssh -L──▶ gliner :8620
    :11502 ─────────────────────────────ssh -L──▶ ollama :11434
    :11512 ─────────────────────────────ssh -L──▶ gliner :8620
    :11503 ────────────────────────────────────────────────ssh -L──▶ 172.24.0.2:11434
    :11513 ────────────────────────────────────────────────ssh -L──▶ gliner :8620
```

The farm is **disabled** (`FARM_ENABLED=0`). It is the fastest node and the least reliable,
and nothing in this run depends on it.

---

## 1. Fill the seven blanks in `.env`

```bash
VPSB_SSH_HOST=   VPSB_SSH_KEY=      # path on THIS machine
VPSA_SSH_HOST=   VPSA_SSH_KEY=
                 DC_SSH_KEY=        # host/user/port already filled: 103.126.197.150:45632 sysadmin
```

Confirm the config is coherent before touching any box:

```bash
python3 llmapi/nodes.py            # "problems": [] and origin "local"
```

## 2. Install GLiNER on each box

One command per node. It copies `llmapi/gliner_server/`, builds there, runs it on that
box's `127.0.0.1:8620`, and waits for the model to actually load.

```bash
./llmapi/install_gliner_remote.sh vps-b --dry-run   # prints what it would do
./llmapi/install_gliner_remote.sh vps-b
./llmapi/install_gliner_remote.sh vps-a
./llmapi/install_gliner_remote.sh dc
```

**First run per box downloads ~1 GB of weights and CPU torch — several minutes.** The
weights go in a named volume, so a rebuild never re-downloads them. The script exits
non-zero and prints the container log if `/healthz` has not gone green in 10 minutes.

> The DC is a shared machine. Run its install when you are ready for it, not as part of a
> batch — and check the cores first if anything else is mid-run.

## 3. Open the tunnels

```bash
./llmapi/tunnels_local.sh          # leave this window open
```

It opens one ssh session per box carrying both that box's services, then **probes each
forward** — an ssh process being alive proves nothing. In another shell:

```bash
./llmapi/tunnels_local.sh --check
```

Six `OK` lines is the goal. A `DOWN` on a gliner port usually means that box's model is
still loading; `--check` again in a minute.

## 4. Start the API and verify the fleet

```bash
PYTHONPATH=. python3 -m uvicorn llmapi.server:app --host 127.0.0.1 --port 8610
```

```bash
curl -s localhost:8610/healthz | python3 -m json.tool
curl -s localhost:8610/v1/nodes | python3 -m json.tool
```

`/v1/nodes` probes every node live and reports what each is actually serving. A node that
is up but lacks `qwen2.5:7b` says so by name — that is the check that matters, because an
Ollama with nothing pulled answers instantly and then fails or spends ~150s loading on the
first real request.

## 5. One real call through each service

```bash
# generation -- routed to whichever node fits the budget and is healthy
curl -s -X POST localhost:8610/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Reply with the single word: ready","npredict":10}' | python3 -m json.tool

# NER -- same routing, its own budget and breaker
curl -s -X POST localhost:8610/v1/gliner \
  -H 'Content-Type: application/json' \
  -d '{"texts":["Cubic Corporation won a $4.5 million contract in March 2026."]}' | python3 -m json.tool
```

Both replies name the `node` that served them and list anything `tried` and failed on the
way. Pin a specific box to test it alone:

```bash
curl -s -X POST localhost:8610/v1/generate -H 'Content-Type: application/json' \
  -d '{"prompt":"ready?","npredict":10,"node":"dc"}'
```

## 6. Run the pipeline

```bash
python3 pipeline/serving_fill.py --limit 2
```

It calls the API like everything else — no model server address anywhere in it.

---

## What to expect, and what would be wrong

| | |
|---|---|
| `/healthz` **503** | config cannot serve — the body names which node and why |
| a generate **502** | every node failed; the `detail` lists each attempt |
| a node **missing from `/v1/nodes` order** | its `*_ENABLED=0` or its `*_URL` is blank |
| **the same node always answering** | correct — fastest-eligible-first, not round robin |
| **the DC leading** | only for calls the faster nodes cannot fit; at 1.5 tok/s it should be last most of the time |

## Two numbers that are not measured yet

- **`*_GLINER_CPS = 20000`** for all three. It sizes the GLiNER budget and picks the fastest
  eligible node. Until you measure it per box, ordering falls back to configured order —
  failover and the breaker still work, only the *preference* is uninformed.
- **`VPSA_TOK_S = 8.3`** is inferred from the 59.5% steal you observed, not measured
  directly. If steal has changed, this is wrong in whichever direction it moved.

`/v1/generate` returns the real `tok_s` for every call. A few calls per box pinned with
`"node"` gives you both numbers honestly.

## Stopping

```bash
./llmapi/tunnels_local.sh --stop
ssh <box> 'docker stop kssl-gliner'      # per box, if you want the service down too
```
