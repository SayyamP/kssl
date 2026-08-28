#!/bin/sh
# How much does the signal LLM actually gain from another core?
#
# The partition question is "how many of the 8 cores does the LLM get", and the
# honest answer depends on whether core 5 and 6 buy anything. Restart the same
# model under different hard caps and measure. Nothing else is guessed from.
set -e
BENCH=/opt/kssl/bench
MODEL="${MODEL:-qwen2.5:7b-instruct}"
OUT="$BENCH/cores.log"
: > "$OUT"

for c in 2 3 4 6 8; do
    echo "=== ${c} cores ===" >> "$OUT"
    docker rm -f kssl-llm-bench >/dev/null 2>&1 || true
    docker run -d --name kssl-llm-bench \
        --cpus "$c" --memory 14g \
        -e OLLAMA_MODELS=/models -e OLLAMA_NUM_PARALLEL=1 \
        -e OLLAMA_MAX_LOADED_MODELS=1 -e OLLAMA_CONTEXT_LENGTH=8192 \
        -e OLLAMA_KEEP_ALIVE=30m \
        -p 127.0.0.1:11434:11434 \
        -v /opt/kssl/models:/models \
        ollama/ollama:latest >/dev/null
    # wait for the API rather than sleeping a guessed amount
    for i in $(seq 1 40); do
        if curl -sf -m 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then break; fi
        sleep 2
    done
    python3 "$BENCH/bench_cpu_llm.py" --models "$MODEL" --runs 3 \
        --label "${c} cores" --out "$BENCH/cores_${c}.json" >> "$OUT" 2>&1
done
echo "=== ALLDONE ===" >> "$OUT"
