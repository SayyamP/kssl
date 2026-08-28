"""Run Layer A and Layer B over the staged corpus.

    python run_extraction.py                # everything new in corpus/, workers=2
    python run_extraction.py --limit 10     # smoke run
    python run_extraction.py --demo

This is an ORCHESTRATOR, not a re-implementation: the engine is the live pipeline in
l2/comprehend (run.py -> build_pop.py -> bench_ontology.py --embed -> layer_b.py), invoked as
subprocesses exactly the way the watchdog invokes them. The extraction-stack/ copy exists for
clean machines; on THIS machine l2/comprehend is the code that has received every fix since the
snapshot was taken, so it is the one that runs.

Outputs land in the engine's own data/ directory under the `kssl_demo` prefix:
  data/kssl_demo_docs.jsonl     the staged corpus as run.py wants it
  data/kssl_demo.db             Layer A store (documents, spans, propositions, coverage)
  data/kssl_demo_pop.jsonl/_vec.npy/_keys.json    the embedded entity population
  data/kssl_demo_layer_b.db     Layer B store (entities, aliases, merges)

load_extracted.py then moves both stores into KSSL_Deploy's Postgres `extracted` schema.

GPU note: Layer A holds the 7b extractor + GLiNER. Do not run while the 14b judge or the
classifier is busy -- they do not co-reside in 24 GB (measured thrash, ~360 s/document).
"""
import argparse
import io
import json
import os
import stage_timer
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
ENGINE = HERE.parent.parent / "l2" / "comprehend"
SET = "kssl_demo"
DOCS = ENGINE / "data" / ("%s_docs.jsonl" % SET)
DB = "data/%s.db" % SET
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


WORKLIST = HERE / "extract_worklist.json"


