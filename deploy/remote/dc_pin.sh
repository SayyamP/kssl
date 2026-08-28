#!/bin/sh
B=/home/sysadmin/kssl/bench
cd "$B" || exit 1
OLLAMA_URL=http://127.0.0.1:11500 OLLAMA_CONTAINER=kssl-extract-ollama \
python3 "$B/bench_cpu_llm.py" --models qwen2.5:7b --runs 3 --threads 10 \
  --label "dc 20-29 pinned, crawl running" \
  --out "$B/llm_dc_pin.json" > "$B/dc_pin.log" 2>&1
echo DONE >> "$B/dc_pin.log"
