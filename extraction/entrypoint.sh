#!/usr/bin/env bash
# One image, several roles. `docker compose` (or systemd) picks the role via the first argument.
# Every role is a long-running process so the container's own restart policy is the supervisor.
#
#   worker     drain the queue forever: claim -> extract (farm) -> store, back off when empty
#   feeder     every FEED_EVERY_S: sync new corpus docs -> enqueue (presignal gate) -> reap
#              leases -> backfill `ready` from gate-refused rows so no worker idles
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

# A STEP THAT FAILS EVERY CYCLE IS INVISIBLE. Fifteen steps in this file end in
# `|| log "... (continuing)"`, which is right -- one broken step must not stop the
# others -- but it means a step that has failed for a week prints exactly the same
# single line as one that hiccupped once, there is no healthcheck on any service in
# docker-compose.yml, and nothing alerts. This repository already records three
# outcomes of that: fill_competitor_news was wired to nothing and the four news panels
# "sat empty from the first rebuild until someone ran it by hand"; mark_shared was
# wired to nothing and "not one of 42 ties carried cid", so the red line was dead
# across the whole tab; and the retranslate window re-asked the same 200 cards every
# cycle for hours, burning farm time and reaching nothing else.
#
# This does not change what happens on failure -- the loop still continues. It counts
# CONSECUTIVE failures per step and escalates to a greppable [ALERT] once a step has
# missed KSSL_STEP_ALERT_AFTER cycles in a row, and says so again when it recovers.
# A hiccup stays one line; a step that is actually broken gets louder every pass.
STEP_STATE="${KSSL_STEP_STATE:-/tmp/kssl-steps}"
mkdir -p "$STEP_STATE" 2>/dev/null || true

step() {
  local name="$1"; shift
  local f="$STEP_STATE/$name" n=0
  if "$@"; then
    n=$(cat "$f" 2>/dev/null || echo 0)
    [ "${n:-0}" -gt 0 ] 2>/dev/null && \
      log "[RECOVERED] $name succeeded after $n consecutive failure(s)"
    echo 0 > "$f" 2>/dev/null || true
    return 0
  fi
  n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$f" 2>/dev/null || true
  if [ "$n" -ge "${KSSL_STEP_ALERT_AFTER:-3}" ]; then
    log "[ALERT] $name has now failed $n cycles in a row and is writing NOTHING."
    log "[ALERT] This is not a hiccup. Check its output above; a step that fails every"
    log "[ALERT] pass usually means a renamed model alias, a missing column, or a"
    log "[ALERT] credential that expired -- none of which stop the other steps."
  else
    log "$name failed (continuing) -- $n consecutive failure(s)"
  fi
  return 0
}

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
  step select python3 "$HERE/select_worklist.py" --limit "${KSSL_WORKLIST_LIMIT:-2000}" \
          --max-lane "${KSSL_MAX_LANE:-7}"
  # 2. Also top up from freshly crawled dated docs (the crawler-freshness lane), idempotently.
  log "sync: corpus -> VPS-B documents"
  step sync python3 "$HERE/sync_documents.py" --limit "${KSSL_SYNC_LIMIT:-500}"
  log "enqueue: documents -> queue (presignal gate)"
  step enqueue sh -c 'cd "$0" && python3 route.py --enqueue' "$ENGINE"
  log "reap: release expired leases"
  step reap sh -c 'cd "$0" && python3 route.py --reap' "$ENGINE"
  # 3. BACKFILL last, so it sees the queue exactly as the workers will: only what nothing else
  #    filled. Measured live -- ready 0, deferred/gate 51,994, 198 workers in backoff -- an idle
  #    fleet beside a 98%-full queue. This tops `ready` back up to KSSL_READY_FLOOR from the rows
  #    the presignal gate refused, best-scoring first, and does nothing at all while real work
  #    exists. See route.backfill(); class is untouched, so fresh work still claims first.
  backfill_once
  # 4. GAPS LAST. Which published column is empty on which competitor, and which corpus
  #    documents would answer it -- queued at P1, because a document fetched BECAUSE a
  #    column is blank outranks the next crawl batch. It rate-limits itself per field
  #    (a corpus scan has no text index to lean on), so on the cycles where it declines
  #    to run it costs one SELECT.
  #
  #    This is the step that stops "the Competitor tab is missing X" being a ticket.
  #    Revenue, founding year and leadership were each noticed by a human, grepped by
  #    hand, queued by hand and only then filled -- four manual steps, per field, that
  #    only began when somebody complained. See backfill_gaps.py.
  log "gaps: empty serving columns -> corpus search -> queue"
  step gaps python3 "$HERE/backfill_gaps.py" --apply
}

backfill_once() {
  log "backfill: keep the fleet fed when the gate has left nothing ready"
  step backfill sh -c 'cd "$0" && C_BACKFILL_FLOOR="$1" python3 route.py --backfill' \
       "$ENGINE" "${KSSL_READY_FLOOR:-400}"
}