def worklist_order():
    """Document ids ranked by what they could populate, best first.

    Without this, staging walks corpus/ in FILENAME order -- which is a sha of the
    URL, i.e. random -- and re-extracts the 50 documents already in the store. The
    ranking comes from extract_worklist.py, which scores each document against the
    same predicates the enrichment steps use to choose their own candidates."""
    if not WORKLIST.exists():
        return None
    try:
        rows = json.loads(WORKLIST.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return [r["document_id"] for r in rows if r.get("document_id")]


def stage_docs(limit=None, ranked=False, newest=False):
    """corpus/*.json -> the jsonl run.py consumes. Returns how many rows were written."""
    rows = []
    paths = sorted(CORPUS.glob("doc_*.json"))
    if newest:
        # Name order is document-id order, which has nothing to do with age --
        # so `--limit 8` quietly extracted eight of the OLDEST files in the
        # directory and the recency gate then refused every one of them.
        paths = sorted(paths, key=lambda q: q.stat().st_mtime, reverse=True)
        print("staging newest-first (%d document(s) on disk)" % len(paths), flush=True)
    if ranked:
        order = worklist_order()
        if not order:
            raise SystemExit("no extract_worklist.json -- run extract_worklist.py first")
        by_id = {p.stem: p for p in paths}
        paths = [by_id[d] for d in order if d in by_id]
        print("staging in worklist order (%d ranked document(s))" % len(paths), flush=True)
    skipped_undated = 0
    for p in paths:
        d = json.loads(p.read_text(encoding="utf-8"))
        # AN UNDATED DOCUMENT CAN NEVER BECOME A CARD. serving_fill refuses anything whose
        # publication date cannot be proven -- a fetch date is not a publish date -- so
        # extracting one spends four minutes of GPU to reach a guaranteed refusal.
        # corpus/ holds both shapes: 4,889 files carrying the crawler's published_at and 735
        # from older stagings that never had one, and `--newest` sorts by file mtime, which
        # interleaves them. Of 171 documents extracted before this filter existed, 122 were
        # undated.
        if not d.get("published_at"):
            skipped_undated += 1
            continue
        # The engine reads `main_text` (run.py line 75 and comprehend() both) -- the staging
        # field is renamed here rather than teaching the engine a second name.
        rows.append({"document_id": d["document_id"], "source_id": d["source_id"],
                     "url": d["url"], "title": d["title"], "language": d["language"],
                     "main_text": d["text"]})
        if limit and len(rows) >= limit:
            break
    if skipped_undated:
        print("skipped %d undated document(s) -- they cannot pass the recency gate"
              % skipped_undated, flush=True)
    DOCS.parent.mkdir(exist_ok=True)
    io.open(DOCS, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return len(rows)


# Seconds to allow per document in Layer A. 900 is a GPU-era number: measured on
# the data centre 2026-08-26, ONE article needed 13.8 min of GLiNER plus two
# comprehension calls of 21m26s and 26m21s -- and the hour-long ceiling killed it
# mid-document. A budget smaller than the work does not protect anything; it just
# throws away everything done so far and reports a timeout. Set this to what the
# host can actually do.
PER_DOC_S = int(os.environ.get("C_PER_DOC_S", "900"))


def step(label, argv, timeout, env=None, metric=None, items=None):
    """One engine stage. A failure stops the chain -- each stage feeds the next, so 'continue
    anyway' would only convert one loud failure into three quiet ones.

    `metric` names the row this writes to metrics.stage_run. The elapsed time was
    already being measured here and printed to stdout; it now also gets a
    destination, which is the whole difference between "we timed it" and "we can
    answer how long the stage takes"."""
    print("== %s" % label, flush=True)
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    t0 = time.time()
    with stage_timer.stage(metric or "extract_a", note=label) as st:
        if items:
            st.items(items)
        r = subprocess.run([sys.executable] + argv, cwd=str(ENGINE), env=e, timeout=timeout)
        print("   %s in %.0fs" % ("ok" if r.returncode == 0 else "FAILED rc=%d" % r.returncode,
                                  time.time() - t0), flush=True)
        if r.returncode != 0:
            raise SystemExit("stage failed: %s" % label)


def main(limit=None, workers=2, ranked=False, newest=False):
    n = stage_docs(limit, ranked, newest)
    if not n:
        raise SystemExit("corpus/ is empty -- run fetch_corpus.py first")
    print("staged %d document(s) -> %s" % (n, DOCS.name), flush=True)

    # Layer A scales with the corpus; the timeout scales with it (the flat-timeout batch kill
    # 20 seconds from the end is a mistake this project makes once).
    step("Layer A -- comprehension extraction",
         ["run.py", "--docs", str(DOCS), "--db", DB, "--workers", str(workers),
          "--note", "KSSL_Deploy demo corpus"],
         timeout=max(3600, n * PER_DOC_S), metric="extract_a", items=n)
    step("population -- entity rows from the new store",
         ["build_pop.py", "--dbs", DB, "--out", "data/%s_pop.jsonl" % SET],
         timeout=600, metric="extract_b")
    step("embeddings -- population + tree vectors",
         ["bench_ontology.py", "--embed"], timeout=3600, env={"C_SET": SET},
         metric="extract_b")
    step("Layer B -- canonical entities",
         ["layer_b.py", "--write", "--set", SET, "--db", "%s_layer_b.db" % SET],
         timeout=3600, env={"C_SET": SET}, metric="extract_b")
    print("\nextraction complete: data/%s.db + data/%s_layer_b.db under %s"
          % (SET, SET, ENGINE), flush=True)


def _demo():
    assert ENGINE.exists() and (ENGINE / "run.py").exists(), "engine missing"
    # The jsonl row must carry exactly what run.py reads.
    import tempfile
    d = {"document_id": "doc_x", "source_id": "s", "url": "u", "title": "t",
         "language": "en", "main_text": "hello"}
    assert set(d) >= {"document_id", "source_id", "main_text"}
    # stage_docs with a limit must not write more rows than asked.
    # the ranking must actually reorder staging, not just be written to a file
    order = worklist_order()
    if order:
        assert len(order) == len(set(order)), "a document must be staged once"
    if CORPUS.exists() and list(CORPUS.glob("doc_*.json")):
        n = stage_docs(limit=2)
        assert n <= 2 and DOCS.exists()
        rows = [json.loads(l) for l in io.open(DOCS, encoding="utf-8")]
        assert len(rows) == n and all("main_text" in r and "document_id" in r for r in rows)
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--worklist", action="store_true",
                    help="stage the ranked, not-yet-extracted documents "
                         "(extract_worklist.py) instead of corpus order")
    ap.add_argument("--newest", action="store_true",
                    help="stage the most recently pulled documents first. "
                         "Without this, --limit takes them in document-id "
                         "order, which is unrelated to age -- and the recency "
                         "gate downstream then refuses the lot.")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        main(limit=a.limit, workers=a.workers, ranked=a.worklist,
             newest=a.newest)
