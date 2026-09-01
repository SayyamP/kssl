"""The article's stored HTML, from the data-centre corpus.

`extracted.document` keeps the article's TEXT but not its markup, and the markup
is where the publisher states the things the dashboard needs: when the story was
published, and which picture it ran with. Both come from one fetch through here,
so a card costs a single corpus round-trip rather than one per field.

NOTHING here may stop a card being written. The corpus is on another machine at
the end of an SSH tunnel; if it is down, slow, or the page was crawled without
markup, the caller gets None and the card goes out without that field.

The breaker is TIME-BOXED, never a permanent latch. A run lasts an hour and the
tunnel will drop at some point during it; a latch that never reopens turns one
blip into a whole run with no dates and no pictures. That is not hypothetical --
it happened on the first production run, at 10:25, and every card after it went
out imageless.
"""
import os
import time

__all__ = ["fetch_html", "state", "reset"]

# The data-centre corpus over the tunnel the feeder already uses.
DSN = os.environ.get("KSSL_CORPUS_SRC_DSN", "")
ENABLED = os.environ.get("KSSL_CORPUS_HTML", "1") not in ("0", "false", "no")
BACKOFF_S = float(os.environ.get("KSSL_CORPUS_BACKOFF_S", "60"))
STATEMENT_TIMEOUT_MS = int(os.environ.get("KSSL_CORPUS_STATEMENT_TIMEOUT_MS", "15000"))
# Persistent query-level failures (a poisoned row, a server-side timeout, lost
# permissions) used to cost every card two failed queries and two reconnects,
# for ever, with `state()` reporting nothing wrong: the breaker only counted
# CONNECT failures. This many consecutive query failures now trips it too.
QFAIL_TRIP = int(os.environ.get("KSSL_CORPUS_QFAIL_TRIP", "5"))

_S = {"con": None, "retry_at": 0.0, "fails": 0, "why": "", "hits": 0, "misses": 0,
      "qfails": 0}

# A card asks for the same document twice -- once for its date, once for its
# picture. Without this the 219 GB `documents` row is detoasted twice per card.
# One entry deep: the caller works through documents one at a time, so a bigger
# cache would only hold rows nothing will ask for again.
_LAST = {"did": None, "url": None, "html": None}


def state():
    """A snapshot for logging; never raises."""
    return dict(_S, con=bool(_S["con"]), enabled=bool(ENABLED and DSN))


def reset():
    """Drop the connection so the next call reconnects. Used by tests."""
    con, _S["con"] = _S["con"], None
    try:
        if con is not None:
            con.close()
    except Exception:                                                # noqa: BLE001
        pass


def _connect():
    if not (ENABLED and DSN):
        return None
    if _S["con"] is not None:
        return _S["con"]
    if time.time() < _S["retry_at"]:
        return None                                                  # backing off
    try:
        import psycopg2
        # Without keepalives an idle connection through the tunnel is reaped
        # silently and only fails on the next query, mid-card.
        # connect_timeout only guards the handshake. A server that accepts the
        # connection and then never answers -- the wedged-sshd / middlebox case
        # this tunnel actually meets -- would block the card loop forever, and a
        # hang is worse than an error because the breaker never sees it. The
        # statement timeout is what makes "never stops a card" true.
        _S["con"] = psycopg2.connect(
            DSN, connect_timeout=10, keepalives=1, keepalives_idle=30,
            keepalives_interval=10, keepalives_count=3,
            options="-c statement_timeout=%d" % int(STATEMENT_TIMEOUT_MS))
        if _S["fails"]:
            print("  corpus: back after %d failure(s)" % _S["fails"], flush=True)
            _S["fails"] = 0
        return _S["con"]
    except Exception as e:                                           # noqa: BLE001
        _S["fails"] += 1
        _S["why"] = "%s: %s" % (type(e).__name__, e)
        _S["retry_at"] = time.time() + BACKOFF_S
        print("  corpus unreachable, pausing %ds: %s" % (int(BACKOFF_S), _S["why"]),
              flush=True)
        return None


def fetch_html(document_id):
    """-> (url, html) for one document, or (None, None). Never raises.

    One retry on a dead connection: the usual failure is a socket the tunnel
    dropped while we were doing something else, and it costs a reconnect rather
    than the card's date and picture.
    """
    if _LAST["did"] == document_id:
        return _LAST["url"], _LAST["html"]
    for attempt in (1, 2):
        con = _connect()
        if con is None:
            return None, None
        try:
            cur = con.cursor()
            # By primary key, so `html` is detoasted for this row alone.
            # `documents` is 219 GB of mostly html -- anything that scans or
            # sorts on it takes the corpus offline.
            cur.execute("SELECT url, html FROM documents WHERE document_id = %s",
                        (document_id,))
            row = cur.fetchone()
            con.commit()
            _S["qfails"] = 0
            url, html = (row[0], row[1]) if row else (None, None)
            if html:
                _S["hits"] += 1
            else:
                _S["misses"] += 1
            _LAST.update(did=document_id, url=url, html=html)
            return url, html
        except Exception as e:                                       # noqa: BLE001
            reset()
            if attempt == 1:
                continue                                             # reconnect, retry once
            _S["qfails"] += 1
            _S["why"] = "query: %s: %s" % (type(e).__name__, e)
            if _S["qfails"] >= QFAIL_TRIP:
                # Queries keep failing on a connection that keeps succeeding.
                # Back off rather than paying two failures per card for ever.
                _S["retry_at"] = time.time() + BACKOFF_S
                _S["qfails"] = 0
                print("  corpus queries failing, pausing %ds: %s"
                      % (int(BACKOFF_S), _S["why"]), flush=True)
            else:
                print("  corpus read failed for %s: %s" % (document_id, e), flush=True)
            return None, None
    return None, None
