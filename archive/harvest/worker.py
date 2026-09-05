"""One harvester instance. Start several; they divide the companies between them.

    python worker.py --id 0 --of 6          # instance 0 of 6
    python worker.py --id 0 --of 1 --once   # drain one task and stop
    python worker.py --demo

SHARDING IS BY COMPANY, NOT BY TASK
-----------------------------------
Worker N takes only the companies whose id hashes to N. One company is one host, so this
buys per-host politeness for free: no two workers can ever be hitting the same site, and
the delay between requests is a plain sleep inside one process instead of a distributed
rate limiter. Sharding by TASK instead would put six workers on one maker's site the
moment its home page expanded into thirty links, which is how a harvest gets a host to
start returning 429 and then reads the 429s as "this company publishes nothing".

WHAT A WORKER DOES WITH A PAGE
------------------------------
`home` is the important one: it is expanded from the site's OWN link graph into the real
per-need tasks, and only the needs that graph did not cover fall back to a guessed path.
Everything else is stored as text against (company, need) for the extractors to read.

Nothing here decides what a fact IS. The worker's whole job is to bring back pages and to
be honest about which ones it failed to bring back.
"""
import argparse
import os
import re
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clean as C                                   # noqa: E402
import fetch as F                                   # noqa: E402
import targets as T                                 # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = T.DSN
POLITE_S = float(os.environ.get("HARVEST_DELAY_S", "1.5"))
MAX_PER_NEED = 4


def log(wid, msg):
    print("[w%s %s] %s" % (wid, time.strftime("%H:%M:%S"), msg), flush=True)


def claim(cx, wid, of, worker_name):
    """Take one pending task from this worker's shard.

    FOR UPDATE SKIP LOCKED is what makes several instances safe against each other: two
    workers asking at the same instant get different rows instead of both running the
    same URL and both writing it.
    """
    with cx.cursor() as cur:
        cur.execute("""
            update harvest.task set state='running', worker=%s, started_at=now()
            where task_id = (
                select task_id from harvest.task
                where state='pending' and (abs(hashtext(cid)) %% %s) = %s
                order by priority, task_id
                for update skip locked limit 1)
            returning task_id, cid, company, need, url, how
        """, (worker_name, of, wid))
        row = cur.fetchone()
    cx.commit()
    return row


def finish(cx, task_id, state, page=None, reason=""):
    with cx.cursor() as cur:
        cur.execute("""update harvest.task set state=%s, via=%s, status=%s, chars=%s,
                       reason=%s, ended_at=now() where task_id=%s""",
                    (state, (page or {}).get("via"), (page or {}).get("status") or 0,
                     len((page or {}).get("text") or ""), reason[:400], task_id))
    cx.commit()


_HOME = {}


def _home_md5(cx, cid):
    """This company's home-page fingerprint, so a page that IS the home page cannot be
    filed as its leadership page."""
    if cid not in _HOME:
        with cx.cursor() as cur:
            cur.execute("select text from harvest.page where cid=%s and need='home' "
                        "order by page_id limit 1", (cid,))
            r = cur.fetchone()
        _HOME[cid] = C.md5(r[0]) if r else ""
    return _HOME[cid]