case "${1:-worker}" in
  migrate)
    # Base schema (db/00..06) once, then any pending migration (db/migrations/), each
    # applied a single time and recorded. Before this ledger existed, migrations were
    # hand-applied over ssh and the checked-in schema drifted eleven columns and a
    # whole table behind the database it claimed to describe.
    DSN="${KSSL_CORPUS_DSN:?set KSSL_CORPUS_DSN}"
    psql "$DSN" -v ON_ERROR_STOP=1 -q -c "CREATE TABLE IF NOT EXISTS schema_version (
        filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"

    # An empty database gets the base files. They are plain CREATE TABLE, not
    # CREATE TABLE IF NOT EXISTS, so this runs exactly once in a database's life --
    # which is what makes `migrate` safe to point at production.
    if [ "$(psql "$DSN" -Atc "SELECT to_regclass('serving.competitors') IS NULL")" = "t" ]; then
      log "empty database: applying base schema"
      for f in "$HERE"/db/[0-9][0-9]_*.sql; do
        log "  apply $(basename "$f")"
        psql "$DSN" -v ON_ERROR_STOP=1 -q -f "$f"
      done
    fi

    # Bootstrap, once. Everything on disk right now already describes this database:
    # the base files because they were either just applied or built it before this
    # ledger existed, and the migrations because each one's effect is folded back into
    # those base files in the same commit that adds it. Record all of it WITHOUT
    # replaying it. Replaying is what would break -- the base schema already carries
    # the ui_config UNIQUE that 2026-09-02_competitor_news_writer.sql adds, and a
    # second ADD CONSTRAINT is an error, not a no-op.
    if [ "$(psql "$DSN" -Atc "SELECT NOT EXISTS (SELECT 1 FROM schema_version)")" = "t" ]; then
      log "recording the schema on disk as this database's starting point"
      for f in "$HERE"/db/[0-9][0-9]_*.sql "$HERE"/db/migrations/*.sql; do
        [ -e "$f" ] || continue
        psql "$DSN" -q -c "INSERT INTO schema_version(filename)
                           VALUES ('$(basename "$f")') ON CONFLICT DO NOTHING"
      done
    fi

    for f in "$HERE"/db/migrations/*.sql; do
      [ -e "$f" ] || continue               # an empty migrations/ leaves the glob literal
      n="$(basename "$f")"
      if [ "$(psql "$DSN" -Atc "SELECT 1 FROM schema_version WHERE filename = '$n'")" = "1" ]; then
        continue
      fi
      log "  apply $n"
      # -1 puts the file AND its ledger row in one transaction, so a migration that
      # fails half way leaves neither the change nor a record claiming it was applied.
      psql "$DSN" -v ON_ERROR_STOP=1 -1 -f "$f" \
        -c "INSERT INTO schema_version(filename) VALUES ('$n')"
    done
    log "schema up to date."
    ;;
  worker)
    health_gate                       # do not claim a doc until a compute backend is proven up
    log "worker starting: run_node --node $NODE (queue -> extract via router:vps-a+farm -> store)"
    cd "$ENGINE"
    exec python3 run_node.py --node "$NODE"
    ;;
  feeder)
    health_gate
    log "feeder starting: feed every ${FEED_EVERY_S}s, backfill every ${BACKFILL_EVERY_S:-120}s"
    while true; do
      feed_once
      # Poll the backfill BETWEEN feed cycles as well. feed_once is heavy -- a worklist select, a
      # corpus sync and a full enqueue pass -- so it cannot run often; but 198 workers can empty
      # `ready` in a couple of minutes, and every minute after that is the whole farm in backoff.
      # Above the floor a backfill is a single COUNT, so this poll costs nothing when all is well.
      _until=$(( $(date +%s) + FEED_EVERY_S ))
      while [ "$(date +%s)" -lt "$_until" ]; do
        sleep "${BACKFILL_EVERY_S:-120}"
        backfill_once
      done
    done
    ;;
  select)
    log "select: priming the queue from the worklist, then exit"
    python3 "$HERE/select_worklist.py" --limit "${KSSL_WORKLIST_LIMIT:-2000}" \
            --max-lane "${KSSL_MAX_LANE:-7}"
    ;;
  layerb)
    log "layerb starting: canonicalise entities every ${LAYERB_EVERY_S:-3600}s (Layer B on Postgres)"
    while true; do
      step layer-b python3 "$HERE/layer_b_pg.py"
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
      step card-build python3 card_writer.py --init --build
      sleep "$CARDS_EVERY_S"
    done
    ;;
  signals)
    # Turn extracted docs into UI feed cards (serving.signal_card/detail) via the
    # signal-generation LLM. The model runs on VPS-A (OLLAMA_URL points at the reverse
    # tunnel 127.0.0.1:11500); this loop reads the local extracted.* and writes serving.*.
    # SIZED FROM THE MEASURED YIELD, not from a round number. Per 300-document pass one replica
    # saw: ~212 already claimed by a sibling, ~70 dated too old, ~5 undated, ~5 off-portfolio,
    # ~4 listing pages -- leaving roughly 13 documents that actually reach the model. Three
    # replicas at 600s therefore issued ~4 model calls a minute, and the 6-slot serving node sat
    # at 0/6 with 94 requests served all day. It was starved, not broken.
    #
    # 1,000 per pass keeps a replica working through its whole cycle instead of finishing early
    # and sleeping, and a 120s timer means the gap between passes is short next to the work. The
    # loop overrunning its own timer is FINE and in fact the point: the sleep is a floor on how
    # often an empty corpus is re-scanned, not a schedule.
    log "signals starting: fill serving cards every ${SIGNALS_EVERY_S:-120}s via ${OLLAMA_URL:-VPS-A}"
    cd "$HERE/signals"
    while true; do
      # THE GATE MUST REACH THE CARDS ALREADY SERVED. serving_fill is append-only (a document
      # is claimed once, its card never revisited), so the subject gate tightened on
      # 2026-09-05 changed nothing on the dashboard: the ~230 cards it refuses had all been
      # written 09-01..09-04 and were still served -- "Leonardo wins 15 helicopter order"
      # under UAVs, "Thales wins U.S. Marine Corps order for Minerva cameras" under vehicles,
      # 23 of them wearing a THREAT badge. Re-judging the served rows each pass is what makes
      # a gate change (this one and every later one) show up. REPORT-ONLY by default: the
      # log lists what would go; KSSL_REGATE_APPLY=1 is the operator's decision to delete.
      if [ "${KSSL_REGATE_APPLY:-0}" = "1" ]; then
        step regate python3 serving_fill.py --regate --apply
      else
        step regate-report python3 serving_fill.py --regate
      fi
      step signal-fill python3 serving_fill.py --limit "${KSSL_SIGNALS_LIMIT:-1000}"
      # AND THE SAME PROBLEM THE REGATE ABOVE SOLVES, FOR LANGUAGE. fill() only visits
      # documents with no card, so the English lead-ins it now writes reach tomorrow's
      # cards and none of the 311 already served off a non-English source. This rebuilds
      # those in place. It costs one model call per non-English card and nothing at all
      # for an English one -- measured on staging, 186 of 210 statements never reach the
      # model -- so it is cheap to run every cycle and is what keeps the tab in English
      # as the corpus grows.
      step retranslate python3 serving_fill.py --retranslate --apply \
              --limit "${KSSL_RETRANSLATE_LIMIT:-200}"
      sleep "${SIGNALS_EVERY_S:-120}"
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
      step enrich-pass python3 enrich_serving.py
      # AND REFILL THE NEWS, IN THE SAME CYCLE THAT EMPTIES IT.
      # serving.competitor_news.comp_id is `REFERENCES serving.competitors(comp_id) ON
      # DELETE CASCADE`, and the pass above deletes and rebuilds every origin='pipeline'
      # competitor -- so each pass silently takes the whole news table with it. This
      # script is its only writer and was wired to nothing, so the four news panels on
      # the dashboard sat empty from the first rebuild until someone ran it by hand.
      # Measured on production 2026-09-04: 123 rows before a pass, 0 after.
      #
      # It reads serving.signal_card, which the `signals` role writes, so it needs no
      # model call and costs seconds. Failure is logged and the loop continues: an empty
      # news panel is bad, an enrich loop that stops rebuilding everything else is worse.
      log "news: refill serving.competitor_news (cascaded away by the rebuild above)"
      step news-fill python3 fill_competitor_news.py --apply
      # AND RE-STAMP THE OVERLAP, FOR THE SAME REASON THE NEWS NEEDS REFILLING.
      # The rebuild above rewrites every origin='pipeline' partners array from the
      # corpus, and the corpus does not know which of a rival's partners are also
      # KSSL's -- that join lives only here. It was wired to nothing at all, so on
      # staging 2026-09-06 not one of 42 ties carried `cid`: the red line was dead
      # across the whole tab, and eight real overlaps (Rafael, Elbit, DRDO, Saab)
      # drew as unshared. No model call, reads serving.partner, costs seconds.
      log "overlap: re-stamp shared partners (the red line) after the rebuild"
      step overlap-marking python3 mark_shared.py --apply
      # And read back the status the older ties state in their own words. The rows
      # written before step_partnerships existed carry no `status`, so the graph drew
      # "Historical Joint Venture (Ended 2013)" as a live edge. Idempotent -- it never
      # touches a tie that already has one -- so it only ever reaches rows nothing
      # else has typed, including any added by hand after this.
      log "status: type the ties no model wrote"
      step status-backfill python3 backfill_tie_status.py --apply
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
