"""Keep the three extraction workers alive, honest, and unstuck.

WHY THIS EXISTS
---------------
The queue already had every mechanism it needed and ran none of them. route.REAP returns an
expired lease to `ready` (and parks it after 3 attempts), lease_ttl already derives the deadline
-- but nothing ever executed the reap, so expired leases simply accumulated: 4 of them sat dead
for hours while the queue reported work in progress.

Worse, a lease expiring does not stop the WORKER. The dc worker spent two hours on one document
whose lease had long since expired and been re-claimed elsewhere: it held a CPU, produced nothing,
and by the time it finished, the result belonged to nobody. A lease is a claim on the DOCUMENT.
Nothing was ever a claim on the PROCESS.

So this supervisor watches both halves:

  * the QUEUE  -- reap expired leases every cycle, the thing that was already written
  * the WORKER -- if a node holds one document past a hard deadline, kill the process, put the
                  document back on the queue, and start a fresh worker on the next one

It runs on the DC HOST, not inside a worker: it needs `docker` to see and restart containers.
It talks to Postgres through the existing postgres container via psql, so it adds no dependency
to the host python -- there is no psycopg there and this is not worth installing one for.
"""
import json
import os
import subprocess
import sys
import time

PG = "mallory-data-postgres-1"
# -q matters more than it looks. Without it psql prints the command tag ("UPDATE 0") even under
# -tA, and an UPDATE ... RETURNING therefore yields one line that is not a row. Parsing that as a
# row raised ValueError on EVERY cycle, at the first statement in cycle(), so the supervisor never
# reached the code that restarts workers -- it looked alive and supervised nothing.
PSQL = ["docker", "exec", "-i", PG, "psql", "-q", "-U", "mallory", "-d", "mallory", "-tAF|",
        "-v", "ON_ERROR_STOP=1"]
WORKDIR = "/kssl/engine/l2/comprehend"
LOG = "/tmp/worker.log"

# tok_s is each node's MEASURED generation rate -- it sets C_TOK_S for the worker, which sizes the
# read timeout. minutes is the node's own budget from route.NODES.
# tok_s is the MEASURED rate; it sets C_TOK_S on the worker and sizes the stuck deadline. Every
# OTHER number here is imported from route.py rather than copied.
#
# It used to be copied, and the copies had already drifted: dc 7.79 here vs 8.765 there, vps-b
# 11.95 vs 3.815. The supervisor reconstructs when a lease was claimed as
# `lease_until - ttl`, and that is what it kills a worker on -- so a stale constant here does not
# produce a wrong number on a dashboard, it kills healthy workers and spares wedged ones.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route as _route                                                          # noqa: E402

ALPHA = _route.ALPHA
# vps-a is capped at 4 of its 8 cores, deliberately, and this is NOT a performance tuning knob.
# 187.127.134.12 is a SHARED box: it also runs tesseract OCR, batch_ocr_worker.py and
# intel_backfill.py, and it triggered a Hostinger CPU-limit alert on 2026-08-28. Measured at that
# moment: our qwen2.5:7b runner alone held 510% CPU -- 5.1 of 8 cores -- against a load average of
# 6.0-7.1. We were the single largest consumer on a machine at its limit. 4 threads caps our share
# at roughly half that and leaves the box's own jobs room to run. Raising it needs a look at that
# host's load first, not just at our throughput.
#
# threads = the cores that node's MODEL SERVER is granted, sent as num_thread on every generate
# call. It MUST equal the cpuset size: llama.cpp counts the HOST's cores from sysfs and ignores
# the cgroup, so a mismatch silently oversubscribes and every barrier becomes a context-switch
# storm. That exact fault has been found three times on this infrastructure and cost 44x on the
# dc. dc=10 matches its cpuset 20-29 (raised from 7 on 2026-08-28); the vps figures describe the
# REMOTE machines' cores, not this box's, and move independently of anything done here.
NODES = {
    "dc":    dict(container="kssl-worker-dc",   tok_s=7.79,   threads=10),
    "vps-a": dict(container="kssl-worker-vpsa", tok_s=15.385, threads=4),
    "vps-b": dict(container="kssl-worker-vpsb", tok_s=11.95,  threads=4),
}
for _n, _c in NODES.items():
    _c["minutes"] = _route.NODES[_n]["minutes"]
    _c["duty"] = _route.DUTY[_n]
    _c["route_tok_s"] = _route.NODES[_n]["tok_s"]     # the rate the LEASE was actually sized with
    # SAFETY DIRECTION, not a single source of truth. These two tables mean different things --
    # route's is the planning rate that sizes caps, supervise's is the measured rate -- and they
    # will disagree again. What must never happen is the disagreement pointing the DANGEROUS way.
    #
    # The two errors are not symmetric. A PESSIMISTIC deadline on a fast node costs only that a
    # genuinely wedged document lives an extra half hour before being killed: bounded, cheap. An
    # OPTIMISTIC deadline on a slow node kills healthy work mid-extraction, charges the document
    # an attempt, and walks it to MAX_ATTEMPTS -- unbounded corpus damage, recorded as a park
    # whose stated reason is a lie.
    #
    # This exact failure was live for minutes: route's dc was corrected 8.765 -> 1.5 from a
    # measurement while this table kept 7.79, giving a 31-minute kill deadline against a 54-minute
    # honest completion time. Every document the dc could claim would have been killed while
    # working correctly. Taking the slower of the two makes the deadline and the read-timeout
    # trust whichever number is more cautious, without trusting either as truth.
    _c["tok_s"] = min(_c["tok_s"], _c["route_tok_s"])


