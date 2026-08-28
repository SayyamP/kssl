"""Judge-model tournament for the card-generation role.

    python bench_models.py                      # all AVAILABLE candidates, blocked
    python bench_models.py --models a b c
    python bench_models.py --demo

Each model runs the production card prompt (serving_fill.PROMPT) over the same
fixed doc set, one model at a time (no VRAM swapping mid-run). Scoring is
mechanical -- parse validity, closed-vocabulary compliance, latency, tok/s --
plus the produced titles so an operator can eyeball quality. Selection rule:
a model must be perfectly parseable (valid+none == docs) to be eligible;
among eligible models, quality of output first, speed second.

Lessons encoded: hybrid-thinking models get think:false AND a no-preamble
suffix AND room to finish (they may still deliberate past the JSON -- that is
a disqualifying behavior, not a harness bug); num_ctx is ALWAYS set explicitly
(qwen3:30b-a3b's 262k default asked ollama for a 95 GB KV cache).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import serving_fill as sf  # noqa: E402  (PROMPT, parse_card, kssl_cats, OLLAMA, DSN)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CANDIDATES = [
    "qwen2.5:14b-instruct",        # incumbent
    "qwen2.5:7b",                  # cheap baseline (the extractor model)
    "qwen-defence-extract:latest", # local defence fine-tune
    "qwen3:4b",                    # tiny hybrid
    "gemma3:27b",
    "mistral-small3.2",
    "qwen3:30b-a3b-instruct-2507",
]
THINKING_FAMILIES = ("qwen3", "deepseek-r1", "qwq")
SUFFIX = ("\n\nOutput ONLY the JSON object or the word NONE. "
          "No reasoning, no preamble, no explanation.")


def installed_models():
    with urllib.request.urlopen((ENDPOINT or sf.OLLAMA) + "/api/tags", timeout=10) as r:
        return {m["name"] for m in json.loads(r.read().decode()).get("models", [])}


def is_thinking(model):
    return any(model.startswith(f) for f in THINKING_FAMILIES)


CPU_MODE = False
ENDPOINT = None
USE_FORMAT = False

# The card schema as a JSON schema. Passed as ollama's `format`, which compiles to a
# GBNF grammar and masks the logits -- an out-of-vocabulary category becomes literally
# unsamplable, and a preamble becomes unsamplable too.
#
# MEASURED 2026-08-24 on ollama 0.32.15, qwen3:4b, num_gpu=0:
#   no format + think=false  -> prose preamble, does NOT parse
#   FORMAT   + think=false  -> valid JSON
#   FORMAT   + think=true   -> does NOT parse
# The 2026-08 A/B that disqualified every thinking model used prompt instructions only
# and never set `format`. That was a harness fault, not a model fault, and this flag is
# what makes the re-match fair.
#
# `reasoning` is deliberately the FIRST property: under constrained decoding the model
# must commit to whatever comes first, so a verdict emitted before its justification is
# a verdict formed without one. `pillar` and `category` come last for the same reason.
def card_schema(cats):
    return {"type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "title": {"type": "string"},
                "sowhat": {"type": "string"},
                "company": {"type": "string"},
                "pillar": {"type": "string", "enum": ["competitive", "market", "tech", "none"]},
                "category": {"type": "string", "enum": list(cats) + ["none"]}},
            "required": ["reasoning", "title", "pillar", "category"]}


def ask(model, prompt, timeout=900, schema=None):
    opts = {"temperature": 0, "num_predict": 2500, "num_ctx": 8192}
    if CPU_MODE:
        opts["num_gpu"] = 0    # force CPU/RAM inference (GPU belongs to the extraction)
    body = {"model": model, "prompt": prompt, "stream": False, "options": opts}
    if USE_FORMAT and schema:
        body["format"] = schema
    if is_thinking(model):
        body["think"] = False
        body["prompt"] = prompt + SUFFIX
    req = urllib.request.Request((ENDPOINT or sf.OLLAMA) + "/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    return (d.get("response", "").strip(), time.time() - t0,
            d.get("eval_count", 0), d.get("eval_duration", 1))


def bench_prompts():
    """The fixed doc set: 6 docs with audited cards + 2 gate-refused docs."""
    import psycopg2
    con = psycopg2.connect(sf.DSN)
    cur = con.cursor()
    cur.execute("""SELECT replace(id,'pl_','') FROM serving.signal_card
                   WHERE origin='pipeline' ORDER BY id LIMIT 6""")
    docs = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT d.document_id FROM extracted.document d
                   WHERE NOT EXISTS (SELECT 1 FROM serving.signal_card c
                                      WHERE c.id='pl_'||d.document_id)
                     AND d.meta->>'set'='kssl'
                   ORDER BY d.document_id LIMIT 2""")
    docs += [r[0] for r in cur.fetchall()]
    cats = sf.kssl_cats()
    out = {}
    for did in docs:
        cur.execute("""SELECT d.title, d.source_id, d.language,
                              subject, predicate, object, modality, ev_quote
                         FROM extracted.proposition p
                         JOIN extracted.document d USING (document_id)
                        WHERE p.document_id=%s ORDER BY i LIMIT 12""", (did,))
        rows = cur.fetchall()
        if not rows:
            continue
        title, source, lang = rows[0][0], rows[0][1], rows[0][2]
        lines = "\n".join('- %s %s %s [%s] -- "%s"' % (s, p, o, m, (q or "")[:180])
                          for _, _, _, s, p, o, m, q in rows)
        out[did] = sf.PROMPT % (", ".join(cats), title or did, source, lang, lines)
    con.close()
    return out, cats


