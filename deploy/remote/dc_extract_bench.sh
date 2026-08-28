#!/bin/sh
# Pull the models the EXTRACTION engine uses, and measure them on the data
# centre's CPUs.
#
# comprehend.py calls qwen2.5:7b for the comprehension pass and
# nomic-embed-text for the population vectors. Those two, on 10 pinned cores
# with no GPU, are what set the extraction stage's wall clock -- so they are
# what gets measured, not a stand-in.
set -e
B=/home/sysadmin/kssl/bench
mkdir -p "$B"
LOG="$B/dc_bench.log"
: > "$LOG"

for m in qwen2.5:7b nomic-embed-text:latest; do
    echo "=== pulling $m" >> "$LOG"
    docker exec kssl-extract-ollama ollama pull "$m" >> "$LOG" 2>&1
    echo "=== DONE $m rc=$?" >> "$LOG"
done

OLLAMA_URL=http://127.0.0.1:11500 OLLAMA_CONTAINER=kssl-extract-ollama \
    python3 "$B/bench_cpu_llm.py" \
    --models qwen2.5:7b --runs 3 \
    --label "datacentre 10 cores (cpuset 20-29)" \
    --out "$B/llm_dc_10core.json" >> "$LOG" 2>&1

echo "=== ALLDONE ===" >> "$LOG"
