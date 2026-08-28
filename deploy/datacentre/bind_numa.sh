#!/bin/sh
# Bind the extraction containers' MEMORY to the socket their cores are on.
#
#   ./bind_numa.sh          # after every `docker compose up` that recreates them
#
# WHY THIS IS A SCRIPT AND NOT A LINE IN THE COMPOSE FILE
# -------------------------------------------------------
# The Compose spec has `cpuset` but no `cpuset_mems`, so there is no way to say
# this declaratively. `docker update --cpuset-mems` does it, and it is lost when
# a container is recreated -- hence a script you re-run, and a note in the
# README rather than a setting that silently reverts.
#
# WHAT IT IS WORTH
# ----------------
# The box is two sockets: NUMA node 0 = cores 0-19, node 1 = cores 20-39. The
# extraction stack lives entirely on node 1 (model 20-26, workers 27-33), but
# without this its memory can be allocated on node 0, so every weight read
# crosses the socket interconnect. Token generation is almost pure memory
# traffic, so that hurts more than it sounds.
#
# Measured 2026-08-26, qwen2.5:7b, 6 threads, quiet box:
#     unbound   3.98 tok/s
#     bound     8.05 tok/s
#
# And the honest other half: under a running crawl it buys NOTHING (1.33 -> 1.20,
# i.e. nothing outside noise), because then the bottleneck is contention for
# memory bandwidth and L3 across the whole machine, which no cpuset or memory
# binding can partition. Collect this gain on a quiet box; do not expect it on a
# busy one.
set -eu

NODE="${KSSL_NUMA_NODE:-1}"

for c in kssl-extract-ollama kssl-autopilot kssl-bench; do
    if docker inspect "$c" >/dev/null 2>&1; then
        docker update --cpuset-mems "$NODE" "$c" >/dev/null
        printf '%-24s mems=%s cpus=%s\n' "$c" \
            "$(docker inspect -f '{{.HostConfig.CpusetMems}}' "$c")" \
            "$(docker inspect -f '{{.HostConfig.CpusetCpus}}' "$c")"
    else
        printf '%-24s not present\n' "$c"
    fi
done

# A container already holding pages on the wrong node keeps them: the binding
# applies to future allocations. Restart the model so it reloads its weights
# where they belong -- the workers allocate per document, so they do not need it.
if [ "${1:-}" = "--restart-model" ]; then
    docker restart kssl-extract-ollama >/dev/null
    echo "kssl-extract-ollama restarted so its weights land on node $NODE"
fi