def granted_ttl(node, chars):
    """The lease route.CLAIM granted for a document of this size on this node.

    Every constant comes from route, none is written twice. The previous version inlined
    `2 * chars * rate + 120` and went stale the moment route's factor and floor changed -- held-for
    times went NEGATIVE, which at least failed loudly. A subtler drift would not have: this is the
    number the supervisor kills workers on."""
    return max(_route.TTL_FLOOR_S,
               _route.TTL_FACTOR * chars * ALPHA / max(0.01, NODES[node]["route_tok_s"]) + 120)

# The lease TTL is NOT usable as the stuck deadline. It is sized from the node's CAP -- the dc's
# is 172 minutes because its cap is 9,274 chars -- so a worker wedged on a 3,350-char document
# that should take 31 minutes stays "within its lease" for nearly three hours. The deadline has
# to come from the document in hand, not from the largest one the node would ever accept.
STUCK_FACTOR = 3.0      # a slow document is not a broken one; 3x expected is generous
STUCK_FLOOR_S = 1800    # ...but never fire before half an hour, whatever the arithmetic says
ORPHAN_GRACE_S = 900    # slack on top of the longest legitimate rest
CYCLE_S = 60

# The crawler fills `documents` continuously; nothing moved those rows into extract_queue. There
# was no cron entry, no systemd unit and no container doing it -- the queue was a one-shot
# snapshot from a hand-run command, and 4,643 crawled documents had never been enqueued while
# 5,499 arrived in a single day. The head of the pipeline was simply not connected to the rest
# of it, and nothing reported that, because every metric measured the queue rather than the flow.
ENQUEUE_EVERY_S = 900
# 4h quiet ~= 30 missed documents at one per 8 minutes: worth paging for, and far beyond any
# legitimate duty rest or backoff. Do not tighten it until the false-positive sources above are
# gone -- a threshold tuned on an alarm that still cries wolf just moves the noise.
QUIET_ALARM_S = 4 * 3600
_last_enqueue = [0.0]


def run_enqueue(dry=False):
    """Pull newly crawled documents into the queue. Idempotent: ENQUEUE is ON CONFLICT DO NOTHING
    and _mark only re-stamps rows still in a pre-dispatch state, so an overlapping window cannot
    walk a finished document backwards."""
    rows = sql("SELECT coalesce(max(crawl_ts), '2026-08-01') FROM extract_queue;", cols=1)
    since = (rows[0][0] if rows else "2026-08-01")[:10]
    if dry:
        print("  would enqueue since %s" % since, flush=True)
        return False
    # DETACHED (-d), not waited on. Enqueue scans a 1.3M-row corpus and its runtime grows with
    # the corpus; any fixed timeout is a deadline that will eventually be missed. It was capped at
    # 120s so a slow enqueue could not stall reaping and stuck-detection -- correct concern, wrong
    # remedy: the cap simply started failing every cycle once the corpus outgrew it, and reaping
    # was blocked for the full 120s each time anyway. Detaching removes the coupling entirely, so
    # the cycle never waits and enqueue takes as long as it takes.
    #
    # Safe to fire and forget: enqueue is idempotent (ON CONFLICT DO NOTHING, and _mark only
    # re-stamps pre-dispatch rows), and a second copy overlapping the first cannot corrupt the
    # queue. `pgrep -f` keeps that from happening anyway.
    # Bracket trick: `[r]oute.py` cannot match the pgrep pattern's OWN cmdline (which literally
    # contains "route.py --enqueue"), so the guard no longer reports BUSY against its own shell.
    # Without it enqueue was skipped on EVERY cycle -- the queue silently never got fed.
    rc, out, _ = sh(["docker", "exec", NODES["dc"]["container"], "sh", "-c",
                     "pgrep -f '[r]oute.py --enqueue' >/dev/null && echo BUSY || echo FREE"],
                    timeout=30)
    if "BUSY" in (out or ""):
        print("  enqueue since %s: previous run still going, skipping this cycle" % since,
              flush=True)
        return False
    rc, _, err = sh(["docker", "exec", "-d", NODES["dc"]["container"], "sh", "-c",
                     "cd %s && python3 route.py --enqueue --since %s >> /tmp/enqueue.log 2>&1"
                     % (WORKDIR, since)], timeout=30)
    print("  enqueue since %s: %s" % (since, "launched" if rc == 0 else "FAILED %s" % err[:120]),
          flush=True)
    return True


def est_seconds(chars, tok_s):
    return chars * ALPHA / max(0.01, tok_s)


