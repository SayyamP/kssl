"""The data-centre half of the article bench.

    python bench/worker.py                 # poll forever
    python bench/worker.py --once          # take one job and stop

Polls metrics.adhoc_job on the VPS for a submitted article, then runs it through
the real pipeline -- the same scripts and the same engine the batch path uses,
not a demo of them:

    fetch -> gate -> Layer A (+ optional Layer B) -> load -> LLM -> serving

Every stage writes its own row to metrics.stage_run under the job's run_id, so
the dashboard's timings and the pipeline's timings are the same numbers.

WHY A POLLING WORKER AND NOT AN ENDPOINT
----------------------------------------
The dashboard is on the VPS; extraction has to happen here, where the engine
and the cores are. The only network direction that already exists is data
centre -> VPS database. Polling that database uses it and needs no inbound
port, no reverse tunnel and no firewall change.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP / "pipeline"))

import stage_timer                                      # noqa: E402
from pull_corpus import classify, load_env, _is_listing  # noqa: E402

load_env()

try:
    import psycopg2 as pg
    from psycopg2.extras import RealDictCursor
except ImportError:                                     # pragma: no cover
    sys.exit("psycopg2 is required: python -m pip install psycopg2-binary")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN", "")
ENGINE = APP.parent / "l2" / "comprehend"
CORPUS = APP / "pipeline" / "corpus"
WORKER = os.environ.get("KSSL_WORKER_NAME") or ("dc-%s" % uuid.uuid4().hex[:6])
MIN_TEXT = 400          # lower than the batch gate: a person chose this article


# ---------------------------------------------------------------- fetching
# The bench fetches a URL a person typed into a browser, from inside a container
# that is attached to BOTH the tunnel network (the VPS database and the VPS
# model) and the corpus network. Without the check below, "give it an article"
# is a request-forgery primitive: submit http://kssl-extract-ollama:11434/api/tags
# or http://mallory-data-postgres-1:5432 and the reply comes back as "the
# article text", gets extracted, and can end up on the client's dashboard.
# Blocking the literal hostname is not enough -- a public URL can redirect into
# the private range -- so the address is resolved and checked, and checked again
# after every redirect.
MAX_FETCH_BYTES = 8 * 1024 * 1024


def _reject_private(url):
    """Raise unless every address this host resolves to is on the public
    internet. Blocks loopback, link-local, private, multicast and reserved."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    u = urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("only http and https are fetched, not %r" % u.scheme)
    host = u.hostname
    if not host:
        raise ValueError("no host in %r" % url)
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError("cannot resolve %s (%s)" % (host, e))
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError("%s resolves to %s, which is not on the public "
                             "internet -- refusing to fetch it" % (host, ip))
    return url