def store_page(cx, task_id, cid, need, page):
    with cx.cursor() as cur:
        cur.execute("""insert into harvest.page (task_id, cid, need, url, final_url,
                       via, status, text) values (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (task_id, cid, need, page["url"], page.get("final_url"),
                     page.get("via"), page.get("status") or 0,
                     (page.get("text") or "")[:400000]))
    cx.commit()


def expand_home(cx, cid, company, site, html):
    """Turn a home page into the per-need work queue. Returns how many tasks were added."""
    found = T.links_for_needs(html, site)
    added = 0
    with cx.cursor() as cur:
        for need, (prio, _) in T.NEEDS.items():
            urls = (found.get(need) or [])[:MAX_PER_NEED]
            how = "link"
            if not urls:
                urls = [T.urllib.parse.urljoin(site, p) for p in T.GUESS.get(need, ())[:3]]
                how = "guess"
            for u in urls:
                cur.execute("""insert into harvest.task (cid, company, need, url, how,
                               priority) values (%s,%s,%s,%s,%s,%s)
                               on conflict do nothing""",
                            (cid, company, need, u, how, prio))
                added += cur.rowcount
    cx.commit()
    return added


def handle_brochure(cx, cid, company, page):
    """A PDF catalogue is read by the reader that was built for exactly this, rather than
    stored as text — its value is a spec TABLE, and flattening it to text loses the
    label/value pairing that makes it usable."""
    sys.path.insert(0, str(HERE.parent))
    import fetch_brochures as FB
    recs = FB.read_pdf(page["bytes"], page["url"])
    if not recs:
        return 0
    n = 0
    with cx.cursor() as cur:
        for r in recs:
            for sp in r["specs"]:
                cur.execute("""insert into harvest.fact
                    (cid, company, field, value, detail, url, line)
                    values (%s,%s,'product_spec',%s,%s,%s,%s)
                    on conflict do nothing""",
                            (cid, company,
                             "%s :: %s" % (r["product"] or "?", sp["label"]),
                             sp["value"], page["url"], sp["line"]))
                n += cur.rowcount
    cx.commit()
    return n


def run(wid, of, once=False, budget_s=None):
    import psycopg2 as pg
    worker_name = "w%d/%d" % (wid, of)
    started = time.time()
    cx = pg.connect(DSN, connect_timeout=15)
    done = failed = 0
    last_host = {}
    while True:
        if budget_s and time.time() - started > budget_s:
            log(wid, "budget reached, stopping")
            break
        row = claim(cx, wid, of, worker_name)
        if not row:
            if once:
                break
            log(wid, "queue empty for this shard; idling")
            time.sleep(20)
            continue
        task_id, cid, company, need, url, how = row

        # politeness, per host, inside this process - see the module docstring
        h = T.host_of(url)
        wait = POLITE_S - (time.time() - last_host.get(h, 0))
        if wait > 0:
            time.sleep(wait)
        last_host[h] = time.time()

        try:
            page = F.get(url)
        except Exception:
            finish(cx, task_id, "failed", None, traceback.format_exc(limit=2))
            failed += 1
            continue

        if not page.ok:
            # `blocked` is retryable and is NOT a verdict about the URL. A 969-char WAF
            # block was once recorded here as permanent and the same URL later returned
            # 353k chars through the host solver.
            state = "blocked" if page.get("reason") == "blocked" else "failed"
            finish(cx, task_id, state, page, page.get("reason", ""))
            failed += 1
            log(wid, "%-7s %-9s %s  %s" % (state, need, page.get("reason", "")[:24], url[:64]))
            continue

        extra = ""
        if page.get("bytes"):
            try:
                n = handle_brochure(cx, cid, company, page)
                extra = " %d specs" % n
            except Exception as e:
                extra = " pdf unread (%s)" % type(e).__name__
        else:
            # A 200 is not proof the page exists. Sitecore answers every unknown path
            # with a 200 error page, and one maker's guessed paths silently redirect to
            # the homepage - 35 pages were stored as leadership/facilities/products
            # before this check existed, and seven of one company's nine "covered" needs
            # were entirely fabricated.
            why = C.verdict({"need": need, "url": url,
                             "final_url": page.get("final_url") or "",
                             "text": page.get("text") or ""}, _home_md5(cx, cid))
            if why:
                finish(cx, task_id, "failed", page, why)
                failed += 1
                log(wid, "reject  %-9s %-26s %s" % (need, why[:26], url[:52]))
                continue
            store_page(cx, task_id, cid, need, page)
            if need == "home":
                added = expand_home(cx, cid, company, page.get("final_url") or url,
                                    page.get("html") or "")
                extra = " +%d tasks" % added
        finish(cx, task_id, "done", page)
        done += 1
        log(wid, "ok      %-9s %-4s %6d ch %s%s"
            % (need, page["via"], len(page.get("text") or ""), url[:58], extra))
        if once:
            break
    cx.close()
    log(wid, "stopped: %d done, %d failed" % (done, failed))


def demo():
    # sharding must be stable and must cover every shard index
    import hashlib
    def shard(cid, of):
        return int(hashlib.md5(cid.encode()).hexdigest(), 16) % of
    assert shard("abc", 6) == shard("abc", 6), "sharding must be deterministic"
    # the real shard uses Postgres hashtext(); what matters here is the INVARIANT that a
    # company is only ever claimed by one worker, which the SQL enforces by construction.
    seen = {shard("c%d" % i, 6) for i in range(200)}
    assert len(seen) == 6, "every shard must get work: %s" % seen
    assert MAX_PER_NEED >= 1
    assert POLITE_S > 0, "a zero delay makes one worker look like a small DDoS"
    print("worker demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--budget", type=float)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        run(a.id, a.of, a.once, a.budget)