def stuck_deadline(chars, tok_s):
    return max(STUCK_FLOOR_S, STUCK_FACTOR * est_seconds(chars, tok_s))


def orphan_deadline(node):
    """How long a worker may hold NO lease before we call it orphaned.

    Holding no lease is normal -- that is what resting looks like, and the rest is deliberate
    back-pressure. But it is ALSO what a worker looks like after its document was reaped out from
    under it: it keeps generating against a lease that is gone, and whatever it produces will be
    rejected by the epoch fence. From outside, the two are identical except in duration.

    So the bound is the longest legitimate rest -- budget x (1/duty - 1) -- plus a grace. vps-b at
    50% duty may genuinely rest a full 22 minutes; the dc at 90% may rest nine. One flat number
    would either kill vps-b mid-rest or let the dc idle for half an hour, which is what it did."""
    n = NODES[node]
    rest_max = n["minutes"] * 60 * (1.0 / max(0.01, n["duty"]) - 1.0)
    return rest_max + ORPHAN_GRACE_S


def sh(cmd, inp=None, timeout=60):
    r = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sql(q, cols=None):
    """Rows as lists of strings. `cols` asserts the shape: any line that does not have exactly
    that many fields is dropped, so a stray command tag or notice can never be mistaken for data.
    Belt as well as braces -- -q already suppresses the tag, but a psql that ever prints anything
    else here should degrade to "no rows", not to a crash that silently disables the supervisor."""
    rc, out, err = sh(PSQL, inp=q)
    if rc != 0:
        raise RuntimeError("psql: %s" % (err or out)[:300])
    rows = [line.split("|") for line in out.splitlines() if line]
    if cols is not None:
        rows = [r for r in rows if len(r) == cols]
    return rows


UNKNOWN = "unknown"          # distinct from None: None means "definitely no process"