class _GuardedRedirects(object):
    """urllib follows redirects for you, which is exactly the hole: the first
    URL passes the check and the third one is 127.0.0.1. Re-check each hop."""

    def __init__(self):
        import urllib.request
        outer = self

        class H(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                _reject_private(newurl)
                return urllib.request.HTTPRedirectHandler.redirect_request(
                    self, req, fp, code, msg, headers, newurl)

        self.opener = urllib.request.build_opener(H())


def fetch(url):
    """The article's text. Uses the crawler's own extractor when importable, so
    the bench and the fleet agree about what an article's text is."""
    import gzip
    import urllib.request
    # A bare request gets 406/403 from a lot of news sites: they check for the
    # Accept headers a browser always sends, not just the User-Agent. Sending an
    # honest UA with a browser's header set is the difference between "the bench
    # cannot read this site" and "the bench reads this site".
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
    })
    _reject_private(url)
    with _GuardedRedirects().opener.open(req, timeout=45) as r:
        # read() with no argument is unbounded, and so is decompress(): a small
        # gzip response can expand to gigabytes, and this container shares its
        # memory limit and its cores with the batch pipeline. One submission
        # should not be able to take the extraction lane down.
        raw = r.read(MAX_FETCH_BYTES + 1)
        if len(raw) > MAX_FETCH_BYTES:
            raise ValueError("the page is larger than %d MB -- not fetching it"
                             % (MAX_FETCH_BYTES // (1024 * 1024)))
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            d = gzip.GzipFile(fileobj=io.BytesIO(raw))
            raw = d.read(MAX_FETCH_BYTES + 1)
            if len(raw) > MAX_FETCH_BYTES:
                raise ValueError("the page decompresses to more than %d MB "
                                 "-- not fetching it"
                                 % (MAX_FETCH_BYTES // (1024 * 1024)))
    enc = "utf-8"
    ctype = r.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    if m:
        enc = m.group(1)
    html = raw.decode(enc, "replace")

    title, text, published = None, None, None
    for base in (APP.parent / "Production crawler" / "crawler",
                 APP.parent / "cralwer"):
        if not (base / "crawler" / "parse.py").exists():
            continue
        sys.path.insert(0, str(base))
        try:
            from crawler import parse as cparse          # noqa: PLC0415
            from crawler import textextract as ctext     # noqa: PLC0415
            title = cparse.title_of(html)
            text = ctext.main_text(html)
            published = (cparse.extract_meta(html, url) or {}).get("published_raw")
            break
        except Exception:                                # noqa: BLE001
            continue
        finally:
            sys.path.remove(str(base))

    if not text:
        # Fallback: strip the obvious furniture. Good enough for a pasted URL.
        from html.parser import HTMLParser

        class _Strip(HTMLParser):
            def __init__(self):
                super().__init__()
                self.out, self.skip = [], 0

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer", "header"):
                    self.skip += 1

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer", "header"):
                    self.skip = max(0, self.skip - 1)

            def handle_data(self, d):
                if not self.skip and d.strip():
                    self.out.append(d.strip())

        p = _Strip()
        p.feed(html)
        text = "\n".join(p.out)
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = (m.group(1).strip() if m else url)[:400]
    return (title or url)[:400], text, published



def from_corpus(url):
    """The article as the fleet already stored it, or None.

    The corpus is reached read-only through KSSL_CORPUS_DSN. Only small columns
    are used to find the row; main_text is read for the one row that matches.
    """
    dsn = os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        return None
    try:
        with pg.connect(dsn, connect_timeout=10) as cx:
            with cx.cursor() as cur:
                cur.execute("SELECT title, published_at FROM documents "
                            "WHERE url = %s ORDER BY ingested_at DESC LIMIT 1",
                            (url,))
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute("SELECT main_text FROM documents WHERE url = %s "
                            "ORDER BY ingested_at DESC LIMIT 1", (url,))
                text = (cur.fetchone() or [None])[0]
        if not text:
            return None
        return (row[0] or url)[:400], text, row[1]
    except Exception:                                   # noqa: BLE001
        return None


# ---------------------------------------------------------------- the stages
def run_engine(argv, timeout, env=None, metric="extract_a", label=""):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    with stage_timer.stage(metric, note=label) as st:
        r = subprocess.run([sys.executable] + argv, cwd=str(ENGINE), env=e,
                           timeout=timeout, capture_output=True, text=True)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-400:]
            raise RuntimeError("%s failed: %s" % (label, tail))
        st.items(1)
    return r.stdout


def process(job, cx):
    """One article, all the way. Raises on a stage failure."""
    run_id = job["run_id"]
    os.environ["KSSL_RUN_ID"] = run_id
    stage_timer.RUN_ID = run_id
    # NOT hardcoded: this worker runs wherever the engine is, and a
    # workstation timing stamped "datacentre" is exactly the mislabel
    # stage_timer warns about.
    stage_timer.HOST = os.environ.get("KSSL_HOST_ROLE") or "unknown"

    def mark(stage_name):
        with cx.cursor() as cur:
            cur.execute("UPDATE metrics.adhoc_job SET stage=%s WHERE run_id=%s",
                        (stage_name, run_id))
        cx.commit()

    # ---- 1. the article itself
    mark("fetch")
    if job.get("raw_text"):
        title = job.get("title") or "(pasted article)"
        text, published = job["raw_text"], None
        with stage_timer.stage("crawl", note="pasted text") as st:
            st.items(1)
    else:
        with stage_timer.stage("crawl", note="fetch %s" % (job["url"] or "")[:80]) as st:
            try:
                title, text, published = fetch(job["url"])
                st.annotate(via="live fetch")
            except Exception as exc:                    # noqa: BLE001
                # Some sites refuse anything that is not a real browser. If the
                # fleet has already crawled this page -- and for a defence news
                # URL it very often has -- the corpus copy is the same article
                # and needs no second fight with the site.
                got = from_corpus(job["url"])
                if not got:
                    raise
                title, text, published = got
                st.annotate(via="corpus (live fetch said: %s)" % str(exc)[:80])
            st.items(1)

    if not text or len(text) < MIN_TEXT:
        return "refused: too short (%d chars, need %d)" % (len(text or ""), MIN_TEXT), None, None

    # ---- 2. the same gate the batch path uses
    mark("select")
    with stage_timer.stage("select", note="relevance gate") as st:
        if job.get("url") and _is_listing(job["url"]):
            return "refused: listing / index page", None, None
        ok, why = classify(text, title)
        st.items(1).annotate(gate=why)
    if not ok:
        return "refused: %s" % why, None, None

    # ---- 3. stage the document the way the corpus path does
    doc_id = "adhoc_%s" % run_id[:12]
    doc = {"document_id": doc_id, "url": job.get("url") or "about:pasted",
           "title": title, "text": text, "source_id": "bench",
           "published_at": published, "language": None, "gate": why}
    # write the title and document id back now, not at the end: the dashboard
    # shows this row while the job runs, and a blank title for ten minutes reads
    # as "nothing is happening".
    with cx.cursor() as cur:
        cur.execute("UPDATE metrics.adhoc_job SET title=%s, document_id=%s "
                    "WHERE run_id=%s", (title[:400], doc_id, run_id))
    cx.commit()

    CORPUS.mkdir(exist_ok=True)
    io.open(CORPUS / ("doc_%s.json" % doc_id), "w", encoding="utf-8",
            newline="").write(json.dumps(doc, ensure_ascii=False))

    docs_jsonl = ENGINE / "data" / ("bench_%s.jsonl" % doc_id)
    io.open(docs_jsonl, "w", encoding="utf-8", newline="").write(json.dumps({
        "document_id": doc_id, "source_id": "bench", "url": doc["url"],
        "title": title, "language": None, "main_text": text}) + "\n")

    # ---- 4. Layer A
    mark("extract_a")
    db = "data/bench_%s.db" % doc_id
    run_engine(["run.py", "--docs", str(docs_jsonl), "--db", db,
                "--workers", "1", "--note", "bench %s" % run_id],
               timeout=int(os.environ.get("C_PER_DOC_S", "3600")),
               metric="extract_a", label="Layer A")

    # ---- 5. Layer B, only when asked: it is a SET-level operation and the
    #        embedding pass alone costs minutes, which is a poor trade for one
    #        article unless the entity view is what you came to see.
    if job.get("layer_b"):
        mark("extract_b")
        run_engine(["build_pop.py", "--dbs", db,
                    "--out", "data/bench_%s_pop.jsonl" % doc_id],
                   timeout=900, metric="extract_b", label="population")
        # layer_b.load() opens {set}_vec.npy and {set}_keys.json, and NOTHING
        # else in this sequence writes them -- bench_ontology.py --embed does.
        # Without it Layer B dies on FileNotFoundError for the .npy every single
        # time, which is why no bench run has ever produced entities. C_SET is
        # what names all three files, so it has to be set here too.
        run_engine(["bench_ontology.py", "--embed"],
                   timeout=1800, env={"C_SET": "bench_%s" % doc_id},
                   metric="extract_b", label="embeddings")
        run_engine(["layer_b.py", "--write", "--set", "bench_%s" % doc_id,
                    "--db", "bench_%s_layer_b.db" % doc_id],
                   timeout=1800, env={"C_SET": "bench_%s" % doc_id},
                   metric="extract_b", label="Layer B")

    # ---- 6. into the VPS Postgres
    mark("load")
    with stage_timer.stage("extract_b", note="load into the VPS database") as st:
        out = subprocess.run(
            [sys.executable, str(APP / "pipeline" / "load_extracted.py"),
             "--sets", "bench_%s" % doc_id],
            cwd=str(APP / "pipeline"), env=dict(os.environ), capture_output=True,
            text=True, timeout=1800)
        if out.returncode != 0:
            raise RuntimeError("load failed: %s" % (out.stderr or "")[-400:])
        st.items(1)

    # ---- 7. the LLM on the VPS turns it into a card
    mark("llm")
    fill = subprocess.run(
        [sys.executable, str(APP / "pipeline" / "serving_fill.py"),
         "--limit", "1", "--only", doc_id],
        cwd=str(APP / "pipeline"), env=dict(os.environ), capture_output=True,
        text=True, timeout=2400)
    detail = (fill.stdout or "").strip().splitlines()[-1:] or [""]
    # A crashed or timed-out card step is NOT a refusal. Reporting it as one
    # ("refused by the card gate") hides a broken model call behind a sentence
    # that reads like a considered editorial decision -- which is exactly what
    # happened the first time this ran.
    if fill.returncode != 0:
        raise RuntimeError("the card step failed (rc=%d): %s"
                           % (fill.returncode,
                              ((fill.stderr or fill.stdout or "").strip()[-300:])))
    if "0 error(s)" not in (fill.stdout or "") and "error" in (fill.stdout or "").lower():
        raise RuntimeError("the card step reported errors: %s" % detail[0][:250])

    # ---- 8. did a card land?
    mark("serving")
    # This was the one step with no timer, so a run that produced a card still
    # rendered as though it had stopped a stage early.
    with stage_timer.stage("serving", note="card visible in the serving table") as st:
        with cx.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM serving.signal_card WHERE id = %s",
                        ("pl_%s" % doc_id,))
            row = cur.fetchone()
        st.items(1 if row else 0)
    if row:
        return "card", row["id"], doc_id
    return "refused by the card gate: %s" % detail[0][:200], None, doc_id


# ---------------------------------------------------------------- the loop
def claim(cx):
    """Take one queued job. The UPDATE ... RETURNING is the claim: two workers
    cannot both win it."""
    with cx.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE metrics.adhoc_job SET status='running', claimed_at=now(),
                   worker=%s
             WHERE run_id = (SELECT run_id FROM metrics.adhoc_job
                              WHERE status='queued'
                              ORDER BY submitted LIMIT 1
                              FOR UPDATE SKIP LOCKED)
         RETURNING *""", (WORKER,))
        job = cur.fetchone()
    cx.commit()
    return job


STALE_MINUTES = int(os.environ.get("KSSL_BENCH_STALE_MIN", "90"))


def reap(cx):
    """Put jobs back that no worker is going to finish.

    A worker can die mid-job -- the container is restarted, the tunnel drops,
    the process is killed. The claim survives it, so the row sits at 'running'
    for ever and the dashboard shows a spinner that will never stop. Nothing
    else recovers it: `claim` only looks at 'queued'. The window is generous
    because a real document legitimately takes tens of minutes on CPU; the
    point is that the state is not permanent, not that it is prompt.
    """
    with cx.cursor() as cur:
        cur.execute("""UPDATE metrics.adhoc_job
                          SET status='queued', claimed_at=NULL, worker=NULL,
                              stage=NULL
                        WHERE status='running'
                          AND claimed_at < now() - make_interval(mins => %s)
                        RETURNING run_id""", (STALE_MINUTES,))
        back = [r[0] for r in cur.fetchall()]
    cx.commit()
    for r in back:
        print("  requeued %s -- claimed over %d minutes ago and never finished"
              % (r, STALE_MINUTES), flush=True)


def finish(cx, run_id, status, outcome, card_id=None, document_id=None):
    # Called from the failure path too, with the connection that may be exactly
    # what failed. If this raises there, the exception escapes the worker loop
    # and the container exits with the job still marked running -- a tunnel
    # hiccup would strand it permanently. So: try the connection we have, and
    # if it is gone, open a fresh one for this one statement.
    try:
        _finish(cx, run_id, status, outcome, card_id, document_id)
    except Exception:                                   # noqa: BLE001
        try:
            fresh = pg.connect(DSN, connect_timeout=10)
        except Exception as exc:                        # noqa: BLE001
            print("  could not record the outcome of %s: %s"
                  % (run_id, str(exc)[:120]), flush=True)
            return
        try:
            _finish(fresh, run_id, status, outcome, card_id, document_id)
        finally:
            fresh.close()


def _finish(cx, run_id, status, outcome, card_id=None, document_id=None):
    with cx.cursor() as cur:
        cur.execute("""UPDATE metrics.adhoc_job
                          SET status=%s, outcome=%s, card_id=%s,
                              document_id=coalesce(%s, document_id),
                              finished_at=now(), stage=NULL
                        WHERE run_id=%s""",
                    (status, outcome, card_id, document_id, run_id))
    cx.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=float, default=3.0)
    a = ap.parse_args()

    if not DSN:
        sys.exit("KSSL_DSN is not set -- it must point at the VPS database")
    os.environ.setdefault("KSSL_METRICS_DSN", DSN)
    if not os.environ.get("KSSL_HOST_ROLE"):
        sys.exit("set KSSL_HOST_ROLE (workstation | datacentre) so the timings "
                 "say where they were measured")

    print("bench worker %s polling %s" % (WORKER, re.sub(r"password=\S+",
                                                         "password=***", DSN)))
    while True:
        try:
            cx = pg.connect(DSN, connect_timeout=10)
        except Exception as exc:                        # noqa: BLE001
            print("  database unreachable: %s" % str(exc)[:120])
            if a.once:
                return 1
            time.sleep(10)
            continue
        try:
            reap(cx)
            job = claim(cx)
            if not job:
                if a.once:
                    print("  nothing queued")
                    return 0
                time.sleep(a.poll)
                continue
            print("== %s  %s" % (job["run_id"], (job["url"] or "(pasted)")[:70]))
            t0 = time.time()
            try:
                outcome, card_id, doc_id = process(job, cx)
                status = "done" if outcome == "card" else "done"
                finish(cx, job["run_id"], status, outcome, card_id, doc_id)
                print("   %s in %.1fs" % (outcome, time.time() - t0))
            except Exception as exc:                    # noqa: BLE001
                finish(cx, job["run_id"], "failed", str(exc)[:400])
                print("   FAILED in %.1fs: %s" % (time.time() - t0, str(exc)[:200]))
            if a.once:
                return 0
        finally:
            cx.close()


if __name__ == "__main__":
    sys.exit(main())
