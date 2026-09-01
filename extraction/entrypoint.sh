#!/usr/bin/env bash
# One image, several roles. `docker compose` (or systemd) picks the role via the first argument.
# Every role is a long-running process so the container's own restart policy is the supervisor.
#
#   worker     drain the queue forever: claim -> extract (farm) -> store, back off when empty
#   feeder     every FEED_EVERY_S: sync new corpus docs -> enqueue (presignal gate) -> reap leases
#   migrate    apply the SQL schema (documents, extracted.*, serving.*) then exit
#   cards      every CARDS_EVERY_S: build serving cards from what has been extracted (UI; optional)
#   once       run one feed+drain cycle and exit (smoke test / cron)
set -euo pipefail

ENGINE="$(cd "$(dirname "$0")/engine" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PYTHONUNBUFFERED=1
# The engine resolves ds.json / source_tiers by these overrides, so the tree can live anywhere.
export C_DS_JSON="${C_DS_JSON:-$ENGINE/ds.json}"
export C_TIERS_PATH="${C_TIERS_PATH:-$ENGINE/source_tiers.py}"

NODE="${KSSL_NODE:-farm}"                 # farm-scale capacity; the worker calls the farm API
FEED_EVERY_S="${FEED_EVERY_S:-600}"       # 10 min: sync + enqueue + reap
CARDS_EVERY_S="${CARDS_EVERY_S:-900}"
SYNC_SINCE_DAYS="${KSSL_SINCE_DAYS:-3}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# Health gate: the orchestrator must confirm the compute backends (vps-a + farm, behind the router)
# are alive before it sends any document for processing. Blocks until KSSL_MIN_HEALTHY_NODES are up.
health_gate() {
  local url="${KSSL_HEALTH_URL:-}"; local need="${KSSL_MIN_HEALTHY_NODES:-1}"
  [ -z "$url" ] && { log "no KSSL_HEALTH_URL set -- skipping health gate"; return 0; }
  while true; do
    # /v1/nodes live-probes each backend; count how many report up:true.
    up=$(curl -fsS -m 8 "$url" 2>/dev/null | grep -o '"up": *true' | wc -l | tr -d ' ')
    if [ "${up:-0}" -ge "$need" ]; then
      log "health gate OK: $up backend(s) up (need $need)"; return 0
    fi
    log "health gate: only ${up:-0} backend(s) up (need $need) -- holding 15s"
    sleep 15
  done
}

feed_once() {
  # 1. SELECTION: prime the queue from the l2_processing_list worklist, in P1..P7 lane order.
  #    This pulls the listed bodies from the corpus and enqueues them by lane (class = lane).
  log "select: worklist (P1..P7) -> queue"
  python3 "$HERE/select_worklist.py" --limit "${KSSL_WORKLIST_LIMIT:-2000}" \
          --max-lane "${KSSL_MAX_LANE:-7}" || log "select failed (continuing)"
  # 2. Also top up from freshly crawled dated docs (the crawler-freshness lane), idempotently.
  log "sync: corpus -> VPS-B documents"
  python3 "$HERE/sync_documents.py" --limit "${KSSL_SYNC_LIMIT:-500}" || log "sync failed (continuing)"
  log "enqueue: documents -> queue (presignal gate)"
  ( cd "$ENGINE" && python3 route.py --enqueue ) || log "enqueue failed (continuing)"
  log "reap: release expired leases"
  ( cd "$ENGINE" && python3 route.py --reap ) || log "reap failed (continuing)"
}

case "${1:-worker}" in
  migrate)
    log "applying schema to KSSL_CORPUS_DSN"
    for f in "$HERE"/db/*.sql; do
      log "  psql -f $(basename "$f")"
      psql "${KSSL_CORPUS_DSN:?set KSSL_CORPUS_DSN}" -v ON_ERROR_STOP=1 -f "$f"
    done
    log "schema applied."
    ;;
  worker)
    health_gate                       # do not claim a doc until a compute backend is proven up
    log "worker starting: run_node --node $NODE (queue -> extract via router:vps-a+farm -> store)"
    cd "$ENGINE"
    exec python3 run_node.py --node "$NODE"
    ;;
  feeder)
    health_gate
    log "feeder starting: cycle every ${FEED_EVERY_S}s"
    while true; do feed_once; sleep "$FEED_EVERY_S"; done
    ;;
  select)
    log "select: priming the queue from the worklist, then exit"
    python3 "$HERE/select_worklist.py" --limit "${KSSL_WORKLIST_LIMIT:-2000}" \
            --max-lane "${KSSL_MAX_LANE:-7}"
    ;;
  layerb)
    log "layerb starting: canonicalise entities every ${LAYERB_EVERY_S:-3600}s (Layer B on Postgres)"
    while true; do
      python3 "$HERE/layer_b_pg.py" || log "layer B failed (continuing)"
      sleep "${LAYERB_EVERY_S:-3600}"
    done
    ;;
  cards)
    log "cards starting: build every ${CARDS_EVERY_S}s"
    cd "$ENGINE"
    # serving.card must exist before --build joins it; --init is idempotent
    # (CREATE TABLE IF NOT EXISTS), so run it every cycle rather than assume a
    # separate migrate step created it.
    while true; do
      python3 card_writer.py --init --build || log "card build failed (continuing)"
      sleep "$CARDS_EVERY_S"
    done
    ;;
  signals)
    # Turn extracted docs into UI feed cards (serving.signal_card/detail) via the
    # signal-generation LLM. The model runs on VPS-A (OLLAMA_URL points at the reverse
    # tunnel 127.0.0.1:11500); this loop reads the local extracted.* and writes serving.*.
    log "signals starting: fill serving cards every ${SIGNALS_EVERY_S:-600}s via ${OLLAMA_URL:-VPS-A}"
    cd "$HERE/signals"
    while true; do
      python3 serving_fill.py --limit "${KSSL_SIGNALS_LIMIT:-300}" || log "signal fill failed (continuing)"
      sleep "${SIGNALS_EVERY_S:-600}"
    done
    ;;
  enrich)
    # Fill the REMAINING serving tables (competitors, matchup, geo, innovation, patent,
    # partner, tender, sources) from extracted.* via the enrichment LLM -- same farm-primary
    # client as signals. Full idempotent rebuild each pass: deletes only origin='pipeline'
    # (never 'reference'/demo) then re-inserts from the current corpus, so the tables sharpen
    # as extraction grows. Heavier than signals, so a slow timer.
    log "enrich starting: rebuild serving tables every ${ENRICH_EVERY_S:-7200}s via ${OLLAMA_URL:-farm}"
    cd "$HERE/signals"
    while true; do
      python3 enrich_serving.py || log "enrich pass failed (continuing)"
      sleep "${ENRICH_EVERY_S:-7200}"
    done
    ;;
  once)
    feed_once
    log "one-shot drain (limited): run_node --node $NODE --limit ${KSSL_ONCE_LIMIT:-20}"
    cd "$ENGINE" && python3 run_node.py --node "$NODE" || true
    ;;
  *)
    echo "unknown role: $1 (worker|feeder|select|layerb|cards|migrate|once)" >&2
    exit 2
    ;;
esac