def worker_pid(container):
    """Host PID of the run_node process in this container, or None."""
    rc, out, _ = sh(["docker", "top", container, "-eo", "pid,args"])
    if rc != 0:
        # "I could not look" is NOT "nothing is there". Under load on this shared box `docker top`
        # returns non-zero and empty, and treating that as absence makes the supervisor requeue a
        # live worker's document (voiding its commit) and start a SECOND worker in the container.
        # That is the six-workers incident, automated. A human made this exact misreading today
        # from the same empty output.
        return UNKNOWN
    for line in out.splitlines()[1:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        # Match the PYTHON process, not the `sh -c` that launched it -- that wrapper carries the
        # same "run_node.py" text in its own command line. Counting it doubled every reading, and
        # trusting it would report a healthy worker whose python had died under a surviving shell.
        if "run_node.py" in parts[1] and parts[1].lstrip().startswith("python"):
            return int(parts[0])
    return None


def log_age_s(container):
    """Seconds since the worker last printed anything. run_node runs under `python3 -u`, so this
    is real evidence of progress and not a buffering artefact."""
    rc, out, _ = sh(["docker", "exec", container, "stat", "-c", "%Y", LOG])
    out = out.strip()
    if rc != 0 or not out.isdigit():
        return None
    return int(time.time()) - int(out)


def start_worker(node):
    n = NODES[node]
    cmd = ("cd %s && C_TOK_S=%s C_LLM_THREADS=%s python3 -u run_node.py --node %s "
           "--db /tmp/local.db >> %s 2>&1" % (WORKDIR, n["tok_s"], n["threads"], node, LOG))
    rc, _, err = sh(["docker", "exec", "-d", n["container"], "sh", "-c", cmd])
    return rc == 0, err


def stop_worker(node):
    """SIGTERM then SIGKILL, matched on the command line -- never on a remembered PID, which may
    have been recycled by the time we act on it."""
    n = NODES[node]
    py = (
        "import os,signal,time\n"
        "def hits():\n"
        "    out=[]\n"
        "    for p in os.listdir('/proc'):\n"
        "        if not p.isdigit(): continue\n"
        "        try: cl=open('/proc/%s/cmdline'%p,'rb').read().decode('utf8','replace')\n"
        "        except Exception: continue\n"
        "        if 'run_node' + '.py' in cl: out.append(int(p))\n"
        "    return out\n"
        "me=os.getpid()\n"
        "h=[p for p in hits() if p!=me]\n"
        "for p in h:\n"
        "    try: os.kill(p,signal.SIGTERM)\n"
        "    except Exception: pass\n"
        "time.sleep(5)\n"
        "for p in [q for q in hits() if q!=me]:\n"
        "    try: os.kill(p,signal.SIGKILL)\n"
        "    except Exception: pass\n"
        "print(len(h))\n")
    rc, out, err = sh(["docker", "exec", "-i", n["container"], "python3", "-"], inp=py)
    return out.strip() or "0"


def requeue(doc_id, why, epoch=None, charge=False):
    """Put a cancelled document back -- FENCED on the state and epoch we observed.

    Unfenced, this could overwrite a COMMITTED result. stop_worker() sleeps 5s between SIGTERM
    and SIGKILL, and in that window the worker can finish: its DONE_SQL takes the row lock, the
    supervisor's UPDATE blocks, the worker commits `done`, the UPDATE unblocks, re-reads the new
    row under READ COMMITTED, finds `document_id` still matching -- and flips a finished document
    back to `ready`. It is then extracted a second time under a second run_id, and because the
    span PK includes run_id the two span sets coexist with nothing to say which is authoritative.
    The state and epoch predicates make that window harmless: after a real commit, neither holds."""
    pred = "state='leased'" + ("" if epoch is None else " AND lease_epoch=%d" % epoch)
    # charge=False refunds the claim's attempt; charge=True keeps it. See route.MAX_ATTEMPTS for
    # the rule: refund only when NO extraction was attempted (worker down, orphan, deploy). A
    # stuck-kill is the strongest evidence there is AGAINST a document -- refunding that one makes
    # park unreachable and lets one wedging document consume a node forever.
    # PARK, don't just ready: a charged requeue that reaches MAX_ATTEMPTS must park, or a
    # deterministically-wedging document sits at state='ready' forever -- excluded from CLAIM
    # (attempts >= MAX) yet counted as healthy backlog, a queue that lies about itself.
    rows = sql("UPDATE extract_queue SET "
               "state = CASE WHEN greatest(0, attempts - %d) >= %d THEN 'parked' ELSE 'ready' END, "
               "reason=%s, leased_by=NULL, lease_until=NULL, "
               "lease_epoch=lease_epoch+1, attempts=greatest(0, attempts - %d) "
               "WHERE document_id='%s' AND %s RETURNING document_id, state;"
               % (0 if charge else 1, _route.MAX_ATTEMPTS, "'" + why.replace("'", "''") + "'",
                  0 if charge else 1, doc_id.replace("'", "''"), pred), cols=2)
    if rows:
        print("      requeued %s (%s)" % (doc_id, why), flush=True)
    else:
        print("      NOT requeued %s -- it finished or was re-claimed first (%s)" % (doc_id, why),
              flush=True)


def held_by(node):
    """(document_id, chars, seconds_held) for this node's live lease, or None.

    seconds_held is reconstructed as now() - (lease_until - ttl_s) rather than tracked in memory,
    so a supervisor restart does not reset every worker's clock to zero -- which would make a hung
    worker immortal as long as the supervisor was flapping."""
    rows = sql("SELECT document_id, chars, EXTRACT(EPOCH FROM (now()-lease_until))::int, "
               "lease_epoch FROM extract_queue WHERE state='leased' AND leased_by='%s' "
               "ORDER BY lease_until DESC LIMIT 1;" % node, cols=4)
    if not rows:
        return None
    doc, chars, past_expiry, epoch = rows[0][0], int(rows[0][1] or 0), int(rows[0][2] or 0), \
        int(rows[0][3] or 0)
    # held = (now - lease_until) + ttl, i.e. how long ago the claim happened. Computing the TTL
    # here from the SAME expression the claim used keeps the two in step by construction.
    held = past_expiry + granted_ttl(node, chars)
    return doc, chars, int(held), epoch


def all_held_by(node):
    """EVERY lease this node holds, not just the newest.

    A worker that dies without releasing leaves its lease behind, and the next worker takes a
    second one -- so a node can hold several at once. held_by()'s LIMIT 1 sees only the newest,
    so the orphan is never stuck-checked and simply waits out its lease, burning an attempt and
    eventually being parked for a failure that was the supervisor's to clean up."""
    return [(r[0], int(r[1] or 0)) for r in
            sql("SELECT document_id, lease_epoch FROM extract_queue "
                "WHERE state='leased' AND leased_by='%s';" % node, cols=2)]


def build_cards(dry=False):
    """Project new extractions into serving.card so the UI has something to read.

    Runs INLINE, unlike enqueue, and that difference is deliberate. Enqueue scans a 1.3M-row
    corpus and its runtime grows without bound, so any fixed timeout eventually starts failing --
    it had to be detached. Card building is incremental: it only touches documents that have no
    card yet, which at ~100 documents/day is a handful per cycle and seconds of work. Inline keeps
    the failure visible instead of silently detaching into a log nobody reads."""
    if dry:
        print("  would build cards", flush=True)
        return 0
    rc, out, err = sh(["docker", "exec", NODES["dc"]["container"], "sh", "-c",
                       "cd %s && python3 card_writer.py --dsn \"$KSSL_CORPUS_DSN\" --build"
                       % WORKDIR], timeout=180)
    line = [x for x in (out or "").splitlines() if "built" in x]
    n = 0
    if line:
        try:
            n = int(line[-1].split()[1])
        except (IndexError, ValueError):
            n = 0
        if n:
            print("  %s" % line[-1].strip(), flush=True)
    elif rc != 0:
        print("  card build FAILED: %s" % (err or out or "?")[:160], flush=True)
    if n:
        refresh_ui_store()
    return n


UI_DATA_DIR = "/home/sysadmin/mallory-l2dash/data"
UI_STORE = "live_postgres.db"


def refresh_ui_store():
    """Hand the dashboard a SQLite file in the shape it already reads.

    The dashboard has no database connection and its /api/stores auto-discovers any *.db in its
    data directory, so this is how Postgres reaches the UI without touching a container that is
    not ours. Copied to a temp name and moved into place, because the dashboard may open the file
    at any moment and half a database is worse than an old one.

    ponytail: a full rebuild each time. At ~100 documents/day that is seconds; past a few thousand
    documents it wants an incremental export keyed on first_seen."""
    tmp = "/tmp/%s.new" % UI_STORE
    rc, _, err = sh(["docker", "exec", NODES["dc"]["container"], "sh", "-c",
                     "cd %s && python3 card_writer.py --dsn \"$KSSL_CORPUS_DSN\" "
                     "--export-sqlite /tmp/%s" % (WORKDIR, UI_STORE)], timeout=300)
    if rc != 0:
        print("  UI export FAILED: %s" % (err or "?")[:140], flush=True)
        return False
    for cmd in (["docker", "cp", "%s:/tmp/%s" % (NODES["dc"]["container"], UI_STORE), tmp],
                ["mv", tmp, "%s/%s" % (UI_DATA_DIR, UI_STORE)]):
        rc, _, err = sh(cmd, timeout=120)
        if rc != 0:
            print("  UI refresh FAILED: %s" % (err or "?")[:140], flush=True)
            return False
    print("  UI store refreshed (%s/%s)" % (UI_DATA_DIR, UI_STORE), flush=True)
    return True


def demote_stale(dry=False):
    """Fresh-first decays into oldest-first once arrivals outrun capacity.

    class is computed from age at ENQUEUE and then frozen, while the claim orders by
    (class, crawl_ts). At 50x oversubscription the P0/P1 lanes grow faster than they drain, so
    the head of the queue becomes permanently week-old work labelled `fresh`, and today's crawl
    waits behind all of it -- the exact opposite of the promise the class system exists to keep."""
    if dry:
        return 0
    # crawl_ts is TEXT, so this is a STRING comparison standing in for a time comparison. It is
    # exact only because every value is 20-char ISO-8601 UTC ending in Z (verified: all 1,305,875
    # corpus rows) -- and only if the formatted cutoff is UTC too. timezone('UTC', now()) makes
    # that explicit rather than depending on the session's TimeZone setting, which is UTC today
    # and would silently shift this window by hours if anyone changed it.
    rows = sql("UPDATE extract_queue SET class=3 WHERE state='ready' AND class < 3 "
               "AND crawl_ts < to_char(timezone('UTC', now()) - interval '24 hours', "
               "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') RETURNING document_id;", cols=1)
    if rows:
        print("  demoted %d stale ready row(s) to P3" % len(rows), flush=True)
    return len(rows)


def alarms():
    """The run-time counterpart of the preflight. Deploy-time is defended; this is not.

    Every incident in this system's history was found by a human reading a log: done-marks with no
    rows, six workers writing to the wrong store, four store failures discarding finished
    documents. All of them are visible in these two questions, and neither was ever asked."""
    out = []
    # STRUCTURAL: under the atomic commit a done row without a document row is impossible. Zero
    # false positives by construction, so this one can never be trained away.
    ghost = sql("SELECT string_agg(document_id, ', ') FROM (SELECT q.document_id "
                "FROM extract_queue q WHERE q.state='done' AND NOT EXISTS (SELECT 1 FROM "
                "extracted.document d WHERE d.document_id=q.document_id) LIMIT 5) t;", cols=1)
    if ghost and ghost[0][0]:
        out.append("done with NO extracted.document row (impossible under the atomic commit): %s"
                   % ghost[0][0])
    # WEAKER: a document can legitimately yield zero spans. Name the ids rather than counting, so
    # a standing false positive is recognisable at a glance as the same document every cycle --
    # an alarm that cries wolf anonymously is how a team learns to skim past the whole channel.
    nospan = sql("SELECT string_agg(document_id, ', ') FROM (SELECT q.document_id "
                 "FROM extract_queue q WHERE q.state='done' AND NOT EXISTS (SELECT 1 FROM "
                 "extracted.span s WHERE s.document_id=q.document_id) LIMIT 5) t;", cols=1)
    if nospan and nospan[0][0]:
        out.append("done with no spans (may be legitimate; same ids every cycle = false alarm): %s"
                   % nospan[0][0])
    # FLOW: measure the DELIVERABLE landing, not a run row. extraction_run.started_at advances once
    # per worker START and RUN_SQL is ON CONFLICT DO NOTHING, so with three stable long-lived
    # workers it simply ages -- the alarm would fire perpetually in the exact steady state we want,
    # and stay silent for workers restarting hourly while storing nothing. Both directions wrong.
    stalled = sql("SELECT (SELECT count(*) FROM extract_queue WHERE state='ready'), "
                  "coalesce(EXTRACT(EPOCH FROM (now() - max(first_seen)))::int, 999999) "
                  "FROM extracted.document;", cols=2)
    if stalled:
        ready, quiet_s = int(stalled[0][0]), int(stalled[0][1])
        if ready > 0 and quiet_s > QUIET_ALARM_S:
            out.append("nothing landed in extracted.document for %.1fh while %d are ready"
                       % (quiet_s / 3600.0, ready))
    # CARD LAG: extraction landing in the store but never reaching serving.card is exactly the
    # break this pipeline already had once at the other end -- the crawler filled `documents` for
    # weeks while nothing moved it into the queue, and nobody noticed because every metric measured
    # the queue rather than the flow. Same shape, other end. 25 is well above one cycle's work.
    lag = sql("SELECT count(*) FROM extracted.document d WHERE NOT EXISTS "
              "(SELECT 1 FROM serving.card s WHERE s.document_id = d.document_id);", cols=1)
    if lag and int(lag[0][0]) > 25:
        out.append("%s extracted document(s) have no serving card -- the UI is going stale"
                   % lag[0][0])
    # CANARY: demote_stale compares crawl_ts as TEXT. That is exact only while every value is
    # 20-char ISO-8601 UTC ending Z. Check it every cycle instead of remembering it once.
    odd = sql("SELECT count(*) FROM extract_queue WHERE crawl_ts !~ "
              "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$';", cols=1)
    if odd and int(odd[0][0]) > 0:
        out.append("%s crawl_ts value(s) are not 20-char ISO-8601 Z -- the stale-class demotion "
                   "compares them as TEXT and is no longer exact" % odd[0][0])
    for a in out:
        print("  ALERT: %s" % a, flush=True)
    return out


def _safe(label, fn, *a, **k):
    """Run one supervisor stage so its failure cannot abort the rest of the cycle. A slow card
    build or a hung `docker top` used to raise straight past every later stage -- reap, stuck-kill,
    restart -- so the supervisor stayed alive while supervising nothing. Each stage is now isolated."""
    try:
        return fn(*a, **k)
    except Exception as e:
        print("  [stage %s] FAILED %s: %s -- continuing" % (label, type(e).__name__, str(e)[:160]),
              flush=True)
        return None


def cycle(state, dry=False):
    acted = False
    now = time.time()
    # SAFETY-CRITICAL FIRST: reap expired leases and check workers before the soft stages (cards,
    # alarms, enqueue). If a soft stage is slow or throws, the queue and the fleet are already tended.
    # H10: reap now matches route.REAP -- parks at MAX_ATTEMPTS (not a stale hardcoded 3), bumps the
    # lease epoch (so a reaped-but-alive worker's late commit is fenced out), and stamps a reason.
    reaped = _safe("reap", sql,
                   "UPDATE extract_queue SET "
                   "state = CASE WHEN attempts >= %d THEN 'parked' ELSE 'ready' END, "
                   "reason='lease expired', leased_by=NULL, lease_until=NULL, "
                   "lease_epoch=lease_epoch+1 "
                   "WHERE state='leased' AND lease_until < now() "
                   "RETURNING document_id, attempts;" % _route.MAX_ATTEMPTS, cols=2) \
             if not dry else []
    for doc, att in (reaped or []):
        print("  reaped %s (attempt %s)%s"
              % (doc, att, " -> PARKED" if int(att) >= _route.MAX_ATTEMPTS else ""), flush=True)
        acted = True

    if _safe("alarms", alarms):
        acted = True
    _safe("demote_stale", demote_stale, dry=dry)
    if _safe("build_cards", build_cards, dry=dry):
        acted = True
    if now - _last_enqueue[0] >= ENQUEUE_EVERY_S:
        _last_enqueue[0] = now
        if _safe("enqueue", run_enqueue, dry=dry):
            acted = True

    for node, n in NODES.items():
      try:
        pid = worker_pid(n["container"])
        if pid is UNKNOWN:
            print("  %-6s could not read process list -- skipping this cycle" % node, flush=True)
            continue
        if pid is None:
            print("  %-6s worker is DOWN -- starting" % node, flush=True)
            if not dry:
                # Kill first, unconditionally: stop_worker is idempotent, and if the process list
                # was merely unreadable a moment ago we must not end up with two.
                stop_worker(node)
                # Release what the dead worker was holding. Skipping this is how a node came to
                # hold two leases at once, one of them invisible to every subsequent check.
                for d, ep in all_held_by(node):
                    requeue(d, "worker was down", epoch=ep)
                ok, err = start_worker(node)
                print("      %s %s" % ("started" if ok else "FAILED", err), flush=True)
            acted = True
            continue
        h = held_by(node)
        if h is None:
            state.pop(node, None)
            age = log_age_s(n["container"])
            limit = orphan_deadline(node)
            if age is not None and age > limit:
                print("  %-6s ORPHANED -- no lease, silent %.0f min (limit %.0f) -- restarting"
                      % (node, age / 60, limit / 60), flush=True)
                if not dry:
                    killed = stop_worker(node)
                    for d, ep in all_held_by(node):
                        requeue(d, "orphaned worker", epoch=ep)
                    ok, err = start_worker(node)
                    print("      killed %s, restarted: %s %s" % (killed, ok, err), flush=True)
                acted = True
            continue
        doc, chars, secs, epoch = h
        deadline = stuck_deadline(chars, n["tok_s"])
        if state.get(node, (None,))[0] != doc:
            state[node] = (doc, time.time())
        if secs > deadline:
            print("  %-6s STUCK on %s (%d chars) for %.0f min, deadline %.0f min -- killing"
                  % (node, doc, chars, secs / 60, deadline / 60), flush=True)
            if not dry:
                killed = stop_worker(node)
                requeue(doc, "worker exceeded %.0f min" % (deadline / 60), epoch=epoch,
                        charge=True)
                ok, err = start_worker(node)
                print("      killed %s, restarted: %s %s" % (killed, ok, err), flush=True)
            state.pop(node, None)
            acted = True
      except Exception as e:
        # One node's docker hiccup must not skip the checks for the other nodes.
        print("  %-6s check FAILED %s: %s -- continuing" % (node, type(e).__name__, str(e)[:120]),
              flush=True)
    return acted


def restart_all(dry=False):
    """Stop every worker, hand its document back, start it again on whatever code is on disk.

    Needed because a running Python process holds its imports: the corrected store_pg.py sat on
    disk for over an hour while three workers kept calling the broken version they had cached at
    start-up, extracting cleanly and failing at the last step every time. Fixing a file is not
    deploying it."""
    for node, n in NODES.items():
        h = held_by(node)
        print("  %-6s stopping%s" % (node, (" (holds %s)" % h[0]) if h else ""), flush=True)
        if dry:
            continue
        killed = stop_worker(node)
        for d, ep in all_held_by(node):
            requeue(d, "worker restarted", epoch=ep)
        ok, err = start_worker(node)
        print("      killed %s, %s %s" % (killed, "started" if ok else "FAILED", err), flush=True)


def status():
    print("queue:", ", ".join("%s=%s" % (r[0], r[1]) for r in
                              sql("SELECT state, count(*) FROM extract_queue GROUP BY state "
                                  "ORDER BY 1;", cols=2)), flush=True)
    print("store:", ", ".join("%s=%s" % (k, v) for k, v in zip(
        ("docs", "spans"), sql("SELECT (SELECT count(*) FROM extracted.document), "
                               "(SELECT count(*) FROM extracted.span);", cols=2)[0])), flush=True)
    for node, n in NODES.items():
        pid = worker_pid(n["container"])
        h = held_by(node)
        print("  %-6s pid=%-8s %s" % (node, pid or "DOWN",
                                      ("holding %s (%d ch) for %.1f min of %.0f allowed"
                                       % (h[0], h[1], h[2] / 60,
                                          stuck_deadline(h[1], n["tok_s"]) / 60)) if h
                                      else "no lease"), flush=True)


LOCK = "/tmp/kssl-supervisor.lock"


def acquire_lock():
    """Exactly one supervisor, enforced by the OS rather than by hoping.

    Two of them ran for ten minutes and killed each other's freshly started workers: A starts a
    worker, B sees it briefly leaseless, kills it, A starts another. All three nodes ended up with
    no worker at all and the queue looked simply idle."""
    import fcntl
    f = open(LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another supervisor holds %s -- exiting" % LOCK, flush=True)
        sys.exit(3)
    f.write("%d\n" % os.getpid())
    f.flush()
    return f                      # kept open for the process lifetime; closing releases the lock


def _demo():
    """Pure-logic self-check. It exists because `supervise.py --demo` used to fall through to
    main() and start a REAL supervisor loop -- on a laptop, against production."""
    for node in NODES:
        # The floor is a FLOOR, not the answer for every small document. Asserting equality here
        # encoded "small doc => floor", which held only while every node was fast enough that
        # 3x a 500-char estimate stayed under 30 min -- and broke the moment the dc's rate was
        # corrected to a measured 1.5 tok/s, where 500 chars honestly needs 27 min.
        assert stuck_deadline(500, NODES[node]["tok_s"]) >= STUCK_FLOOR_S, node
        assert stuck_deadline(50000, NODES[node]["tok_s"]) > stuck_deadline(
            500, NODES[node]["tok_s"]), node
        # a stuck deadline must never be shorter than the longest legitimate rest, or a resting
        # worker gets killed for resting
        assert orphan_deadline(node) > NODES[node]["minutes"] * 60 * (
            1.0 / NODES[node]["duty"] - 1.0), node
    assert stuck_deadline(9274, NODES["dc"]["tok_s"]) > stuck_deadline(1089, NODES["dc"]["tok_s"])
    # the requeue must be fenced -- an unfenced one can overwrite a committed `done`
    import inspect
    src = inspect.getsource(requeue)
    assert "state='leased'" in src, "requeue must be fenced on state"
    assert "lease_epoch=%d" in src, "requeue must be fenced on the observed epoch"
    # the crawler must stay connected to the queue; this is the check that it is wired at all
    assert ENQUEUE_EVERY_S > 0 and "run_enqueue" in inspect.getsource(cycle), \
        "the supervisor must periodically enqueue newly crawled documents"
    # "could not look" must never be read as "nothing is there"
    csrc = inspect.getsource(cycle)
    assert "pid is UNKNOWN" in csrc and csrc.index("pid is UNKNOWN") < csrc.index("pid is None"), \
        "an unreadable process list must be handled BEFORE the down path"
    # The attempts economy must not be net-zero: refund when no extraction was attempted,
    # CHARGE when one was. A blanket refund makes park unreachable and lets one crashing
    # document consume a node forever.
    rq = inspect.getsource(requeue)
    assert "charge=False" in rq and "0 if charge else 1" in rq, \
        "requeue must charge or refund explicitly, never unconditionally refund"
    cy = inspect.getsource(cycle)
    assert "charge=True" in cy, "the stuck-kill must CHARGE the attempt"
    assert "worker was down" in cy and "charge=True" not in cy.split("worker was down")[1][:80], \
        "the down path must REFUND (no extraction was attempted)"
    assert "refresh_ui_store" in inspect.getsource(build_cards), \
        "new cards must also reach the dashboard, or the UI silently goes stale"
    assert "alarms" in cy and "demote_stale" in cy and "build_cards" in cy, \
        "the cycle must run the alarms, the stale-class demotion, and the card build"
    # Each stage is isolated so one failure cannot abort the rest of the cycle (reap + worker checks).
    assert "_safe(" in cy, "cycle stages must be wrapped so one failure does not skip the others"
    # The reap must park at the shared MAX_ATTEMPTS and bump the epoch, not a drifted hardcoded value.
    assert "lease_epoch=lease_epoch+1" in cy and "_route.MAX_ATTEMPTS" in cy, \
        "the reap must fence on the epoch and use route.MAX_ATTEMPTS, not a copied threshold"
    assert "serving.card" in inspect.getsource(alarms), \
        "an alarm must watch for extraction landing in the store but never reaching the UI"
    # the demotion compares TEXT timestamps; the cutoff must be forced to UTC, not the session's
    assert "timezone('UTC', now())" in inspect.getsource(demote_stale), \
        "the stale-class cutoff must be explicitly UTC, not session-timezone dependent"
    al = inspect.getsource(alarms)
    assert "extracted.document" in al and "max(first_seen)" in al, \
        "the quiet alarm must measure documents landing, not worker-start rows"
    assert "max(started_at)" not in al, \
        "extraction_run.started_at advances per worker START, not per document -- it fires " \
        "perpetually in the healthy steady state and stays silent when nothing is stored"
    assert "crawl_ts !~" in al, "the ISO-8601 canary must run every cycle"
    import route as _r
    assert "max_attempts" in _r.RELEASE and "max_attempts" in _r.CLAIM, \
        "park must be enforced in every state transition, not only in REAP"
    # THE assertion this round needed: the kill deadline must exceed the honest completion time of
    # any document the node is allowed to claim. Had this existed, correcting route's dc rate
    # would have failed here loudly instead of silently arming a kill mill.
    for _n2, _c2 in NODES.items():
        assert _c2.get("threads"), "%s must declare its model server's thread count" % _n2
        _cap = _r.NODES[_n2]["cap"]
        _dl = stuck_deadline(_cap, _c2["tok_s"])
        _need = _r.est_seconds(_cap, _c2["route_tok_s"])
        assert _dl > _need, (
            "%s: stuck deadline %.0f min is BELOW the %.0f min a cap-sized document honestly "
            "needs -- this kills healthy work and charges it an attempt" % (_n2, _dl / 60,
                                                                            _need / 60))
        # ...and the kill must still fire before the lease expires, or reap wins the race
        assert _dl < _r.lease_ttl(_cap, _c2["route_tok_s"]), \
            "%s: the stuck-kill must fire before the lease expires" % _n2
    # the reconstructed lease must match what route actually grants, or held-for is fiction
    for _n in NODES:
        for _ch in (500, 3000, 9000):
            _want = max(_route.TTL_FLOOR_S,
                        _route.TTL_FACTOR * _ch * _route.ALPHA
                        / _route.NODES[_n]["tok_s"] + 120)
            assert abs(granted_ttl(_n, _ch) - _want) < 1e-6, (_n, _ch)
    print("ok  deadlines are duty-aware; requeue is fenced on state and epoch")


def main():
    a = sys.argv
    if "--demo" in a:
        _demo(); return
    dry = "--dry" in a
    if "--status" in a:
        status(); return
    if "--restart-all" in a:
        restart_all(dry=dry); status(); return
    once = "--once" in a
    # A dry run mutates nothing, so it must not need the lock -- otherwise the one command you
    # reach for to diagnose a running supervisor is the one command the running supervisor blocks.
    _lock = None if dry else acquire_lock()   # noqa: F841 -- referenced, or GC frees the lock
    state = {}
    while True:
        try:
            if cycle(state, dry=dry):
                status()
        except Exception as e:
            print("supervisor error: %s: %s" % (type(e).__name__, str(e)[:200]), flush=True)
        if once:
            return
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
