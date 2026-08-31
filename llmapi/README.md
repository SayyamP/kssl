# llmapi — every model call, one door

Runs on **VPS-B**. The pipeline never dials a model server; it calls this.

```
pipeline/*.py  ──llmapi/client.py──▶  llmapi/server.py  ──▶  vps-b Ollama (local)
                    (stdlib)              (FastAPI)      └─▶  farm  (OpenAI-shaped, Bearer)
                                                          ✗   vps-a, dc — not reachable from here
```

## Why

Four modules each carried their own `urllib.request.urlopen(OLLAMA + "/api/generate")`, and
three carried their own copy of `llm_opts`. One model server made that survivable. There are
four, they are not interchangeable, and **two of them cannot be reached from this box**.

## Run

```bash
python llmapi/nodes.py  --status      # what is configured, what answers
python llmapi/client.py --ping        # is the API up
uvicorn llmapi.server:app --host 127.0.0.1 --port 8610
```

Deployed, it is the `llmapi` service in `docker-compose.vps.yml`.

## Use

```python
from llmapi.client import ask, gliner

text          = ask("summarise this", npredict=300)
text, meta    = ask("...", with_meta=True)          # meta.node, meta.eval_count, meta.tok_s
results       = gliner(["sentence one", "sentence two"])
```

## Routing — the same decision `route.py` makes, one level down

`route.py` asks *"which document can this node finish inside its budget?"*. This asks
*"which node can finish this call inside its budget?"* Same fleet, same constants, same
shape of decision — two routers on one fleet that disagree about what a node can do is how
a queue and its workers drift apart.

**Copied deliberately:**

- capacity comes from a **time budget** and a **measured tok/s**, never a hand-set share
- **strict first, relaxed only if nothing fits** — `FALLBACK_MULTIPLE = 3.0`, route.py's value
- **health before dispatch**, cached, bad results re-checked sooner (`SVC_TTL_BAD < SVC_TTL_OK`)
- a node that cannot take this call is **demoted, never removed** — route.py: *parking is
  terminal, so it must mean "impossible", never "nobody is up right now"*

**Deliberately not copied:** the `class` ladder. Freshness and trust tier are properties of
a *document waiting in a queue*; a model call has already been admitted — route.py decided
that. Re-deciding priority here would be a second admission control behind the first.

