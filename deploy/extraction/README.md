# Running Layer A/B extraction at the data centre

Extraction is the expensive stage and it belongs on the 40-core box, not on the
8-core VPS. This directory is what puts it there.

## Before you run a large batch: check who owns the cores

This is the single thing that decides whether extraction takes an hour or a day.

The box is *documented* as: crawler `0-19`, L2 `20-29`, SFL `30-34`, OS and
shared `35-39`. Measured on 2026-08-25, that is not what is running:

```
$ docker inspect -f '{{.Name}} {{.HostConfig.CpusetCpus}}' $(docker ps -q)
/mallory-crawler-crawler-api-1     0-34      <-- spills across the L2 lane
/mallory-crawler-crawler-api-2-1   0-34
...  (all twelve)
/kssl-extract-ollama               20-29
```

and the corpus Postgres sits on `35-39`. With a news crawl running, the box was
at load 87 of 40 cores and the extraction model measured **1.06 tok/s** — against
**11.4 tok/s** on a four-core VPS. That is contention, not hardware.

So, one of:

* **Pin the crawlers back to their lane** — `docker update --cpuset-cpus 0-19`
  on each `crawler-api` container. This is live and needs no restart, so the
  durable frontier survives. **But test it first:** the crawler's own
  concurrency governor reads *host* CPU rather than its cgroup, so confining it
  to 20 cores while it targets 90% of 40 may make it oversubscribe its own lane.
  Caps on this box have been lethal before.
* **Or run extraction against a quiet fleet** — after a batch finishes, or with
  the fleet in maintenance mode.

Do not read 1.06 tok/s as the machine's capability, and do not size a batch from
it.

## Install

```bash
docker compose -f docker-compose.extract.yml build      # ~10 min, mostly torch
```

The image pins `gliner==0.2.13` and `transformers==4.45.2` together. They are a
matched pair: gliner 0.2.13 requires transformers <4.46, and the engine's
`check.py` fails the run on a mismatch. The older
`l2/comprehend/deploy/Dockerfile` installs gliner unpinned and produces an image
that builds cleanly and then refuses to work.

torch comes from the CPU index deliberately. GLiNER's `from_pretrained` defaults
to `map_location="cpu"` and the engine never selects a device, so **GLiNER runs
on CPU even on the GPU workstation** — moving it here costs nothing. The
warnings in `extraction-stack/requirements.txt` and `setup.ps1` that a CPU wheel
"costs 30x on every GLiNER pass" are contradicted by the code; ignore them.

The GLiNER weights (~1.2 GB) are baked into the image rather than fetched on
first run, so a cold start cannot fail on a Hugging Face outage.

## The models it calls

Extraction does not hold an LLM itself — it reaches one over HTTP:

| Env | Default | What it is |
|---|---|---|
| `C_MODEL` | `qwen2.5:7b` | the comprehension pass. **This is the wall clock.** |
| `C_EMBED` | `nomic-embed-text:latest` | population + ontology-tree vectors |
| `C_GLINER` | `urchade/gliner_multi-v2.1` | high-recall span finder, CPU, in-process |
| `OLLAMA_URL` | `http://host.docker.internal:11500` | the centre's own Ollama |

`kssl-extract-ollama` is already running on the centre with both models pulled.

`C_THREADS` defaults to 10 here. The engine hardcodes 24, which oversubscribes a
shared lane. And pinning the *model's* thread count to its core budget is worth
roughly a factor of two on a capped container — measured on the VPS, 4 cores:
6.0 tok/s default vs 11.4 tok/s pinned.

## Run

```bash
# 1. new documents out of the corpus and into the queue
python pipeline/pull_corpus.py --since 2026-08-25 --limit 200

# 2. Layer A then Layer B
python pipeline/run_extraction.py --limit 200 --workers 4

# 3. into Postgres
python pipeline/load_extracted.py
```

Each of those records itself in `metrics.stage_run`, so afterwards:

```sql
SELECT * FROM metrics.stage_summary ORDER BY ord;
SELECT * FROM metrics.doc_journey ORDER BY end_to_end_s DESC LIMIT 20;
```

`--workers` above 4 measured no gain in an earlier A/B, and GLiNER is serialised
across workers by a single lock, so it becomes the bottleneck rather than the
model.

## Where the results go

`KSSL_DSN` points at the **VPS** database through the SSH tunnel:

```bash
ssh -N -L 5460:127.0.0.1:5460 root@<vps>
export KSSL_DSN="host=127.0.0.1 port=5460 dbname=kssl user=postgres password=..."
```

so the VPS database port never leaves the VPS, and the serving layer sees the
new rows without extraction ever touching the web tier.
