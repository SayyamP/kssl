"""Queue worker: the pull loop that run.py's --docs mode cannot do.

    python run_node.py --node dc

This is run.py with the queue drain, deployed under its own name ON PURPOSE. The DC's run.py has
diverged from this repo's copy before -- comprehend.py there was rewritten by someone else while
we were mid-change -- so overwriting a shared entry point to add a feature only we use is how you
silently break someone else's run. Same code, new filename, nothing of theirs touched.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store  # noqa: E402
from comprehend import comprehend  # noqa: E402
from segment import classify, detect_lang, tokenize  # noqa: E402

HERE = Path(__file__).parent
DOCS = HERE / "data" / "docs.jsonl"


def load_docs(path=None):
    """Load one or more doc files. Passing --docs 'a.jsonl,b.jsonl' benchmarks a combined set
    without copying rows around."""
    paths = [Path(p) if Path(p).is_absolute() else HERE / p
             for p in (path.split(",") if path else [str(DOCS)])]
    out = []
    for p in paths:
        out += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def _safe_release(q, node, doc_id, epoch, reason):
    """Release a held lease without ever letting the release itself kill the worker. Returns a
    working queue connection: the same one, or a fresh one if `q` was the thing that died. A dead
    connection in the failure path is exactly how a store blip used to strand a lease for its full
    TTL and charge the attempt."""
    import route
    for attempt in (1, 2):
        try:
            try:
                q.rollback()
            except Exception:
                pass
            route.release(q, doc_id, epoch, reason, charge=True)
            return q
        except Exception as e:
            if attempt == 2:
                print(f"{node}: could not release {doc_id} even on a fresh connection: "
                      f"{type(e).__name__}; reap will reclaim it", flush=True)
                return q
            try:
                q.close()
            except Exception:
                pass
            q = route.connect_queue()          # reconnect and try once more
    return q


def drain(node, conn, process, lin=None):
    """Claim -> extract -> commit, until the queue offers this node nothing. One document at a
    time, deliberately: token generation already saturates the cores, so a second concurrent
    document on the same node splits the same tokens/second between two callers and finishes
    neither sooner. Concurrency here buys latency, not throughput, and we have none to spare.
    """
    import route
    q = route.connect_queue()             # None if psycopg/DSN absent -- say so, do not pretend
    if q is None:
        print("no queue connection (set KSSL_CORPUS_DSN); nothing to drain", flush=True)
        return
    # Prove the store path works BEFORE claiming anything. Four times this module has extracted
    # a document perfectly over 8-25 minutes and thrown it away on the final INSERT, and every
    # time the only trace was a line in a container-local log nobody was reading. One canonical
    # record through the real path, rolled back, costs milliseconds and turns that entire class
    # of failure into a worker that refuses to start.
    if lin is not None:
        import store_pg
        try:
            store_pg.preflight(q, lin)
            print("  preflight ok: store path verified against the live schema", flush=True)
        except Exception as e:
            print(f"PREFLIGHT FAILED -- refusing to drain: {type(e).__name__}: {str(e)[:220]}",
                  flush=True)
            return
    sql, args = route.claim_sql(node)
    loose_sql, loose_args = route.claim_sql(node, relaxed=True)
    cfg = route.NODES[node]
    print(f"worker {node}: classes P{cfg.get('min_class', 0)}-P{cfg['max_class']}, "
          f"<= {cfg['cap']:,} chars, {cfg['minutes']} min budget, order {cfg['order']}", flush=True)
    print(f"  pacing: {route.DUTY.get(node, 0.85):.0%} duty cycle, "
          f"min gap {route.MIN_GAP_S}s, health gate at {route.load_ok.__name__}", flush=True)
    # `empty` and `svc_fail` are counted SEPARATELY and reset independently. They used to share
    # one counter, which meant a gateway blip climbed the queue-empty ladder to 300s and stayed
    # there until a claim succeeded -- so a ten-second 502 cost five minutes of an idle GPU slot.
    n, empty, svc_fail = 0, 0, 0
    while True:
        # Health BEFORE claim. Claiming first and then discovering the box is overloaded leaves
        # the document leased until its TTL expires -- the slowest possible way to find out.
        # Two gates, both BEFORE the claim, because a document leased to a node that cannot
        # process it is frozen for the whole lease TTL before anyone else can have it.
        svc_ok, svc_why = route.service_ok(node)
        if not svc_ok:
            svc_fail += 1
            wait = route.svc_backoff_s(svc_fail - 1)
            print(f"{node}: model server not ready ({svc_why}); "
                  f"holding {wait:.0f}s and claiming nothing "
                  f"(probe failure {svc_fail})", flush=True)
            time.sleep(wait)
            continue
        svc_fail = 0
        if not route.load_ok(node):
            wait = route.backoff_s(empty)
            print(f"{node}: load too high, holding {wait:.0f}s before asking again", flush=True)
            time.sleep(wait)
            empty += 1
            continue
        # Strict cap first, so a node always prefers work sized for it. Only when there is
        # nothing at all within its own limit does it reach for a longer document: an idle node
        # beside a full queue is pure waste, and the downside is bounded -- a lost lease re-queues
        # and store.save is idempotent, so being wrong costs compute, never data.
        with q.cursor() as c:
            c.execute(sql, args)
            row = c.fetchone()
        q.commit()
        if not row:
            with q.cursor() as c:
                c.execute(loose_sql, loose_args)
                row = c.fetchone()
            q.commit()
            if row:
                print(f"{node}: nothing within {cfg['cap']:,} chars; taking a longer one "
                      f"(up to {cfg['fallback_cap']:,}) rather than idling", flush=True)
        if not row:
            # Nothing eligible is normal, not an error: this node's classes and length cap simply
            # have no work right now. Back off rather than spin, and keep the worker alive so it
            # picks up the next enqueue without anyone restarting it.
            empty += 1
            wait = route.backoff_s(empty)
            if empty == 1:
                print(f"{node}: nothing eligible ({n} done); polling with backoff", flush=True)
            time.sleep(wait)
            continue
        empty = 0
        doc_id, epoch, chars, text_hash = row
        d = route.fetch_doc(q, doc_id)
        if d is None or not (d.get("main_text") or "").strip():
            route.park(q, doc_id, epoch, "document has no text in corpus")
            print(f"{node}: PARKED {doc_id} -- no longer in the corpus", flush=True)
            continue
        # fetch_doc SELECTs on a non-autocommit connection, which OPENS a transaction it never
        # closes. Left open, store_pg's `with conn.transaction()` nests as a SAVEPOINT instead of
        # a transaction: nothing is durable until some later commit, and a worker killed in
        # between rolls the finished document back. Measured live: three sessions idle in
        # transaction for 5-6 minutes each, holding the shared database's vacuum horizon open
        # across every 8-25 minute extraction. End the read here; the write opens its own.
        q.commit()
        # The offset contract assumes every node sees byte-identical text. If it does not, spans
        # locate against text this node never had, and the failure shows up as a quiet rise in
        # unlocatable spans rather than as an error. Verify before spending 20 minutes on it.
        try:
            if route.text_hash(d["main_text"]) != text_hash:
                route.park(q, doc_id, epoch, "text_hash mismatch")
                print(f"{node}: PARKED {doc_id} -- text changed since enqueue", flush=True)
                continue
            n += 1
            t_doc = time.time()
            rec = process(n, d, want_rec=True)
            elapsed = time.time() - t_doc
            if rec is None:
                # Release it NOW rather than letting the lease run out. On the dc that lease is up to
                # 172 minutes -- nearly three hours of a document sitting `leased`, doing nothing,
                # after a failure that was known the instant it happened. Worse, the eventual reap
                # counts it as an attempt, so three fast failures park the document permanently for a
                # fault that was never the document's. Fenced on our epoch so this cannot disturb a
                # lease someone else now holds.
                # charge=True: an extraction WAS attempted and failed. Refunding here is what made
                # park unreachable -- a document that crashes deterministically was re-claimed from
                # the head of its own FIFO class in seconds, forever, consuming the node.
                route.release(q, doc_id, epoch, "extraction failed", charge=True)
                print(f"{node}: extraction failed for {doc_id}; lease released (attempt charged)",
                      flush=True)
                time.sleep(route.MIN_GAP_S)      # never spin: a fast crash must not become a hot loop
                continue
            # The spans and the done-mark go in ONE transaction, fenced on our lease epoch. Writing
            # them separately is what lost a completed document earlier: the queue said `done` while
            # the extraction lived only in container-local /tmp, and a container recreate took it.
            # Either both land or neither does.
            # A mid-document LLM outage makes every chunk return [], and the document would then be
            # stored and marked done holding only NER spans -- a near-empty result, permanently, with
            # nothing to say the model never answered. Refuse to store it; the audit already knows.
            # Test for LLM spans specifically, not for spans at all: GLiNER and the values pass still
            # produce spans during a total model outage, so `not rec["spans"]` was almost never true
            # and this guard almost never fired. The black hole it was written to close -- an NER-only
            # document committed as a complete `done` -- stayed open behind a check that looked shut.
            _failed = sum(1 for a in (rec.get("audit") or [])
                          if a.get("kind") == "llm_call_failed")
            if _failed and not any((sp.get("source") == "llm") for sp in (rec.get("spans") or [])):
                # WAS IT THIS DOCUMENT, OR WAS IT THE FARM? Charging an attempt answers "this
                # document is poison"; MAX_ATTEMPTS is 5 and a park is TERMINAL, so five power
                # cuts at one site silently destroy a perfectly good document. The Pune farm
                # loses power routinely -- 5-10 minutes, occasionally 30 -- and every outage was
                # spending one of every in-flight document's five lives.
                #
                # route.py states the rule this violates, in its own words: park "must mean
                # `impossible`, never `nobody is up right now`". So ask the server. If it is
                # down, the document was never tried and the claim's +1 is refunded (charge=
                # False subtracts it back to net zero); if it is up, the failure really was
                # about this document and the charge stands.
                up, up_why = route.service_ok(node)
                route.release(q, doc_id, epoch, "every LLM chunk failed", charge=up)
                print(f"{node}: every LLM chunk failed for {doc_id}; not stored, lease released"
                      + ("" if up else f" WITHOUT charging an attempt -- server is down ({up_why})"),
                      flush=True)
                time.sleep(route.MIN_GAP_S)
                continue
            import store_pg
            try:
                ns, np = store_pg.save_and_commit(q, rec, lin, doc_id, epoch)
                print(f"{node}: stored {ns} spans, {np} propositions for {doc_id}", flush=True)
            except store_pg._LeaseLost:
                print(f"{node}: lease lost on {doc_id} -- spans rolled back, whoever holds it owns "
                      f"the result", flush=True)
            except Exception as e:
                # Roll back and hand the document straight back. Letting the lease expire here was
                # the costliest habit in the system: the store layer has failed four separate times
                # this way, and each failure ALSO burned an attempt, so a deterministic store bug
                # parks the entire corpus after three wasted extractions each. The fault is ours,
                # so it must not count against the document.
                route.release(q, doc_id, epoch, "store failed", charge=True)
                print(f"{node}: STORE FAILED {type(e).__name__}: {str(e)[:150]} -- lease released "
                      f"(attempt charged)", flush=True)
                time.sleep(route.MIN_GAP_S)
            # Rest before asking for more. This is the whole back-pressure mechanism: the node is
            # never SENT work, it asks -- and it waits before asking. A 10-minute document on an 85%
            # duty node rests ~106s, which the capacity figures already account for.
            rest = route.cooldown_s(node, elapsed)
            if rest:
                print(f"{node}: {elapsed/60:.1f} min document, resting {rest:.0f}s "
                      f"({route.DUTY.get(node, 0.85):.0%} duty)", flush=True)
                time.sleep(rest)
        except Exception as _ex:
            # SAFETY NET: any unhandled error in the leased section (a null/oversized doc, a
            # crash inside process(), a broken connection) must NOT kill the worker with the
            # lease held -- that is the poison-doc loop that permanently eats a node. Release
            # the lease (charge=True: an attempt was made) on a fresh connection if q is dead,
            # then keep draining.
            print(f"{node}: UNHANDLED {type(_ex).__name__} on {doc_id}: {str(_ex)[:150]} -- "
                  f"releasing lease and continuing", flush=True)
            q = _safe_release(q, node, doc_id, epoch, f"unhandled: {type(_ex).__name__}")
            time.sleep(route.MIN_GAP_S)
            continue


def main():
    a = sys.argv
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    only = a[a.index("--only") + 1] if "--only" in a else None
    redo = "--redo" in a
    workers = int(a[a.index("--workers") + 1]) if "--workers" in a else 1
    write_lock = threading.Lock()
    # --node turns run.py from "process this file" into "be a worker on the shared queue".
    # Everything downstream -- one(), store.save(), the coverage report -- is untouched: the only
    # difference is where documents come from and that finishing one releases its lease.
    node = a[a.index("--node") + 1] if "--node" in a else None
    docs = [] if node else load_docs(a[a.index("--docs") + 1] if "--docs" in a else None)
    if only:
        docs = [d for d in docs if only.lower() in (d.get("source_id", "") + d["document_id"]).lower()]
    db = a[a.index("--db") + 1] if "--db" in a else None
    conn = store.connect(db) if db else store.connect()
    from lineage import run_lineage
    lin = run_lineage(run_id=a[a.index("--run-id") + 1] if "--run-id" in a else None,
                      note=a[a.index("--note") + 1] if "--note" in a else "")
    run_id = store.save_run(conn, lin)
    print(f"run {run_id}  pipeline {lin['pipeline_version'] or '(no git)'}  "
          f"lexicon {lin['lexicon_version']}\n"
          f"  model {lin['model']} {lin['model_digest']}  gliner {lin['gliner']}", flush=True)
    done = {r[0] for r in conn.execute("SELECT document_id FROM doc").fetchall()}
    if node and not redo:
        pass                                 # the queue already tracks state; `done` is local only
    if not node and not redo:
        docs = [d for d in docs if d["document_id"] not in done]
    if limit:
        docs = docs[:limit]
    print(f"{len(docs)} document(s) to process ({len(done)} already stored), "
          f"{workers} worker(s)\n", flush=True)

    t0 = time.time()
    done_n = [0]

    def one(n, d, want_rec=False):
        print(f"[{n}/{len(docs)}] {d.get('source_id', '')} · {len(d['main_text'])} chars · "
              f"declared {d.get('language', '')}", flush=True)
        try:
            rec = comprehend(d)
        except Exception as e:
            print(f"[{n}] FAILED {type(e).__name__}: {str(e)[:120]}", flush=True)
            return None
        toks = classify(tokenize(rec["text"]), rec["language"])
        from segment import coverage
        coverage(toks, rec["spans"])          # re-mark covered flags for the token table
        # One SQLite connection, many workers: serialize writes. Interleaved executemany calls on a
        # shared connection corrupt the row set long before SQLite complains about threads.
        # In queue mode the durable write is Postgres, done by the caller inside the same
        # transaction as the done-mark. The local SQLite copy is kept only when NOT in queue mode,
        # because that is the path `--docs` still uses.
        if not want_rec:
            with write_lock:
                store.save(conn, rec, toks, run_id=run_id)
        with write_lock:
            done_n[0] += 1
            k = done_n[0]
        c = rec["coverage"]
        el = time.time() - t0
        print(f"[{n}] -> content {c['pct_content']}%  explained {c['pct_spans_explained']}%  "
              f"ref-ctx {c['pct_referential_contextual']}%  spans {c['spans']}  "
              f"props {len(rec['propositions'])}  {rec['elapsed_s']}s   "
              f"({k}/{len(docs)} stored, {el / 60:.0f}m elapsed, "
              f"eta {el / max(1, k) * (len(docs) - k) / 60:.0f}m)\n", flush=True)
        return rec if want_rec else None

    if node:
        drain(node, conn, one, lin)
    elif workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda t: one(*t), list(enumerate(docs, 1))))
    else:
        for n, d in enumerate(docs, 1):
            one(n, d)

    rows = conn.execute(
        "SELECT d.source_id, c.pct_content, c.pct_spans_explained, c.pct_referential_contextual, "
        "c.spans, c.n_uncovered_content FROM coverage c JOIN doc d USING(document_id) "
        "ORDER BY c.pct_content").fetchall()
    print(f"{'source':<28}{'content%':>9}{'expl%':>7}{'refctx%':>8}{'spans':>7}{'holes':>7}")
    for r in rows:
        print(f"{(r[0] or '')[:27]:<28}{r[1]:>9}{r[2]:>7}{r[3]:>8}{r[4]:>7}{r[5]:>7}")
    if rows:
        print(f"\nmean content coverage {sum(r[1] for r in rows) / len(rows):.1f}%  "
              f"mean explained {sum(r[2] for r in rows) / len(rows):.1f}%  "
              f"over {len(rows)} docs, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        import tempfile
        # Test the LOADER, not the presence of sample data. The production package ships without
        # data/docs.jsonl, so asserting it exists made this self-check fail on every clean install
        # -- a check that cannot pass is worse than no check, because it teaches people to ignore
        # the runner that reports it.
        d = Path(tempfile.mkdtemp())
        one, two = d / "a.jsonl", d / "b.jsonl"
        one.write_text(json.dumps({"document_id": "x", "main_text": "hello", "source_id": "s"}),
                       encoding="utf-8")
        two.write_text("\n".join(json.dumps({"document_id": "y%d" % i, "main_text": "t",
                                             "source_id": "s"}) for i in range(3)) + "\n\n",
                       encoding="utf-8")
        ds = load_docs(str(one))
        assert len(ds) == 1 and ds[0]["document_id"] == "x", ds
        # several files combine, and a blank line is not a document
        assert len(load_docs("%s,%s" % (one, two))) == 4, load_docs("%s,%s" % (one, two))
        if DOCS.exists():                       # only meaningful where the sample set is present
            real = load_docs()
            assert real and "main_text" in real[0] and "document_id" in real[0]
        print("ok")
    else:
        main()
