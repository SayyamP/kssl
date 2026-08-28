"""Pull newly-crawled defence documents out of the data-centre corpus into the
extraction queue.

    python pipeline/pull_corpus.py --since 2026-08-25 --limit 200

This is the join the pipeline was missing. `fetch_corpus.py` pulls RSS directly
and writes corpus/doc_*.json; the crawler fleet writes 1.2M documents into the
data-centre Postgres; and until now nothing connected the two, so nothing the
crawler fetched ever reached extraction.

THREE THINGS THIS IS CAREFUL ABOUT
----------------------------------
* **It never scans the big columns.** `documents` is 81 GB and almost all of
  that is `html`/`main_text` in TOAST. Selecting or ordering by them detoasts
  the table and has taken the corpus offline before. The candidate query touches
  only small columns and `text_len`; the text is fetched per chosen row.
* **It is a gate, not a firehose.** A page is a candidate only if it is recent,
  long enough to carry a claim, and mentions something the dashboard is about --
  the client, a known competitor, or defence procurement vocabulary. Everything
  else is counted out, not silently dropped.
* **It is idempotent.** Documents already staged, and documents already in
  `extracted.document`, are skipped, so re-running tops up rather than
  duplicating.

Reaches the corpus through the SSH tunnel (see docker-compose.tunnel.yml), so
the corpus port never leaves the data centre.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage_timer                                      # noqa: E402

try:
    import psycopg2 as pg
except ImportError:                                     # pragma: no cover
    try:
        import psycopg as pg                            # noqa: N813
    except ImportError:
        sys.exit("no postgres driver: python -m pip install psycopg2-binary")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def load_env():
    """Read ../.env directly, rather than having a shell source it.

    `set -a; . ./.env` looks convenient and is a trap: these values contain
    shell metacharacters, so the shell either fails to parse the file or -- worse
    -- expands part of a password. Reading the file here keeps every value
    literal and keeps secrets off the command line.
    """
    p = Path(__file__).parent.parent / ".env"
    if not p.exists():
        return
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

CORPUS_DSN = os.environ.get(
    "KSSL_CORPUS_DSN",
    "host=127.0.0.1 port=15432 dbname=mallory user=mallory password=")
KSSL_DSN = os.environ.get(
    "KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
CORPUS_DIR = HERE / "corpus"

# A document must be long enough to carry a grounded claim. Below this it is a
# nav page, a stub or a redirect notice -- extraction on it costs a full model
# pass and yields nothing.
MIN_TEXT = int(os.environ.get("KSSL_MIN_TEXT", "700"))

# How many candidate rows to consider per document kept. The gate refuses
# most of what the crawler fetches -- defence trade press still carries a lot
# of aviation, space and general politics -- so a small factor silently
# starves the run: asking for 14 documents scanned 84 rows and kept 1.
# These are small columns, so a wide scan is cheap; the text is only read
# for rows that pass.
CANDIDATE_FACTOR = int(os.environ.get("KSSL_CANDIDATE_FACTOR", "60"))

# --- the relevance gate -------------------------------------------------------
# Whole words, not substrings: 'isr' inside 'Israel' and 'sam' inside 'Samsung'
# are the mistakes this project has already made. Numeric terms keep their units
# so '155' still matches '155mm'.
CLIENT = ["kalyani", "bharat forge", "kssl", "kalyani strategic"]

RIVALS = [
    "bae systems", "rheinmetall", "hanwha", "nexter", "kndsleonardo", "knds",
    "leonardo", "elbit", "iai", "saab", "thales", "general dynamics",
    "bofors", "denel", "norinco", "rostec", "tata advanced", "larsen",
    "mahindra defence", "adani defence", "bharat electronics", "drdo",
    "ordnance factory", "munitions india", "yantra india",
]

DEFENCE = [
    "artillery", "howitzer", "gun system", "ammunition", "ordnance",
    "armoured", "armored", "infantry combat vehicle", "mine protected",
    "tender", "procurement", "contract award", "request for proposal",
    "defence ministry", "ministry of defence", "defense ministry",
    "indigenisation", "indigenization", "emergency procurement",
    "artillery gun", "atags", "155mm", "105mm", "mrsi", "towed gun",
    "self-propelled", "protected vehicle", "small arms", "drone", "loitering",
]


def _rx(terms):
    """One word-boundary regex per bucket. A numeric term keeps its unit."""
    parts = []
    for t in terms:
        lit = re.escape(t)
        tail = r"(?![0-9])" if t[-1].isdigit() else r"(s|es)?\b"
        parts.append(r"\b" + lit + tail)
    return re.compile("|".join(parts), re.I)


RX_CLIENT, RX_RIVAL, RX_DEFENCE = _rx(CLIENT), _rx(RIVALS), _rx(DEFENCE)

_LISTING = None


def classify(text, title):
    """Why this document is (or is not) a candidate. Returns (keep, reason)."""
    blob = "%s\n%s" % (title or "", text or "")
    hits = []
    if RX_CLIENT.search(blob):
        hits.append("client")
    if RX_RIVAL.search(blob):
        hits.append("competitor")
    if RX_DEFENCE.search(blob):
        hits.append("defence")
    if not hits:
        return False, "no client, competitor or defence term"
    # A defence word alone is weak -- half the trade press says "procurement".
    # Require either a named organisation, or defence vocabulary in the TITLE.
    if hits == ["defence"] and not RX_DEFENCE.search(title or ""):
        return False, "defence vocabulary in body only, no named organisation"
    return True, "+".join(hits)



def _is_listing(url):
    """serving_fill's own listing test, imported rather than re-implemented.

    Falls back to False if that module cannot be imported (it pulls in the
    reference dataset), so selection still works standalone.
    """
    global _LISTING
    if _LISTING is None:
        try:
            from serving_fill import is_listing as _f
            _LISTING = _f
        except Exception:                               # noqa: BLE001
            _LISTING = lambda _u: False                 # noqa: E731
    return _LISTING(url)


def staged_ids():
    """Documents already written to corpus/, so a re-run tops up."""
    out = set()
    if CORPUS_DIR.exists():
        for p in CORPUS_DIR.glob("doc_*.json"):
            out.add(p.stem[4:])
    return out


def extracted_ids():
    """Documents already through Layer A. Skipping them is the whole reason a
    second run is cheap."""
    try:
        with pg.connect(KSSL_DSN, connect_timeout=8) as cx:
            with cx.cursor() as cur:
                cur.execute("SELECT document_id FROM extracted.document")
                return {r[0] for r in cur.fetchall()}
    except Exception as exc:                            # noqa: BLE001
        print("  (could not read extracted.document: %s)" % str(exc)[:90])
        return set()



class BodyReader(object):
    """One reconnecting connection for the per-document body reads.

    The candidate rows are already in memory by the time the loop starts, so the
    corpus is needed only for main_text -- but it is needed for as long as the
    pull runs, which on a four-thousand-document pull is tens of minutes. A
    single connection held open that long through the SSH tunnel is exactly what
    dropped mid-run and took the whole batch with it. Losing the connection is
    not an error worth failing a run over; it is a thing to reconnect through.
    """

    def __init__(self):
        self.cx = None
        self.drops = 0

    def _cursor(self):
        if self.cx is None or self.cx.closed:
            self.cx = pg.connect(CORPUS_DSN, connect_timeout=15)
        return self.cx.cursor()

    def text(self, doc_id):
        for attempt in (1, 2, 3):
            try:
                cur = self._cursor()
                cur.execute(
                    "SELECT main_text FROM documents WHERE document_id = %s",
                    (doc_id,))
                got = cur.fetchone()
                cur.close()
                return (got[0] if got else None) or ""
            except (pg.OperationalError, pg.InterfaceError) as exc:
                if self.cx is not None:
                    try:
                        self.cx.close()
                    except Exception:                   # noqa: BLE001
                        pass
                self.cx = None
                self.drops += 1
                if attempt == 3:
                    raise
                print("  corpus connection lost (%s) -- reconnecting"
                      % str(exc).strip().splitlines()[0][:58])
                time.sleep(2 * attempt)

    def close(self):
        if self.cx is not None:
            try:
                self.cx.close()
            except Exception:                           # noqa: BLE001
                pass
            self.cx = None


def write_staged(doc):
    """Put one document on disk. Called the moment it is kept, never later."""
    p = CORPUS_DIR / ("doc_%s.json" % doc["document_id"])
    io.open(p, "w", encoding="utf-8", newline="").write(
        json.dumps(doc, ensure_ascii=False))
    return p


def pull(since, limit, dry_run=False, dated_only=True,
         published_since=None):
    CORPUS_DIR.mkdir(exist_ok=True)
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    have = staged_ids() | extracted_ids()
    print("already staged or extracted: %d" % len(have))
    body = BodyReader()

    with stage_timer.stage("select", note="corpus -> extraction queue") as st:
        with pg.connect(CORPUS_DSN, connect_timeout=15) as cx:
            with cx.cursor() as cur:
                # SMALL COLUMNS ONLY. text_len is a stored integer; length(main_text)
                # here would decompress every row and take the corpus down.
                # dated_only: take only documents whose publication date the
                # CRAWLER proved from the page's own metadata. Downstream, a
                # document with no proven publish date is refused anyway -- the
                # body's Date spans are about the article's subject ('January
                # 2022'), not about the article -- so pulling undated documents
                # spends a full extraction pass on something that can never
                # become a card. Fetch date is NOT a substitute: an old article
                # can be fetched today.
                where = "ingested_at >= %s AND text_len >= %s"
                params = [since, MIN_TEXT]
                if dated_only:
                    where += " AND published_at IS NOT NULL AND published_at <> ''"
                    # A publication date in the FUTURE is a misparse, not news.
                    # The corpus has plenty (a DD/MM read as MM/DD, a "next
                    # issue" date in the byline), and ordering by published_at
                    # DESC puts every one of them at the front of the queue --
                    # so this guard is what stops the freshest-looking documents
                    # being the most broken ones.
                    where += " AND published_at <= %s"
                    params.append(datetime.now(timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%SZ"))
                if published_since:
                    # Ingest date is when WE fetched it; publication date is what
                    # the recency gate downstream actually judges. Filtering on
                    # ingest alone happily returns a 2017 article fetched today,
                    # and every one of those costs a full extraction pass before
                    # being refused.
                    where += " AND published_at >= %s"
                    params.append(published_since)
                cur.execute(
                    "SELECT document_id, url, title, source_id, published_at,"
                    "       ingested_at, language, text_len "
                    "FROM documents "
                    "WHERE " + where + " "
                    "ORDER BY published_at DESC NULLS LAST "
                    "LIMIT %s",
                    params + [limit * CANDIDATE_FACTOR])
                rows = cur.fetchall()
                print("candidate rows in window: %d" % len(rows))

                kept, counted_out, written = 0, {}, []
                for (doc_id, url, title, source_id, published_at,
                     ingested_at, lang, tlen) in rows:
                    if kept >= limit:
                        break
                    if doc_id in have:
                        counted_out["already have"] = counted_out.get("already have", 0) + 1
                        continue
                    text = body.text(doc_id)
                    if len(text) < MIN_TEXT:
                        counted_out["too short"] = counted_out.get("too short", 0) + 1
                        continue
                    # A listing page is refused downstream anyway ("a card built
                    # from one conflates stories"), and finding that out costs a
                    # full extraction pass -- minutes of model time per page. The
                    # same detector the serving stage uses is applied here, so
                    # the two cannot disagree about what a listing is.
                    # A SECOND, CLIENT-SIDE future-date refusal. The SQL guard above
                    # already excludes these, yet twelve infodefensa rows dated
                    # 2026-12-30 -- four months ahead of a corpus whose newest article is
                    # from August -- were sitting in corpus/ from an earlier pull. A date
                    # in the future is a misparse of a DD-MM surface, not news, and
                    # ordering by published_at DESC puts every one of them at the FRONT of
                    # the queue. Cheap to check here, and it also cleans a directory
                    # staged before the SQL guard existed.
                    if published_at and str(published_at)[:10] > _today:
                        counted_out["published in the future (misparsed date)"] =                             counted_out.get("published in the future (misparsed date)", 0) + 1
                        continue
                    if _is_listing(url):
                        counted_out["listing / index page"] =                             counted_out.get("listing / index page", 0) + 1
                        continue
                    ok, why = classify(text, title)
                    if not ok:
                        counted_out[why] = counted_out.get(why, 0) + 1
                        continue

                    doc = {
                        "document_id": doc_id,
                        "url": url,
                        "title": title or "",
                        "text": text,
                        "source_id": source_id,
                        "published_at": published_at,
                        "fetched_at": ingested_at,
                        "language": lang,
                        "gate": why,
                    }
                    # Write NOW, not after the loop. The deferred write meant
                    # a connection lost at document 3,900 discarded all 3,900 --
                    # a full pull that read for forty minutes and staged zero.
                    if not dry_run:
                        write_staged(doc)
                    written.append(doc)
                    kept += 1

        body.close()
        st.items(kept)

    print("")
    print("  kept          %d%s" % (kept, "  (dry run, nothing written)" if dry_run else ""))
    for why, n in sorted(counted_out.items(), key=lambda kv: -kv[1]):
        print("  counted out   %-52s %d" % (why, n))
    if written:
        by_gate = {}
        for d in written:
            by_gate[d["gate"]] = by_gate.get(d["gate"], 0) + 1
        print("")
        for g, n in sorted(by_gate.items(), key=lambda kv: -kv[1]):
            print("  gate %-20s %d" % (g, n))
        print("")
        print("  example: %s" % written[0]["url"][:110])
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="ISO date; default is the last 24 hours")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--published-since", default=None,
                    help="ISO date; only articles PUBLISHED on or after this. "
                         "This is what the recency gate judges.")
    ap.add_argument("--any-date", action="store_true",
                    help="also take documents with no proven publish "
                         "date. They will almost all be refused later.")
    a = ap.parse_args()
    since = a.since or (datetime.now(timezone.utc) - timedelta(days=1)
                        ).strftime("%Y-%m-%d")
    print("pulling documents ingested since %s (limit %d, min %d chars)"
          % (since, a.limit, MIN_TEXT))
    n = pull(since, a.limit, a.dry_run, dated_only=not a.any_date,
             published_since=a.published_since)
    if not n:
        print("\nnothing matched -- widen --since, or the gate is too tight")
    return 0


def _selfcheck():
    """The gate is the risky part: prove it accepts and rejects for the right
    reasons before it decides what the dashboard is built from."""
    ok, why = classify("Bharat Forge won an order for 155mm artillery.", "Order")
    assert ok and "client" in why, why

    ok, why = classify("Rheinmetall opened a new ammunition plant.", "Plant")
    assert ok and "competitor" in why, why

    # defence vocabulary in the body only, no organisation -> refused
    ok, why = classify("The council debated procurement of new bin lorries.", "Bins")
    assert not ok, why

    # ...but the same vocabulary in the TITLE passes
    ok, _ = classify("The ministry issued a tender.", "Defence ministry tender")
    assert ok

    # substrings must not match: this is the recurring bug in this codebase
    ok, why = classify("Samsung and Israel both appear here.", "Tech")
    assert not ok, "substring match: %s" % why

    # A numeric term keeps its unit. Tested on the regex directly: classify()
    # would also apply the title rule, which would hide what is being checked.
    assert RX_DEFENCE.search("the 155mm round"), "155mm should match"
    assert not RX_DEFENCE.search("there were 1550 people"), "155 matched in 1550"
    assert not RX_DEFENCE.search("model 3155mm"), "155mm matched mid-number"

    # and a document carrying both a calibre and a title term is kept
    ok, _ = classify("The 155mm round was fired.", "New artillery round")
    assert ok

    print("pull_corpus gate self-check ok")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        sys.exit(main())
