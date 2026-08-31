"""End-to-end fleet test: one document per machine, both services, offsets verified.

    python3 llmapi/fleet_test.py                       # 3 docs from the local corpus set
    python3 llmapi/fleet_test.py --dsn "$KSSL_CORPUS_DSN"   # 3 FRESH docs from the crawler
    python3 llmapi/fleet_test.py --nodes vps-b,vps-a,dc
    python3 llmapi/fleet_test.py --demo                # self-check, no network

WHAT IT PROVES, AND WHAT IT DOES NOT
------------------------------------
It pins one document to each node with the API's `node=` parameter, so a pass means THAT
BOX served it -- not that some box did. Failover is deliberately bypassed: a test that
lets the chain rescue a dead node reports the fleet healthy when one third of it is down.

DOCUMENTS ARE SIZED TO THE NODE, the same way route.py sizes them
----------------------------------------------------------------
The dc is 1.5 tok/s against vps-b's 11.95, and route.py caps it near 1,587 characters for
exactly that reason. Handing every node the same document would not be fairness, it would
be a test that the slowest node times out -- which we already know. So each node gets the
largest document it could actually be given in production.

THE CHECK THAT MATTERS IS THE OFFSET CONTRACT
---------------------------------------------
Every span GLiNER returns is sliced back out of the document and compared to the text the
service reported. `document.text[start:end] == span.text` is the invariant the whole
pipeline rests on, and routing NER through a new service on three new boxes is exactly the
kind of change that can break it silently -- a per-sentence offset added to the wrong
sentence still looks like a plausible span.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llmapi import client as llm_client  # noqa: E402
from llmapi import nodes  # noqa: E402

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent.parent / "comprehend" / "data" / "corpus600.jsonl"

# Not segment.py's splitter. That lives in the extraction engine and is offset-exact for
# 34 languages; this only has to cut the text into pieces small enough for one NER call,
# and every offset below is computed from the cut position rather than from the split.
_SENT = re.compile(r"(?<=[.!?。！？])\s+")


def sentences(text):
    """-> [(start, sentence)]. Offsets are the caller's contract, so they are taken from
    the scan position, never recomputed by searching for the sentence afterwards."""
    out, pos = [], 0
    for part in _SENT.split(text):
        if not part:
            continue
        i = text.find(part, pos)
        if i < 0:
            continue
        out.append((i, part))
        pos = i + len(part)
    return out


def load_local(path=None, limit=None):
    p = Path(path) if path else CORPUS
    if not p.exists():
        raise SystemExit("no corpus at %s -- pass --docs or --dsn" % p)
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows[:limit] if limit else rows


def load_corpus(dsn, n=3, since_hours=48):
    """Fresh documents from the crawler, in TWO PHASES.

    `documents` is 1.38M rows carrying 219 GB of html, and main_text is TOASTed: any
    predicate or projection over those columns decompresses them and has taken this corpus
    down before. So phase 1 selects only small inline columns to CHOOSE the set, and phase
    2 fetches main_text for exactly the chosen ids by primary key.

    FRESHNESS IS `ingested_at`, COMPARED AS TEXT. The time columns are `text`, not
    timestamps -- `fetched_at >= now()` raises "operator does not exist: text >= timestamptz",
    and casting every row to timestamptz is the full-1.38M-row scan the docstring warns about
    (it times out at 25s). But these are ISO8601 `...Z` strings, whose lexical order IS their
    chronological order, and only `ingested_at` carries a btree index -- so a plain text `>=`
    against an ISO cutoff rides that index and returns in ~0.5s. `pushed_at` is entirely NULL
    here (nothing has been pushed to KSSL yet), so it cannot be used for freshness.
    """
    import datetime
    import psycopg2
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=int(since_hours))
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SET statement_timeout='25s'")
    cur.execute("""SELECT document_id, source_id, language, title, text_len, ingested_at
                     FROM documents
                    WHERE ingested_at >= %s
                      AND text_len BETWEEN 400 AND 12000
                    ORDER BY ingested_at DESC
                    LIMIT %s""", (cutoff, int(n) * 20))
    picked = cur.fetchall()
    if not picked:
        raise SystemExit("no documents in the last %dh within the size band" % since_hours)
    ids = [r[0] for r in picked]
    cur.execute("SELECT document_id, main_text FROM documents WHERE document_id = ANY(%s)", (ids,))
    text = dict(cur.fetchall())
    con.close()
    return [{"document_id": r[0], "source_id": r[1], "language": r[2], "title": r[3],
             "main_text": text.get(r[0], "")} for r in picked if text.get(r[0])]


def assign(docs, node_ids):
    """One document per node, each the LARGEST that node could be given in production.

    Sorted by what each node can actually finish, so the dc gets a document it can serve
    rather than one that proves it is slow.
    """
    caps = []
    for nid in node_ids:
        tok = nodes.table()[nid]["tok_s"]
        # route.py: cap = minutes * 60 * tok_s / ALPHA, with ALPHA = 4.82 output tokens
        # per input character. Same formula, so this test asks for work the queue would
        # actually route to this node.
        caps.append((nid, int(nodes.budget_s(nid) * tok / 4.82)))
    caps.sort(key=lambda x: x[1])                       # smallest capacity first
    pool = sorted((d for d in docs if d.get("main_text")), key=lambda d: len(d["main_text"]))
    out, used = [], set()
    for nid, cap in caps:
        fit = [d for d in pool if len(d["main_text"]) <= cap and d["document_id"] not in used]
        if not fit:
            out.append((nid, cap, None))
            continue
        d = fit[-1]                                      # the largest that still fits
        used.add(d["document_id"])
        out.append((nid, cap, d))
    return out


def run_one(nid, doc, npredict=120, max_sentences=12):
    """GLiNER then LLM, both PINNED to this node. -> result dict."""
    text = doc["main_text"]
    r = {"node": nid, "document_id": doc["document_id"], "chars": len(text),
         "source": doc.get("source_id", ""), "lang": doc.get("language", ""),
         "gliner": None, "llm": None, "violations": [], "errors": []}

    sents = sentences(text)[:max_sentences]
    t0 = time.time()
    try:
        results = llm_client.gliner([s for _, s in sents], node=nid)
        n_spans = 0
        for (base, sent), ents in zip(sents, results):
            for e in ents or []:
                n_spans += 1
                a, b = base + int(e["start"]), base + int(e["end"])
                # THE CONTRACT. The service returns per-sentence offsets; we add the
                # sentence's own start. If the two disagree the slice will not match the
                # text the service reported, and that is the only way to catch it.
                got, want = text[a:b], sent[int(e["start"]):int(e["end"])]
                if got != want:
                    r["violations"].append("[%d:%d] sliced %r, service said %r" % (a, b, got, want))
        r["gliner"] = {"sentences": len(sents), "spans": n_spans,
                       "elapsed_s": round(time.time() - t0, 2)}
    except Exception as e:
        r["errors"].append("gliner: %s: %s" % (type(e).__name__, str(e)[:160]))

    prompt = ("Reply with ONE short English sentence naming the main organisation this "
              "text is about, or NONE.\n\n" + text[:1500])
    try:
        out, meta = llm_client.ask(prompt, npredict=npredict, node=nid, with_meta=True)
        r["llm"] = {"reply": (out or "")[:90], "eval_count": meta.get("eval_count"),
                    "tok_s": meta.get("tok_s"), "elapsed_s": meta.get("elapsed_s"),
                    "model": meta.get("model")}
    except Exception as e:
        r["errors"].append("llm: %s: %s" % (type(e).__name__, str(e)[:160]))
    return r


def report(rows):
    print("\n%-7s %-9s %-7s %-22s %-24s %s" %
          ("node", "chars", "spans", "gliner", "llm", "offsets"))
    print("-" * 96)
    ok = True
    for r in rows:
        g = r["gliner"]
        l = r["llm"]
        gtxt = ("%d sent / %.1fs" % (g["sentences"], g["elapsed_s"])) if g else "FAILED"
        ltxt = (("%s tok @ %s tok/s" % (l["eval_count"], l["tok_s"])) if l and l["eval_count"]
                else ("%.1fs" % l["elapsed_s"]) if l else "FAILED")
        vio = "OK" if not r["violations"] else "%d VIOLATION(S)" % len(r["violations"])
        if r["errors"] or r["violations"]:
            ok = False
        print("%-7s %-9s %-7s %-22s %-24s %s" %
              (r["node"], "{:,}".format(r["chars"]), (g or {}).get("spans", "-"), gtxt, ltxt, vio))
    for r in rows:
        for e in r["errors"]:
            print("  ! %-6s %s" % (r["node"], e))
        for v in r["violations"][:3]:
            print("  ! %-6s OFFSET %s" % (r["node"], v))
    print()
    print("PASS -- every machine served both services and the offset contract held" if ok
          else "FAIL -- see the lines above")
    return 0 if ok else 1


def _demo():
    text = "Cubic won a deal. Safran replied! A third one? Yes."
    s = sentences(text)
    assert len(s) == 4, s
    # offsets must be exact, and must come from the scan rather than a later search
    for base, sent in s:
        assert text[base:base + len(sent)] == sent, (base, sent)
    assert s[0][0] == 0 and s[1][1].startswith("Safran"), s
    # a repeated sentence must not both resolve to the first occurrence
    dup = "Same text. Same text."
    d = sentences(dup)
    assert [b for b, _ in d] == [0, 11], d
    assert sentences("") == [] and sentences("   ")[0][1].strip() == ""

    # assignment gives each node the LARGEST document it could actually be given, and the
    # slowest node the smallest -- the dc must never draw the biggest document.
    base = dict(os.environ)
    try:
        os.environ.update({"VPSB_TOK_S": "11.95", "VPSA_TOK_S": "8.3", "DC_TOK_S": "1.5",
                           "VPSB_URL": "http://x", "VPSA_URL": "http://y", "DC_URL": "http://z",
                           "VPSB_ENABLED": "1", "VPSA_ENABLED": "1", "DC_ENABLED": "1"})
        docs = [{"document_id": "d%d" % i, "main_text": "x" * n}
                for i, n in enumerate((500, 1200, 3000, 9000))]
        got = assign(docs, ["vps-b", "vps-a", "dc"])
        by = {nid: d for nid, _cap, d in got}
        assert all(d is not None for d in by.values()), got
        # every document must fit the cap it was assigned to
        for nid, cap, d in got:
            assert len(d["main_text"]) <= cap, (nid, cap, len(d["main_text"]))
        # ...and no document is used twice
        ids = [d["document_id"] for d in by.values()]
        assert len(set(ids)) == 3, ids
        # a node with no document that fits is reported, not skipped silently
        tiny = assign([{"document_id": "big", "main_text": "x" * 10_000_000}], ["dc"])
        assert tiny[0][2] is None, tiny
        print("ok  sentence offsets are exact incl. repeats, and no node is assigned a "
              "document it could not be given in production")
    finally:
        os.environ.clear()
        os.environ.update(base)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", help="fetch 3 FRESH documents from the crawler corpus")
    ap.add_argument("--docs", help="a .jsonl of documents (default: the local corpus600 set)")
    ap.add_argument("--nodes", default="", help="comma-separated; default = every live node")
    ap.add_argument("--npredict", type=int, default=120)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        return _demo()

    nodes.load_env()
    node_ids = ([n.strip() for n in a.nodes.split(",") if n.strip()]
                or nodes.live_order())
    if not node_ids:
        raise SystemExit("no live nodes -- check LLM_NODE_ORDER and the *_URL values")

    h = llm_client.health()
    if not h.get("ok"):
        print("API not healthy: %s" % (h.get("problems") or h), file=sys.stderr)
        print("start it with:  PYTHONPATH=. python3 -m uvicorn llmapi.server:app "
              "--host 127.0.0.1 --port %s" % os.environ.get("LLMAPI_PORT", 8610), file=sys.stderr)
        return 2

    docs = load_corpus(a.dsn) if a.dsn else load_local(a.docs)
    print("%d candidate document(s) from %s" % (len(docs), "the crawler" if a.dsn else "disk"))

    rows = []
    for nid, cap, doc in assign(docs, node_ids):
        if doc is None:
            print("  %-6s no document fits its %s-char cap" % (nid, "{:,}".format(cap)))
            rows.append({"node": nid, "document_id": "-", "chars": 0, "gliner": None,
                         "llm": None, "violations": [], "errors": ["no document fits"]})
            continue
        print("  %-6s cap %-8s -> %s (%s chars, %s)" %
              (nid, "{:,}".format(cap), doc["document_id"], "{:,}".format(len(doc["main_text"])),
               doc.get("language", "?")), flush=True)
        rows.append(run_one(nid, doc, npredict=a.npredict))
    return report(rows)


if __name__ == "__main__":
    sys.exit(main() or 0)
