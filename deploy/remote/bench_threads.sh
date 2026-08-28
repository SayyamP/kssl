#!/bin/sh
# Does matching the thread count to the CPU cap recover the loss?
#
# The core-scaling run came out superlinear (2 -> 8 cores was 4x the cores and
# 7x the throughput), which no compute-bound workload does. The likely cause is
# that ollama sizes its thread pool from the HOST's core count and ignores the
# container quota, so a capped container spends its slice context-switching.
# If that is right, pinning num_thread to the cap should beat the default at
# the same cap. If it is wrong, the two columns come out equal and the cap is
# simply expensive.
set -e
B=/opt/kssl/bench
LOG="$B/threads.log"
: > "$LOG"

for c in 3 4; do
    docker rm -f kssl-llm-bench >/dev/null 2>&1 || true
    docker run -d --name kssl-llm-bench --cpus "$c" --memory 14g \
        -e OLLAMA_MODELS=/models -e OLLAMA_NUM_PARALLEL=1 \
        -e OLLAMA_MAX_LOADED_MODELS=1 -e OLLAMA_CONTEXT_LENGTH=8192 \
        -p 127.0.0.1:11434:11434 -v /opt/kssl/models:/models \
        ollama/ollama:latest >/dev/null
    for i in $(seq 1 40); do
        curl -sf -m 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
        sleep 2
    done
    echo "=== ${c} cores, threads=default ===" >> "$LOG"
    python3 "$B/bench_cpu_llm.py" --models qwen2.5:7b-instruct --runs 3 \
        --label "${c}c default threads" --out "$B/th_${c}_def.json" >> "$LOG" 2>&1
    echo "=== ${c} cores, threads=${c} ===" >> "$LOG"
    python3 "$B/bench_cpu_llm.py" --models qwen2.5:7b-instruct --runs 3 --threads "$c" \
        --label "${c}c pinned threads" --out "$B/th_${c}_pin.json" >> "$LOG" 2>&1
done
echo "=== ALLDONE ===" >> "$LOG"