Four tiers, ordered fastest-first inside each (route.py's `order="short"`):

```
0  fits its budget, healthy, free
1  fits, healthy, at its concurrency cap
2  fits only under the relaxed budget      (route.py's fallback_cap)
3  cooling after repeated failures          last resort, never removed
```

What that produces, with all four nodes live:

```
npredict=80    (verdict)   farm → vps-b → vps-a → dc      all four fit
npredict=300   (card)      farm → vps-b → vps-a → dc      all four fit
npredict=13212 (dense)     farm → vps-b → vps-a → dc      only farm+vps-b fit; rest relaxed
farm cooling               vps-b → vps-a → dc → farm
```

The farm leads when healthy — it is 72% of fleet capacity — and the DC picks up small calls
it can honestly finish while being demoted for large ones. **Nobody maintains a percentage.**

### The farm is fast and unreliable, so it gets a breaker

`route.py` records it *"often not alive 2-3 hours straight"*. Fastest-first would hand a
dead farm most of the calls, each burning its full read timeout before falling through —
throughput would drop *further with* the fast node than without it. So `LLM_BREAK_AFTER`
consecutive transport failures (default 3) stop it leading for `LLM_COOLDOWN_S` (default
120s). One success restores it. It is never removed.

### Concurrency is a property of the server, not a knob

`OLLAMA_NUM_PARALLEL=1` on vps-b and the DC — they serve **one** request at a time and
everything else sits in `OLLAMA_MAX_QUEUE`. The farm was measured at N=12. So
`*_MAX_INFLIGHT` defaults to 1 and 12 respectively, and a saturated node yields its turn.

## GLiNER runs on every node

It used to be one of two bad options: an in-process torch model inside **every** extraction
worker (~2 GB each, capacity invisible to any router), or the farm — the node measured as
*"often not alive 2-3 hours straight"*. One unreliable remote or N copies of a local model
is not a choice worth having.

Now each box runs `llmapi/gliner_server` and the router treats it exactly like a model
server — same budget, health, concurrency cap and circuit breaker:

```
vps-b   gliner:8620                (local container)
vps-a   tunnel-vpsa:11512          second forward on its existing ssh session
dc      tunnel-dc:11513            second forward on its existing ssh session
farm    ollama.i3softlab.com/extract
```

**Nothing depends on the farm.** It is one entry in `GLINER_NODE_ORDER`, not the only one.

Three things this gets right:

- **The wire contract is the farm's**, not a new one: `{"text": [...], "labels", "threshold"}`
  → `{"results": [[...]]}`. So a local node and the farm are interchangeable in one chain,
  and `comprehend.py`'s existing `_gliner_remote` parses either unchanged.
- **Breakers are keyed per service** (`vps-b` vs `vps-b:gliner`). Ollama being down says
  nothing about whether GLiNER answers; a shared counter would pull a healthy service out
  of rotation for its neighbour's outage.
- **A short results list is refused.** The caller zips the reply against its own sentence
  list *by position*, so a missing entry would shift every later span into the wrong
  sentence — silently, and straight past the offset contract.

One number here is **unmeasured**: `*_GLINER_CPS` (characters/second) sizes the GLiNER
budget and picks the fastest eligible node. 20,000 is a conservative placeholder. This
project's own rule applies — `unrated` is not a bad score, it means nobody has assessed it.
Measure it per node before trusting the routing to prefer one box over another for NER.

## The three rules it enforces

**1. An address is relative to the caller.** `127.0.0.1:11434` is correct for vps-a's Ollama
*on vps-a*; from vps-b it is vps-b's own Ollama and the call silently succeeds against the
wrong machine. Every `*_URL` is declared as "the address as seen from `LLM_ORIGIN`", and a
node whose URL is another host's loopback is a **startup error**, not a runtime mystery.

**2. Failover is for transport, never for content.** A refused connection, a timeout or a 5xx
is retried elsewhere. An empty completion or a model refusal is **not** — that is an answer,
and re-asking a second model until one says something is how a pipeline invents facts.

**3. A down API raises.** It never falls back to a direct Ollama call. That "helpful"
fallback would resurrect the exact problem this module exists to prevent, at the one moment
nobody is watching, and hide it because output still appears.

## Endpoints

| | |
|---|---|
| `POST /v1/generate` | `{prompt, npredict?, model?, format?, node?}` → `{response, node, eval_count, tok_s, ...}` |
| `POST /v1/gliner` | `{texts: [...], labels?, threshold?}` → `{results: [[...]], node}` |
| `GET /v1/nodes` | per-node config + live probe |
| `GET /v1/budget?npredict=` | worst-case seconds across the whole failover chain |
| `GET /healthz` | 200 when a call can be served, **503** with `problems[]` when not |

`/healthz` re-evaluates the config **per request**, never the value captured at boot: cached,
a config an operator had fixed would report unhealthy until someone restarted, and one that
rotted after boot would report healthy forever.

Bad input is `400` with a reason; an upstream that will not answer is `502`. Neither is ever
an uncaught `500`.

`/v1/gliner` returns offsets **relative to each input string**, exactly as upstream does.
The caller shifts them into document coordinates and slices span text from the document, so
`document.text[start:end] == span.text` stays a property of one place instead of two.

## Config

All of it in `.env`, under `LLM / GLiNER API`. The load order is: real environment wins over
`.env` (compose and the shell are more specific than a file on disk).

| | |
|---|---|
| `LLM_ORIGIN` | which host this runs on — refuses a config that cannot work here |
| `LLM_NODE_ORDER` | preference order; first reachable+healthy node wins, rest are failover |
| `<NODE>_URL` | address **as seen from `LLM_ORIGIN`**. Blank ⇒ disabled, never guessed |
| `<NODE>_TOK_S` | that node's measured rate — drives the derived read timeout |
| `<NODE>_THREADS` | must equal the serving container's cpu cap |

## What is deliberately not here

- **`bench_models.py` still dials Ollama directly.** It compares models on one endpoint; a
  benchmark that silently failed over to a second node would measure the router, not the model.

- **`/v1/gliner` has no caller in this repo yet, and that is a real gap — not a finished
  criterion.** The only GLiNER consumer is Layer A extraction inside the external
  `l2/comprehend` engine, which `pipeline/run_extraction.py` invokes as a subprocess at
  `ENGINE = ../../l2/comprehend` — outside this repository. Every LLM and GLiNER call
  *originating in this repo* now goes through the API; the extraction engine's own calls do
  not, and cannot until that engine is changed to call this endpoint. Do not read the
  endpoint's existence as the traffic having moved.
- **vps-a and dc are disabled.** vps-a's Ollama is on its own loopback with no routable
  address from here; the DC's is a private docker address, and routing serving-side work
  through the slowest node in the fleet (1.5 tok/s measured) is the opposite of the goal.
  Give either a reachable URL and flip `*_ENABLED=1` to bring it in — no code change.
- **No local GLiNER.** It would need torch (~2 GB) on the box whose cores are the constraint.
