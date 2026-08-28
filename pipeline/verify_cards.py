"""Entailment check over pipeline cards -- the last gate before a card stays on the UI.

    python verify_cards.py            # judge every pipeline card, delete unsupported
    python verify_cards.py --dry      # judge and report, delete nothing
    python verify_cards.py --demo

A card's title and so-what are LLM assertions; the extractor grounded the QUOTES,
not the assertion built on them. This asks the 14b, per card, whether the quotes
actually SUPPORT the card's claim (the L2 post-mortem: existence of evidence is
not entailment). Unsupported cards are deleted and counted -- an audit trail line
per deletion, never a silent disappearance.
"""
import argparse
import json
import os
import sys
import urllib.request

DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
OLLAMA = os.environ.get("KSSL_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("KSSL_MODEL", "qwen2.5:14b-instruct")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROMPT = """You are verifying a competitive-intelligence card against its evidence.

CARD CLAIM:
Title: %s
Why it matters: %s

EVIDENCE (verbatim quotes from the source article):
%s

Question: do the quotes SUPPORT the card? Judge in two parts:
1. The TITLE's facts (who, what, numbers) must be stated or directly implied by
   the quotes -- not merely the same company or topic. A title that upgrades the
   claim (announced -> delivered, plan -> contract, talks -> order, concept ->
   product) is NOT supported.
2. The why-it-matters is an analyst's reading; it may INFER significance from
   those facts. Reject it only if it asserts facts the quotes contradict or
   do not contain at all.
Reply with exactly one line:
SUPPORTED
or
UNSUPPORTED: <one short reason>"""




# Where the model runs. Defaults are unchanged; the env vars exist so a fill can be
# pushed off the GPU when the extraction owns it (num_gpu=0 -> CPU/RAM inference).
# num_ctx is ALWAYS set explicitly: a model whose default context is 262k asks ollama
# for a 95 GB KV cache and the request dies as an opaque HTTP 500.
def llm_opts(npredict):
    o = {"temperature": 0, "num_predict": npredict, "num_ctx": int(os.environ.get("KSSL_NUM_CTX", 8192))}
    if os.environ.get("KSSL_LLM_CPU") == "1":
        o["num_gpu"] = 0
    return o


def ask(prompt, timeout=120):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": llm_opts(80)})
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body.encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "").strip()


def parse_verdict(raw):
    """-> (ok: bool|None, reason). None = unparseable (counted, never deleted on)."""
    line = (raw or "").strip().splitlines()[0].strip() if (raw or "").strip() else ""
    up = line.upper()
    if up.startswith("SUPPORTED"):
        return True, ""
    if up.startswith("UNSUPPORTED"):
        return False, line.split(":", 1)[1].strip() if ":" in line else ""
    return None, line[:80]


def verify(dsn=DSN, dry=False):
    import psycopg2
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("""SELECT c.id, c.title, c.sowhat, d.lens
                     FROM serving.signal_card c JOIN serving.signal_detail d ON d.id = c.id
                    WHERE c.origin = 'pipeline' ORDER BY c.ord""")
    rows = cur.fetchall()
    stats = {"supported": 0, "deleted": 0, "unclear": 0}
    for cid, title, sowhat, lens in rows:
        quotes = "\n".join("- %s" % r[1] for r in (lens or []) if len(r) > 1)[:3000]
        if not quotes:
            stats["unclear"] += 1
            continue
        ok, reason = parse_verdict(ask(PROMPT % (title, sowhat, quotes)))
        if ok:
            stats["supported"] += 1
        elif ok is False:
            print("UNSUPPORTED %s: %s -- %s" % (cid, title[:60], reason), flush=True)
            if not dry:
                cur.execute("DELETE FROM serving.signal_detail WHERE id=%s", (cid,))
                cur.execute("DELETE FROM serving.signal_card WHERE id=%s", (cid,))
                con.commit()
            stats["deleted"] += 1
        else:
            # an unparseable verdict must never delete a card
            print("UNCLEAR %s: %s" % (cid, reason), flush=True)
            stats["unclear"] += 1
    con.close()
    print("verified: %(supported)d supported, %(deleted)d unsupported%(sfx)s, "
          "%(unclear)d unclear (kept)" % dict(stats, sfx=" (dry, kept)" if dry else
                                              " (deleted)"), flush=True)
    return stats


def _demo():
    assert parse_verdict("SUPPORTED") == (True, "")
    assert parse_verdict("supported.") == (True, "")
    ok, why = parse_verdict("UNSUPPORTED: quote only mentions the company")
    assert ok is False and "mentions" in why
    assert parse_verdict("Maybe?")[0] is None, "garbage must not delete"
    assert parse_verdict("")[0] is None
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        verify(a.dsn, dry=a.dry)