def run(models=None):
    have = installed_models()
    todo = [m for m in (models or CANDIDATES)
            if m in have or ("%s:latest" % m) in have]
    missing = [m for m in (models or CANDIDATES) if m not in todo]
    if missing:
        print("not installed, skipped: %s" % ", ".join(missing), flush=True)
    prompts, cats = bench_prompts()
    schema = card_schema(cats) if USE_FORMAT else None
    print("%d model(s) x %d doc(s)\n" % (len(todo), len(prompts)), flush=True)

    table = []
    for model in todo:                       # blocked: one model loaded at a time
        r = {"valid": 0, "none": 0, "bad": 0, "secs": [], "tps": [], "titles": []}
        for did, prompt in prompts.items():
            try:
                raw, secs, ec, ed = ask(model, prompt, schema=schema)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                print("%-28s %s ERR %s" % (model, did[-8:], repr(e)[:70]), flush=True)
                r["bad"] += 1
                continue
            if "</think>" in raw:
                raw = raw.split("</think>")[-1].strip()
            card = sf.parse_card(raw, cats)
            r["secs"].append(secs)
            r["tps"].append(ec / (ed / 1e9) if ed else 0)
            if card:
                r["valid"] += 1
                r["titles"].append(card["title"][:70])
                tag = "CARD %s|%s| %s" % (card["pillar"][:4], card["category"][:12],
                                          card["title"][:48])
            elif raw.strip().upper().startswith("NONE"):
                r["none"] += 1
                tag = "NONE"
            else:
                r["bad"] += 1
                tag = "MALFORMED: " + raw[:60].replace("\n", " ")
            print("%-28s %s %6.1fs  %s" % (model, did[-8:], secs, tag), flush=True)
        n = len(r["secs"]) or 1
        table.append((model, r["valid"], r["none"], r["bad"],
                      sum(r["secs"]) / n, sum(r["tps"]) / n, r["titles"]))

    print("\n=== TOURNAMENT SUMMARY (%d docs; eligible = 0 malformed) ===" % len(prompts))
    for model, v, no, bad, avg, tps, _ in sorted(table, key=lambda x: (x[3], x[4])):
        print("%-28s valid=%d none=%d malformed=%d  avg=%5.1fs  tok/s=%3.0f  %s"
              % (model, v, no, bad, avg, tps,
                 "ELIGIBLE" if bad == 0 else "disqualified"), flush=True)
    return table


def _demo():
    assert is_thinking("qwen3:30b-a3b") and is_thinking("qwen3:4b")
    assert not is_thinking("qwen2.5:14b-instruct") and not is_thinking("gemma3:27b")
    # the harness must always bound the context (the 95 GB KV lesson)
    import inspect
    src = inspect.getsource(ask)
    assert "num_ctx" in src
    # the schema must only offer categories that exist, plus an explicit refusal, and
    # must put the reasoning field before the two closed-vocabulary decisions
    sc = card_schema(["Artillery", "Ammunition"])
    keys = list(sc["properties"])
    assert keys[0] == "reasoning", "reasoning must be decoded first, got %s" % keys[0]
    assert keys.index("pillar") > keys.index("reasoning")
    assert keys.index("category") > keys.index("reasoning")
    assert "none" in sc["properties"]["category"]["enum"], "no way to refuse a card"
    assert "none" in sc["properties"]["pillar"]["enum"]
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--cpu", action="store_true",
                    help="num_gpu=0: run on CPU/RAM while the GPU is busy")
    ap.add_argument("--endpoint", default=None,
                    help="a second, CPU-only ollama (e.g. http://127.0.0.1:11435) "
                         "so this bench does not queue behind GPU work")
    ap.add_argument("--format", action="store_true",
                    help="constrain decoding with the card JSON schema (ollama >=0.32); "
                         "this is what the 2026-08 tournament wrongly omitted")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    globals()["CPU_MODE"] = a.cpu
    globals()["ENDPOINT"] = a.endpoint
    globals()["USE_FORMAT"] = a.format
    if a.demo:
        _demo()
    else:
        run(a.models)
