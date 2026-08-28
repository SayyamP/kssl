#!/bin/sh
# Pull the candidate models for the CPU benchmark. Run detached: this is
# ~16 GB and must outlive the SSH session that starts it.
LOG=/opt/kssl/bench/pull.log
mkdir -p /opt/kssl/bench
: > "$LOG"
for m in qwen3:4b qwen2.5:7b-instruct qwen2.5:14b-instruct; do
    echo "=== pulling $m at $(date -Is)" >> "$LOG"
    docker exec kssl-llm-bench ollama pull "$m" >> "$LOG" 2>&1
    echo "=== DONE $m rc=$? at $(date -Is)" >> "$LOG"
done
echo "=== ALLDONE $(date -Is)" >> "$LOG"
