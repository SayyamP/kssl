# The data centre's half of the deployment

Extraction runs here. The database, the card-writing model, the API and the
dashboard run on the VPS. Nothing runs on a workstation — that was a temporary
arrangement while the centre was saturated, and it is over.

```
   corpus (here)  ->  Layer A/B (here)  ->  VPS database  ->  VPS model  ->  UI
   1.2M docs          gliner + qwen7b       kssl-db          qwen14b        /
```

## Bring it up

```bash
cd /home/sysadmin/kssl/dc
cp dc.env.example dc.env && chmod 600 dc.env   # fill in the two passwords
docker compose -f docker-compose.dc.yml --env-file dc.env up -d --build

# the extraction model lives in its own container, started separately; it has to
# join this stack's network or the workers cannot resolve it
docker network connect kssl-dc kssl-extract-ollama
```

Three containers come up:

| container | what it does |
|---|---|
| `kssl-tunnel` | one ssh session to the VPS, two forwards, no published port |
| `kssl-autopilot` | the loop: new corpus documents → cards, every 30 min |
| `kssl-bench` | the worker behind the dashboard's "paste an article" page |

All three are `restart: unless-stopped`, which is the whole supervision story:
the box has no passwordless sudo, so there is no systemd unit to write, and
Docker starts on boot.

## The three network paths, and why each is what it is

**To the VPS — through a container, not the host.** `kssl-tunnel` holds
`ssh -N -g -L 0.0.0.0:5460:… -L 0.0.0.0:11500:…`. Because the forwards are bound
inside a container that publishes no port, they are reachable by the other
containers as `kssl-tunnel:5460` / `kssl-tunnel:11500` and by nothing else. The
`-g` is not optional: without it `-L` binds loopback only, and a container
arriving on the bridge interface is refused with no log line anywhere.

**To the corpus — by container name on its own network.** Not
`172.17.0.1:5432`. `~/mallory-firewall.sh` DROPs the corpus ports in the
`DOCKER-USER` chain, container traffic traverses that chain too, and the failure
is a silent hang. Joining `mallory-data_default` and addressing
`mallory-data-postgres-1:5432` never touches the host interface, so the rule
keeping the corpus off the internet stays intact. Do not "fix" this by opening
the firewall.

**To the extraction model — a container on the same network.**
`kssl-extract-ollama` was started outside this stack, on the default bridge,
where there is no name resolution. `docker network connect kssl-dc` gives it a
name here. If a worker reports `Name or service not known` for
`kssl-extract-ollama`, that connect is what is missing.

## Two models, deliberately on two machines

| stage | model | where | why there |
|---|---|---|---|
| Layer A comprehension | `qwen2.5:7b` | this box, `kssl-extract-ollama` | it is the wall clock, and the cores are here |
| GLiNER span finder | `gliner_multi-v2.1` | this box, in-process, CPU | it runs on CPU even on a GPU box — the engine never selects a device |
| signal cards | `qwen2.5:14b-instruct` | the VPS, `kssl-llm` | it serves the dashboard; it stays on the machine that serves it |

`KSSL_LLM_THREADS=4` pins the VPS model's thread count to its container's cpu
cap. Ollama sizes its pool from the *host* core count and ignores the cgroup, so
without this it oversubscribes a 4-core cap and thrashes — measured, 6.0 → 11.4
tok/s.

`KSSL_LLM_CPU=1` raises the call timeout to 900 s. Neither machine has a GPU; at
180 s a card that would have been written instead times out, and the pipeline
used to report that as *the card gate refused it* — a crash dressed as an
editorial decision.

## Cores

The box is divided `crawler 0-19 / extraction model 20-26 / extraction workers
27-33 / lab LLMs 34 / data stores 35-39`, no lane shared. Note that this is also
the NUMA split: node 0 is cores 0-19, node 1 is 20-39, so the whole extraction
stack sits on one socket. Run `./bind_numa.sh` after any recreate to put its
memory there too.

Do **not** convert `cpuset` to a `cpus:` quota. A CFS quota inflates latency,
fires the engine's watchdog, and the crawler's own concurrency governors read
*host* CPU rather than their cgroup. Caps on this box have been lethal before.

Check who actually owns the cores before blaming the hardware:

```bash
docker inspect -f '{{.Name}} {{.HostConfig.CpusetCpus}}' $(docker ps -q) | sort
```

A note on a number this file used to carry: it said 1.06 tok/s under contention
"against 11.4 on a quiet lane". **That 11.4 was the VPS, not a quiet lane here** —
the comparison put two machines side by side and read it as one machine's before
and after. Measured properly (next section), a quiet lane on this box gives 8.05,
and the exclusive-lane division on its own gave 1.33. Cores were never the thing.


## What actually limits extraction speed here (measured 2026-08-26)

Same box, same model (`qwen2.5:7b`), same 6 threads. Every row is a real
measurement, not an estimate:

| crawler | memory binding | tok/s |
|---|---|---|
| running | unbound | 1.33 |
| running | bound to the local socket | 1.20 |
| maintenance mode | unbound | 3.98 |
| **maintenance mode** | **bound to the local socket** | **8.05** |
| *(the VPS, EPYC 9354P, 4 threads, for scale)* | | *12.74* |

Three things follow, and the first one cost a whole evening to learn:

1. **The crawler costs 6.7x, and it is not a fight over cores.** Dividing the
   cores into exclusive lanes -- which is what `docker-compose.dc.yml` does, and
   which is worth doing for other reasons -- changed the number by nothing
   (1.06 before the division, 1.33 after). The contention is for **memory
   bandwidth and L3**, and a `cpuset` cannot partition either. Any plan that
   starts "give extraction more cores" is answering the wrong question.
2. **NUMA binding is worth 2x, but only on a quiet box.** `bind_numa.sh` puts
   the containers' memory on the socket their cores are on; 3.98 -> 8.05 idle,
   and 1.33 -> 1.20 (i.e. nothing) while crawling. Free, worth having, not a
   fix on its own.
3. **The hardware gap is the small part.** A quiet, properly-bound data centre
   does 8.05 against the VPS's 12.74. That 1.6x is the chip -- DDR4 Ice Lake at
   2.0 GHz against DDR5 Zen 4 at 3.25 GHz -- and it is not what makes extraction
   slow here.

**The lever that works is time, not resources:** run the crawl and the
extraction in turns rather than together. `POST /api/crawler/fleet/maintenance?on=true`
stops the fleet and holds off refill; `on=false` resumes it (measured: 21 saved
jobs restored, nothing lost). At 8 tok/s an article takes ~6 minutes instead of
~40.

## Reading the timings

Every stage writes `metrics.stage_run` on the VPS with `host='datacentre'`, so
where a number was measured is recorded rather than inferred:

```sql
SELECT * FROM metrics.stage_summary ORDER BY ord;
SELECT * FROM metrics.doc_journey ORDER BY end_to_end_s DESC LIMIT 20;
SELECT * FROM metrics.adhoc_summary ORDER BY submitted DESC LIMIT 10;
```

## When something is wrong

```bash
docker compose -f docker-compose.dc.yml --env-file dc.env logs -f autopilot
docker exec kssl-tunnel nc -z 127.0.0.1 5460 && echo "db forward alive"
docker exec kssl-autopilot python -c \
  "import os,psycopg2;psycopg2.connect(os.environ['KSSL_DSN'],connect_timeout=5);print('vps db ok')"
```

A restarting worker is almost always the tunnel: the healthcheck tests both
forwards, because `ExitOnForwardFailure` only catches a failure at setup — a
forward that dies later leaves the ssh session happily alive.
