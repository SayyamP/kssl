"""The LLM / GLiNER API. Every model call in the system goes through here.

    uvicorn llmapi.server:app --host 127.0.0.1 --port 8610
    python llmapi/server.py --demo          # self-check, no network, no model

    POST /v1/generate   {prompt, npredict?, model?, format?, node?}  -> {response, node, ...}
    POST /v1/gliner     {texts: [...], labels?, threshold?}          -> {results: [[...]], node}
    GET  /v1/nodes                                                   -> per-node health
    GET  /healthz

WHAT THIS REPLACES
------------------
Four modules each built their own `urllib.request.urlopen(OLLAMA + "/api/generate")`, and
three of them carried their own copy of `llm_opts`. Four copies of one piece of plumbing
is four places for a timeout fix to be applied three times.

IT RUNS ON VPS-B, AND THAT IS A DESIGN CONSTRAINT, NOT A DEPLOYMENT DETAIL
--------------------------------------------------------------------------
Model calls originate here. The DC is deliberately not in the path: its Ollama answers on
a private docker address that does not exist from this host, and routing serving-side work
through the slowest node in the fleet (1.5 tok/s measured) would make every card wait on
the box least able to produce it.

FAILOVER IS FOR TRANSPORT, NEVER FOR CONTENT
--------------------------------------------
A node that refuses the connection, times out, or 5xxs is retried elsewhere. A node that
answers with a model refusal, or an empty completion, is NOT -- that is an answer, and
re-asking a second model until one says something is how a pipeline invents facts. The
distinction is the whole reason `_Transport` exists as its own exception type.
"""
import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llmapi import nodes  # noqa: E402

try:
    import httpx
except ImportError:                      # --demo must run without the dependency
    httpx = None

_HTTP = None


def _client():
    """One pooled client for the process.

    httpx.post() builds a fresh Client -- transport, connection pool and an SSL context --
    then tears it down on EVERY call: measured at 8.45ms against 0.29ms for a shared one,
    all of it GIL-held, plus a socket into TIME_WAIT per request.
    """
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
            # The farm gateways sit behind Cloudflare, whose bot-protection 403s the default
            # httpx/python User-Agent. A curl-shaped UA gets through; harmless to local nodes.
            headers={"User-Agent": "curl/8.4.0"})
    return _HTTP


class _Transport(Exception):
    """The node could not be reached or did not answer. Safe to try another node."""


class _Refused(Exception):
    """The node answered and the answer is unusable. NOT safe to try another node."""


def _int0(v):
    """A token count that is missing or garbled is TELEMETRY, not a reason to throw away
    a good generation. int(None) and int("many") both raise; neither should cost a reply."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _auth(node):
    k = node.get("api_key")
    return {"Authorization": "Bearer " + k} if k else {}


def call_node(node, prompt, npredict, fmt=None, model=None, post=None):
    """One generation against one node. -> (text, meta). Raises _Transport or _Refused."""
    # Each node serves exactly ONE model under its own name (farm: text-model, CPU: qwen2.5:7b-instruct).
    # The node's configured name therefore wins over a caller's generic request -- serving_fill asks for
    # "qwen2.5:7b", but the farm only knows "text-model" and 400s on any other name. Node model is authority.
    model = node.get("model") or model or os.environ.get("NODE_MODEL") or "qwen2.5:7b"
    opts = nodes.options(node, npredict)
    timeout = nodes.read_timeout(npredict, node["tok_s"])

    if node["openai"]:
        # The farm gateway is OpenAI-shaped: guided_json rather than `format`.
        url = node["url"] + "/v1/chat/completions"
        body = {"model": model, "temperature": 0, "max_tokens": int(npredict),
                "messages": [{"role": "user", "content": prompt}]}
        if fmt:
            body["guided_json"] = fmt
    else:
        url = node["url"] + "/api/generate"
        # keep_alive=-1 pins the model resident after the first load. Without it Ollama
        # evicts on its 5-minute idle default, so the NEXT call after a lull cold-loads
        # again (~150s+ on a CPU box) and blows the read timeout -- the exact ReadTimeout
        # that made vps-a/dc look dead. Load once, stay warm. Override with NODE_KEEP_ALIVE
        # (seconds, or -1 to pin) if a box is RAM-starved and must release the model.
        body = {"model": model, "prompt": prompt, "stream": False, "options": opts,
                "keep_alive": nodes._i("NODE_KEEP_ALIVE", -1)}
        if fmt:
            body["format"] = fmt

    t0 = time.time()
    # A bare float REPLACES the pooled client's whole Timeout object, so the 10s connect
    # budget would silently become the generation budget: a node whose address blackholes
    # -- exactly the "private DC address dialled from elsewhere" case -- then burns the
    # full read timeout in connect, per attempt, before failover can even begin.
    budget = (httpx.Timeout(connect=10.0, read=timeout, write=30.0, pool=10.0)
              if httpx is not None else timeout)
    try:
        r = (post or _client().post)(url, json=body, timeout=budget, headers=_auth(node))
    except Exception as e:
        raise _Transport("%s: %s" % (type(e).__name__, str(e)[:90]))
    if r.status_code != 200:
        # 530 from the farm means "no key", which reads exactly like an outage. Say which.
        raise _Transport("HTTP %s%s" % (r.status_code,
                                        " (no API key?)" if r.status_code == 530 else ""))
    try:
        payload = r.json()
    except Exception:
        raise _Transport("unparseable body")

    # A 200 whose body is not the shape we expect is a TRANSPORT failure, not a crash. It
    # has to raise _Transport specifically, or it escapes generate()'s retry loop and the
    # healthy farm is never tried -- a proxy returning `["error"]` would take the whole
    # request down while a working node sat right behind it in the chain.
    if not isinstance(payload, dict):
        raise _Transport("200 with a %s body, expected an object" % type(payload).__name__)
    if node["openai"]:
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _Transport("OpenAI-shaped reply with no choices")
        used = _int0((payload.get("usage") or {}).get("completion_tokens"))
    else:
        text = payload.get("response", "")
        used = _int0(payload.get("eval_count"))
    if not isinstance(text, str):
        raise _Transport("reply content was %s, not a string" % type(text).__name__)

    return (text or "").strip(), {
        "node": node["id"], "model": model, "eval_count": used,
        "elapsed_s": round(time.time() - t0, 2),
        "tok_s": round(used / max(0.01, time.time() - t0), 2) if used else None,
        "timeout_granted_s": round(timeout, 1),
    }


_LOCK = threading.Lock()
_INFLIGHT = {}                  # node id -> calls currently in flight
_CURRENT = {}                   # node id -> smooth-weighted-round-robin credit
_FAILS = {}                     # node id -> consecutive transport failures
_COOL_UNTIL = {}                # node id -> monotonic time it may lead again


def _reset_selector():
    """Drop all selection state. For the self-check only -- these are process globals and
    a test that leaves a node cooling makes the next test's chain order a mystery."""
    with _LOCK:
        _INFLIGHT.clear(); _CURRENT.clear(); _FAILS.clear(); _COOL_UNTIL.clear()


def inflight():
    with _LOCK:
        return dict(_INFLIGHT)


def _cooling(nid, now=None):
    return _COOL_UNTIL.get(nid, 0.0) > (now if now is not None else time.monotonic())


def note_result(nid, ok, now=None):
    """Record a node's outcome. THE CIRCUIT BREAKER, and it is not optional here.

    The farm carries the largest weight because it is 4.5x the next node -- and it is also
    the least reliable thing in the fleet: route.py records it "often not alive 2-3 hours
    straight". Those two facts together are a trap. Weighted selection would hand a dead
    farm ~71% of all picks, and each of those calls would burn its full read timeout, twice,
    before falling through to a node that was healthy the whole time. Throughput would drop
    further WITH the fast node than without it.

    So consecutive transport failures cool a node off: it stops LEADING, keeps its place at
    the back of the chain, and one success restores it. Nothing is ever removed -- a node
    that looks dead may just have been briefly unreachable, and the only way to find out is
    to let it answer when everything else is busy.
    """
    now = now if now is not None else time.monotonic()
    with _LOCK:
        if ok:
            _FAILS[nid] = 0
            _COOL_UNTIL.pop(nid, None)
            return
        n = _FAILS.get(nid, 0) + 1
        _FAILS[nid] = n
        if n >= max(1, nodes._i("LLM_BREAK_AFTER", 3)):
            _COOL_UNTIL[nid] = now + nodes._f("LLM_COOLDOWN_S", 120.0)


def select_chain(npredict=300, t=None, order=None):
    """Order the live nodes for THIS call: who to ask first, then who to fall back to.

    THE SAME DECISION route.py MAKES, one level down. There it is "which document can this
    node finish inside its budget"; here it is "which node can finish this call inside
    its budget". Both derive capacity from a TIME budget and a measured tok/s, and neither
    uses a hand-set share -- route.py's own comment on why is worth keeping in mind:
    a weighted score cannot express a hard rule, and the tuning surface is pure liability.

    Four tiers, strict-first, exactly like an ordered claim:

        0  fits its budget, healthy, free       ask these first, fastest first
        1  fits, healthy, but at its concurrency cap
        2  fits only under the RELAXED budget   (route.py's fallback_cap)
        3  cooling after repeated failures      last resort, never removed

    Fastest-first inside tier 0 is route.py's `order="short"` -- take the work that
    finishes soonest. It also means an available farm gets the large calls, which is what
    the capacity model says should happen, without anyone maintaining a percentage.
    """
    t = t if t is not None else nodes.table()
    live = order if order is not None else nodes.live_order()
    return _rank(live, lambda n: nodes.est_seconds(npredict, t[n]["tok_s"]),
                 lambda n: nodes.fits(n, npredict, t[n]["tok_s"]), service="")


def gliner_chain(chars, order=None):
    """The same ranking, for the GLiNER service. Same fleet, same tiers, same breaker.

    Keyed separately (`:gliner`) so the two services on one box do not cool each other:
    Ollama being down says nothing about whether GLiNER is answering, and a shared counter
    would take a healthy service out of rotation for its neighbour's outage.
    """
    live = order if order is not None else nodes.gliner_order()
    return _rank(live, lambda n: nodes.est_gliner_seconds(chars, nodes.gliner_cps(n)),
                 lambda n: nodes.gliner_fits(n, chars), service=":gliner")


def _rank(live, cost_of, fits, service=""):
    """Order nodes for one call: fastest-first among those that fit, then the rest."""
    if not live:
        return []
    now = time.monotonic()
    with _LOCK:
        busy = {n: _INFLIGHT.get(n + service, 0) >= nodes.max_inflight(n) for n in live}
        cold = {n: _cooling(n + service, now) for n in live}

    def tier(n):
        if cold[n]:
            return 3
        if not fits(n):
            # Over budget strictly. Eligible only under the relaxed limit, and if it does
            # not fit even then it still stays in the list -- being last is a real answer,
            # being absent means a call fails while a node that could have served it idles.
            return 2
        return 1 if busy[n] else 0

    # Ties inside a tier go to the node that finishes soonest, then to the configured
    # order so the result is deterministic for the same fleet state.
    return sorted(live, key=lambda n: (tier(n), cost_of(n), live.index(n)))


def generate(prompt, npredict=300, fmt=None, model=None, node=None, post=None, table=None):
    """Try the preference order until one node answers. -> (text, meta)."""
    t = table if table is not None else nodes.table()
    if node:
        if node not in t:
            raise _Refused("unknown node %r" % node)
        if not t[node]["enabled"]:
            raise _Refused("node %r is not enabled here" % node)
        chain = [node]
    else:
        chain = select_chain(npredict, t)
    if not chain:
        raise _Refused("no node is enabled -- check LLM_NODE_ORDER and the *_URL values")

    tried = []
    # LLM_RETRIES is ATTEMPTS PER NODE, not retries-after-the-first. Parsed defensively:
    # a typo'd value must not raise inside every request handler.
    attempts_per_node = max(1, nodes._i("LLM_RETRIES", 2))
    for nid in chain:
        for attempt in range(attempts_per_node):
            with _LOCK:
                _INFLIGHT[nid] = _INFLIGHT.get(nid, 0) + 1
            try:
                text, meta = call_node(t[nid], prompt, npredict, fmt, model, post=post)
            except _Transport as e:
                note_result(nid, False)
                tried.append("%s: %s" % (nid, e))
                if attempt + 1 < attempts_per_node:
                    time.sleep(nodes._f("LLM_BACKOFF_S", 1.0) * (attempt + 1))
                continue
            finally:
                # DECREMENT ON EVERY PATH. A counter that only comes down on success leaks
                # one per failure, and a node that has failed `max_inflight` times then
                # looks permanently busy and is never chosen again -- a slow, silent
                # capacity loss that reads as the node being down.
                with _LOCK:
                    _INFLIGHT[nid] = max(0, _INFLIGHT.get(nid, 1) - 1)
            note_result(nid, True)
            meta["tried"] = tried
            meta["chain"] = chain
            return text, meta
    raise _Transport("every node failed -- " + " | ".join(tried))


worst_case_s = nodes.worst_case_s


def call_gliner_node(nid, body, post=None):
    """One /extract against one node. -> results. Raises _Transport."""
    # The configured value is the FULL endpoint, matching the existing GLINER_URL
    # convention (https://ollama.i3softlab.com/extract) rather than a base to append to.
    url = nodes.gliner_url(nid)
    t = nodes.table()
    # The farm needs its Bearer key; a node on our own network must never be sent one.
    key = t[nid]["api_key"] if t.get(nid) else ""
    headers = {"Authorization": "Bearer " + key} if key and url.startswith("https") else {}
    # Same rule as call_node: a bare int replaces the whole Timeout object, so a
    # blackholed URL would burn the entire read budget in CONNECT.
    read_s = nodes.est_gliner_seconds(sum(len(x) for x in body["text"]),
                                      nodes.gliner_cps(nid)) * 3.0 + 30.0
    budget = (httpx.Timeout(connect=10.0, read=read_s, write=30.0, pool=10.0)
              if httpx is not None else read_s)
    try:
        r = (post or _client().post)(url, json=body, timeout=budget, headers=headers)
    except Exception as e:
        raise _Transport("%s: %s" % (type(e).__name__, str(e)[:90]))
    if r.status_code != 200:
        raise _Transport("HTTP %s%s" % (r.status_code,
                                        " (model still loading?)" if r.status_code == 503 else ""))
    try:
        payload = r.json()
    except Exception:
        raise _Transport("unparseable body")
    if not isinstance(payload, dict):
        raise _Transport("200 with a %s body, expected an object" % type(payload).__name__)
    results = payload.get("results")
    if not isinstance(results, list):
        raise _Transport("reply has no results list")
    # THE REPLY IS ZIPPED AGAINST THE CALLER'S SENTENCES BY POSITION. A short list would
    # silently shift every span after the gap into the wrong sentence, which is exactly
    # the class of bug the offset contract exists to make impossible.
    if len(results) != len(body["text"]):
        raise _Transport("asked for %d texts, got %d results"
                         % (len(body["text"]), len(results)))
    return results


def gliner(texts, labels=None, threshold=None, node=None, post=None):
    """Run NER over a batch of sentences, on whichever node can serve it.

    Routed exactly like a generation: budget, health, concurrency cap, circuit breaker --
    across EVERY node that serves GLiNER, not just the farm. The farm is the fastest and
    the least reliable thing in the fleet; being the only GLiNER was a single point of
    failure wearing a redundancy label.

    Offsets come back relative to each input string and are NOT adjusted here: the caller
    owns the document and does the arithmetic, so `document.text[start:end] == span.text`
    stays a property of one place instead of two.
    """
    if not nodes._on("GLINER_ENABLED", "1"):
        raise _Refused("GLiNER is disabled (GLINER_ENABLED=0)")
    texts = list(texts)
    if node:
        # PINNED. Failover is deliberately bypassed so a caller testing one box gets that
        # box's answer or an error -- never a rescue from a neighbour that hides the fault.
        if node not in nodes.KNOWN:
            raise _Refused("unknown node %r" % node)
        if not nodes.gliner_enabled(node):
            raise _Refused("node %r does not serve GLiNER here" % node)
        chain = [node]
    else:
        chain = gliner_chain(sum(len(x) for x in texts))
    if not chain:
        raise _Refused("no node serves GLiNER -- set <NODE>_GLINER_URL and GLINER_NODE_ORDER")
    # Both keys on purpose: the current farm gateway reads "texts" (and errors on "text"
    # alone), while our own gliner_server reads "text". Sending both satisfies each without
    # a per-node branch or a redeploy -- each service uses the key it knows, ignores the other.
    body = {"text": texts, "texts": texts,
            "labels": labels or _default_labels(),
            # nodes._f exists for exactly this: a garbled GLINER_THRESHOLD must not
            # raise inside a request handler and surface as a 500.
            "threshold": float(threshold) if threshold is not None
                        else nodes._f("GLINER_THRESHOLD", 0.2)}

    tried, t0 = [], time.time()
    attempts = max(1, nodes._i("LLM_RETRIES", 2))
    for nid in chain:
        for attempt in range(attempts):
            key = nid + ":gliner"
            with _LOCK:
                _INFLIGHT[key] = _INFLIGHT.get(key, 0) + 1
            try:
                results = call_gliner_node(nid, body, post=post)
            except _Transport as e:
                note_result(key, False)
                tried.append("%s: %s" % (nid, e))
                if attempt + 1 < attempts:
                    time.sleep(nodes._f("LLM_BACKOFF_S", 1.0) * (attempt + 1))
                continue
            finally:
                with _LOCK:
                    _INFLIGHT[key] = max(0, _INFLIGHT.get(key, 1) - 1)
            note_result(key, True)
            return results, {"node": nid, "elapsed_s": round(time.time() - t0, 2),
                             "n_texts": len(texts), "threshold": body["threshold"],
                             "tried": tried, "chain": chain}
    raise _Transport("every GLiNER node failed -- " + " | ".join(tried))


def _default_labels():
    raw = (os.environ.get("GLINER_LABELS") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return ["person", "organization", "location", "product", "event",
            "document or standard", "date", "money amount", "measurement"]


# --------------------------------------------------------------------------- HTTP
def build_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    nodes.load_env()
    boot = nodes.check_config()
    if boot:
        # Loud once at startup, so a broken config is visible in the logs immediately --
        # but NOT cached. See healthz.
        print("llmapi: %d config problem(s) at startup:" % len(boot), file=sys.stderr)
        for b in boot:
            print("  ! %s" % b, file=sys.stderr)
    app = FastAPI(title="KSSL LLM/GLiNER API", version="1")

    @app.get("/healthz")
    def healthz():
        # RE-EVALUATED PER REQUEST, never the value captured at boot. This is what the
        # container healthcheck polls: cached at startup, a config fixed by an operator
        # would report unhealthy until someone thought to restart, and a config that
        # ROTTED after boot would report healthy forever. Both are the failure this
        # endpoint exists to prevent. It is a dict comparison, not a network call.
        problems = nodes.check_config()
        # Degraded, not dead: the process is up and can say why it cannot serve.
        return JSONResponse({"ok": not problems, "origin": nodes.origin(),
                             "order": nodes.live_order(), "problems": problems},
                            status_code=200 if not problems else 503)

    @app.get("/v1/nodes")
    def v1_nodes():
        t = nodes.table()
        out = {}
        for nid, n in t.items():
            row = {"url": n["url"], "enabled": n["enabled"], "tok_s": n["tok_s"],
                   "openai": n["openai"]}
            if n["enabled"]:
                ok, why = nodes.probe(n)
                row["up"], row["detail"] = ok, why
            out[nid] = row
        return {"origin": nodes.origin(), "order": nodes.live_order(),
                "nodes": out, "problems": nodes.check_config()}

    @app.get("/v1/budget")
    def v1_budget(npredict: int = 300):
        # The client has to out-wait the WHOLE failover chain, not one call, or it abandons
        # work the server is still legitimately doing. Only the server knows the chain.
        return {"npredict": npredict, "worst_case_s": worst_case_s(npredict)}

    @app.post("/v1/generate")
    def v1_generate(req: dict):
        req = req or {}
        prompt = req.get("prompt")
        if not prompt or not str(prompt).strip():
            raise HTTPException(400, "prompt is required and must not be empty")
        # `req.get("npredict") or 300` would turn an explicit 0 into 300, because 0 is
        # falsy -- so "ask for nothing" silently became "ask for the default" and the guard
        # below could never fire. Absent and zero are different requests; test for absent.
        raw = req.get("npredict")
        if raw is None:
            npredict = 300
        else:
            # A non-numeric npredict is the CALLER's mistake -- 400, never an uncaught
            # ValueError surfacing as a 500 that reads like the server fell over.
            try:
                npredict = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(400, "npredict must be an integer, got %r" % raw)
        if npredict < 1:
            raise HTTPException(400, "npredict must be >= 1, got %d" % npredict)
        try:
            text, meta = generate(str(prompt), npredict=npredict, fmt=req.get("format"),
                                  model=req.get("model"), node=req.get("node"))
        except _Refused as e:
            raise HTTPException(400, str(e))
        except _Transport as e:
            raise HTTPException(502, str(e))
        return {"response": text, **meta}

    @app.post("/v1/chat/completions")
    def v1_chat_completions(req: dict):
        # OpenAI-compatible shim so the extraction engine (which speaks /v1/chat/completions with
        # C_OPENAI=1) routes its LLM calls THROUGH this router -- across vps-a and farm with the same
        # health-gating, failover and per-node budgets as /v1/generate -- instead of dialing one
        # backend directly. The engine sends {messages:[{role,content}], max_tokens, model}; we take
        # the last user turn as the prompt, run it through generate(), and answer OpenAI-shaped.
        req = req or {}
        msgs = req.get("messages") or []
        prompt = ""
        for m in msgs:                       # last user message is the prompt; fall back to the last
            if isinstance(m, dict) and m.get("content"):
                if m.get("role") == "user":
                    prompt = str(m["content"])
        if not prompt and msgs and isinstance(msgs[-1], dict):
            prompt = str(msgs[-1].get("content") or "")
        if not prompt.strip():
            raise HTTPException(400, "messages must contain non-empty content")
        try:
            npredict = int(req.get("max_tokens") or 300)
        except (TypeError, ValueError):
            raise HTTPException(400, "max_tokens must be an integer")
        npredict = max(1, npredict)
        # guided_json (farm) rides on `format`; the engine passes it as `response_format`/`guided_json`.
        fmt = req.get("guided_json") or (req.get("response_format") or {}).get("schema") \
            if isinstance(req.get("response_format"), dict) else req.get("guided_json")
        try:
            text, meta = generate(str(prompt), npredict=npredict, fmt=fmt,
                                  model=req.get("model"), node=req.get("node"))
        except _Refused as e:
            raise HTTPException(400, str(e))
        except _Transport as e:
            raise HTTPException(502, str(e))
        used = _int0(meta.get("eval_count"))
        return {"id": "chatcmpl-router", "object": "chat.completion", "model": meta.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
                "usage": {"completion_tokens": used, "prompt_tokens": 0, "total_tokens": used},
                "_route": {"node": meta.get("node")}}

    @app.post("/v1/gliner")
    def v1_gliner(req: dict):
        req = req or {}
        texts = req.get("texts")
        if not isinstance(texts, list) or not texts:
            raise HTTPException(400, "texts must be a non-empty list of strings")
        if not all(isinstance(x, str) for x in texts):
            raise HTTPException(400, "every element of texts must be a string")
        th = req.get("threshold")
        if th is not None:
            try:
                th = float(th)
            except (TypeError, ValueError):
                raise HTTPException(400, "threshold must be a number, got %r" % req.get("threshold"))
        try:
            results, meta = gliner(texts, req.get("labels"), th, node=req.get("node"))
        except _Refused as e:
            raise HTTPException(400, str(e))
        except _Transport as e:
            raise HTTPException(502, str(e))
        return {"results": results, **meta}

    return app


class _R:
    """Minimal stand-in for an httpx response, for the self-check."""

    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


def _demo():
    base = dict(os.environ)
    try:
        for k in list(os.environ):
            if k.split("_")[0] in ("VPSA", "VPSB", "DC", "FARM", "LLM", "NODE", "GLINER"):
                del os.environ[k]
        os.environ.update({
            "LLM_ORIGIN": "vps-b", "LLM_NODE_ORDER": "vps-b,farm", "LLM_RETRIES": "1",
            "VPSB_URL": "http://127.0.0.1:11434", "VPSB_ENABLED": "1",
            "VPSB_TOK_S": "11.95", "VPSB_THREADS": "4", "VPSB_CPU": "1",
            "FARM_URL": "https://farm.example", "FARM_ENABLED": "1",
            "FARM_OPENAI": "1", "FARM_API_KEY": "k", "FARM_TOK_S": "53.5",
            "NODE_MODEL": "qwen2.5:7b",
            "GLINER_NODE_ORDER": "vps-b,farm",
            "VPSB_GLINER_URL": "http://127.0.0.1:8620/extract",
            "FARM_GLINER_URL": "https://farm.example/extract",
            # The shape/failover assertions below need a KNOWN head. At npredict=300 the
            # farm (53.5 tok/s) finishes soonest and would lead, so give vps-b a budget
            # that fits and the farm one that does not. Selection is tested on its own.
            "VPSB_BUDGET_MIN": "22", "FARM_BUDGET_MIN": "0.001",
        })
        _reset_selector()
        t = nodes.table()

        seen = []

        def native_ok(url, json=None, timeout=None, headers=None):
            seen.append((url, json, timeout, headers))
            return _R(200, {"response": " hello ", "eval_count": 12})

        text, meta = generate("hi", npredict=300, post=native_ok, table=t)
        assert text == "hello", repr(text)
        assert meta["node"] == "vps-b" and meta["eval_count"] == 12, meta
        url, body, timeout, headers = seen[0]
        assert url == "http://127.0.0.1:11434/api/generate", url
        # the node's own characteristics reach the wire, not a global default
        assert body["options"]["num_thread"] == 4 and body["options"]["num_gpu"] == 0, body
        assert body["stream"] is False
        assert headers == {}, headers
        # the derived READ timeout reaches the wire, and the connect budget SURVIVES it --
        # a bare float would replace the whole Timeout and make connect wait a generation
        want = nodes.read_timeout(300, 11.95)
        if httpx is not None:
            assert timeout.read == want and timeout.connect == 10.0, timeout
        else:
            assert timeout == want, timeout

        # FAILOVER ON TRANSPORT: vps-b refuses, farm answers, and the reply is OpenAI-shaped
        calls = []

        def flaky(url, json=None, timeout=None, headers=None):
            calls.append(url)
            if "127.0.0.1" in url:
                raise OSError("connection refused")
            return _R(200, {"choices": [{"message": {"content": "from farm"}}],
                            "usage": {"completion_tokens": 7}})

        text, meta = generate("hi", post=flaky, table=t)
        assert text == "from farm" and meta["node"] == "farm", meta
        assert calls[-1] == "https://farm.example/v1/chat/completions", calls
        assert meta["tried"] and "vps-b" in meta["tried"][0], meta["tried"]

        # the farm carries its Bearer key; the local node must never be sent one
        seen.clear()

        def openai_ok(url, json=None, timeout=None, headers=None):
            seen.append((url, json, timeout, headers))
            return _R(200, {"choices": [{"message": {"content": "ok"}}],
                            "usage": {"completion_tokens": 3}})

        generate("hi", node="farm", post=openai_ok, table=t)
        assert seen[0][3] == {"Authorization": "Bearer k"}, seen[0][3]
        # guided_json, not `format`, on the OpenAI-shaped node -- and no ollama `options`
        seen.clear()
        generate("hi", node="farm", fmt={"type": "object"}, post=openai_ok, table=t)
        assert "guided_json" in seen[0][1] and "options" not in seen[0][1], seen[0][1]
        seen.clear()
        generate("hi", fmt={"type": "object"}, post=native_ok, table=t)
        assert "format" in seen[0][1] and "guided_json" not in seen[0][1], seen[0][1]

        # A REFUSAL IS AN ANSWER. An empty completion must NOT roll to the next node --
        # re-asking until some model says something is how a pipeline invents facts.
        hits = []

        def empty(url, json=None, timeout=None, headers=None):
            hits.append(url)
            return _R(200, {"response": "", "eval_count": 0})

        text, meta = generate("hi", post=empty, table=t)
        assert text == "" and meta["node"] == "vps-b", meta
        assert len(hits) == 1, "an empty answer must not fail over: %s" % hits

        # every node down is a transport error naming what was tried
        def dead(url, json=None, timeout=None, headers=None):
            raise OSError("nope")
        try:
            generate("hi", post=dead, table=t)
            raise AssertionError("must raise when nothing answers")
        except _Transport as e:
            assert "vps-b" in str(e) and "farm" in str(e), str(e)

        # a 530 is reported as a probable missing key, not as a bare status
        try:
            generate("hi", node="farm", post=lambda *a, **k: _R(530, {}), table=t)
            raise AssertionError("530 must raise")
        except _Transport as e:
            assert "API key" in str(e), str(e)

        # A 200 CARRYING THE WRONG SHAPE IS A TRANSPORT FAILURE AND MUST FAIL OVER.
        # Unguarded, `payload.get` on a list raised AttributeError, which is not _Transport
        # -- so it escaped the retry loop entirely and the healthy farm was never tried.
        for bad_body in ([1, 2], "busy", 7):
            hits = []

            def wrong_shape(url, json=None, timeout=None, headers=None):
                hits.append(url)
                if "127.0.0.1" in url:
                    return _R(200, bad_body)
                return _R(200, {"choices": [{"message": {"content": "farm saved it"}}]})

            text, meta = generate("hi", post=wrong_shape, table=t)
            assert text == "farm saved it" and meta["node"] == "farm", \
                "a %s body must fail over, not crash: %r" % (type(bad_body).__name__, meta)

        # a non-string completion is also transport, not a crash
        try:
            generate("hi", node="vps-b", table=t,
                     post=lambda *a, **k: _R(200, {"response": {"oops": 1}}))
            raise AssertionError("a non-string completion must raise _Transport")
        except _Transport as e:
            assert "not a string" in str(e), str(e)

        # a garbled token count is telemetry, never a reason to lose a good generation
        text, meta = generate("hi", node="vps-b", table=t,
                              post=lambda *a, **k: _R(200, {"response": "fine",
                                                            "eval_count": "many"}))
        assert text == "fine" and meta["eval_count"] == 0, meta

        # an unknown or disabled node is a client error, never a silent fallback
        for bad in ("nope", "dc"):
            try:
                generate("hi", node=bad, post=native_ok, table=t)
                raise AssertionError("%s must be refused" % bad)
            except _Refused:
                pass

        # GLiNER proxies the batched shape unchanged and does NOT touch offsets
        def gl(url, json=None, timeout=None, headers=None):
            assert url == "https://farm.example/extract", url
            assert json["text"] == ["a b", "c"], json
            assert json["threshold"] == 0.2, json
            return _R(200, {"results": [[{"start": 0, "end": 1, "label": "person",
                                          "score": 0.9}], []]})

        res, meta = gliner(["a b", "c"], post=gl)
        assert res[0][0]["start"] == 0 and res[1] == [], res
        assert meta["n_texts"] == 2, meta

        # a 200 carrying an HTML error page (a proxy in front of the farm) is the UPSTREAM
        # failing: 502, never an uncaught 500 that reads as ours
        for bad in (ValueError("not json"), ["a", "list"], "a string"):
            try:
                gliner(["x"], post=lambda *a, **k: _R(200, bad))
                raise AssertionError("a %r body must raise _Transport" % (bad,))
            except _Transport:
                pass

        # GLINER FAILS OVER ACROSS NODES like everything else -- the farm is no longer a
        # single point of failure, which was the whole reason it ran everywhere.
        _reset_selector()
        hit = []

        def gl_flaky(url, json=None, timeout=None, headers=None):
            hit.append(url)
            if "127.0.0.1" in url:
                raise OSError("gliner down on vps-b")
            return _R(200, {"results": [[], []]})

        res, meta = gliner(["a b", "c"], post=gl_flaky)
        assert meta["node"] == "farm", meta
        assert hit[-1] == "https://farm.example/extract", hit
        assert any("vps-b" in x for x in meta["tried"]), meta["tried"]

        # the farm's key rides only to the farm; a node on our own network never sees it
        _reset_selector()
        seen_h = []

        def gl_rec(url, json=None, timeout=None, headers=None):
            seen_h.append((url, headers))
            return _R(200, {"results": [[]]})

        gliner(["x"], post=gl_rec)
        assert seen_h[0][1] == {}, "a local GLiNER must not be sent the farm key: %s" % (seen_h[0],)

        # A SHORT RESULT LIST MUST BE REFUSED. The caller zips this against its own
        # sentence list BY POSITION, so a missing entry shifts every span after it into
        # the wrong sentence -- silently, and past the offset contract.
        _reset_selector()
        try:
            gliner(["a", "b", "c"], post=lambda *a, **k: _R(200, {"results": [[], []]}))
            raise AssertionError("a short results list must raise")
        except _Transport as e:
            assert "got 2" in str(e), str(e)

        # ...and so must a reply with no results list at all
        _reset_selector()
        try:
            gliner(["a"], post=lambda *a, **k: _R(200, {"oops": 1}))
            raise AssertionError("a reply with no results list must raise")
        except _Transport as e:
            assert "no results" in str(e), str(e)

        # a node whose model is still loading answers 503, and the message says so rather
        # than reading as a generic outage
        _reset_selector()
        try:
            gliner(["a"], post=lambda *a, **k: _R(503, {}))
            raise AssertionError("503 must raise")
        except _Transport as e:
            assert "loading" in str(e), str(e)

        os.environ["GLINER_ENABLED"] = "0"
        try:
            gliner(["x"], post=gl)
            raise AssertionError("disabled GLiNER must refuse")
        except _Refused:
            pass
        os.environ["GLINER_ENABLED"] = "1"

        # no node configured for GLiNER is a REFUSAL naming the fix, not a crash
        _reset_selector()
        saved_order = os.environ.get("GLINER_NODE_ORDER", "")
        os.environ["GLINER_NODE_ORDER"] = ""
        os.environ["VPSB_GLINER_URL"] = ""
        os.environ["FARM_GLINER_URL"] = ""
        try:
            gliner(["x"], post=gl)
            raise AssertionError("no GLiNER node must refuse")
        except _Refused as e:
            assert "GLINER_URL" in str(e), str(e)
        os.environ["GLINER_NODE_ORDER"] = saved_order
        os.environ["VPSB_GLINER_URL"] = "http://127.0.0.1:8620/extract"
        os.environ["FARM_GLINER_URL"] = "https://farm.example/extract"
        _demo_routing()
        _demo_app()
        print("ok  the deployed entrypoint resolves and answers, failover is transport-only, "
              "an empty answer never rolls to another node, the farm key stays off local nodes")
    finally:
        os.environ.clear()
        os.environ.update(base)


def _demo_routing():
    """Selection follows route.py's model: budget-derived eligibility, strict before
    relaxed, health before dispatch, demote-never-remove."""
    base = dict(os.environ)
    try:
        for k in list(os.environ):
            if k.split("_")[0] in ("VPSA", "VPSB", "DC", "FARM", "LLM", "NODE"):
                del os.environ[k]
        os.environ.update({
            "LLM_ORIGIN": "vps-b", "LLM_NODE_ORDER": "vps-b,vps-a,dc,farm",
            "VPSB_URL": "http://127.0.0.1:11434", "VPSB_ENABLED": "1", "VPSB_TOK_S": "11.95",
            "VPSA_URL": "http://tunnel-vpsa:11502", "VPSA_ENABLED": "1", "VPSA_TOK_S": "8.3",
            "DC_URL": "http://tunnel-dc:11503", "DC_ENABLED": "1", "DC_TOK_S": "1.5",
            "FARM_URL": "https://farm.example", "FARM_ENABLED": "1", "FARM_OPENAI": "1",
            "FARM_API_KEY": "k", "FARM_TOK_S": "53.5",
        })
        _reset_selector()
        t = nodes.table()

        # FASTEST-FIRST among nodes that fit -- route.py's order="short", take the work
        # that finishes soonest. With everything healthy the farm leads, which is what the
        # capacity model says (72% of the fleet) without a percentage anywhere.
        assert select_chain(300, t)[0] == "farm", select_chain(300, t)
        assert select_chain(300, t) == ["farm", "vps-b", "vps-a", "dc"], select_chain(300, t)

        # THE BUDGET DECIDES, NOT A SHARE. The dc at 1.5 tok/s can honestly serve an
        # 80-token verdict (53s, inside its 85-min budget) but not a 20,000-token job
        # (3.7h, far past it) -- so it is demoted for the big call and eligible for the
        # small one. Nothing was tuned to make that happen.
        assert nodes.fits("dc", 80, 1.5), "the dc must be eligible for a small call"
        assert not nodes.fits("dc", 20000, 1.5), "the dc must not be eligible for a huge one"
        assert select_chain(20000, t)[-1] == "dc", select_chain(20000, t)
        assert "dc" in select_chain(20000, t), "over-budget is DEMOTED, never removed"

        # A COOLING NODE STOPS LEADING. This is the farm case exactly: fastest node, least
        # reliable. Without it, weighted-by-speed selection hands a dead farm most of the
        # calls and each one burns its full timeout before falling through.
        os.environ["LLM_BREAK_AFTER"] = "3"
        os.environ["LLM_COOLDOWN_S"] = "120"
        for _ in range(3):
            note_result("farm", False)
        chain = select_chain(300, t)
        assert chain[0] == "vps-b", "a cooling farm must not lead: %s" % chain
        assert chain[-1] == "farm", "...but must stay in the chain: %s" % chain
        note_result("farm", True)                      # one success restores it
        assert select_chain(300, t)[0] == "farm", select_chain(300, t)

        # two failures is not enough to trip it -- a single blip must not cost the fastest node
        _reset_selector()
        note_result("farm", False); note_result("farm", False)
        assert select_chain(300, t)[0] == "farm", "2 < LLM_BREAK_AFTER must not cool it"

        # A BUSY NODE YIELDS ITS TURN. vps-b and the dc run OLLAMA_NUM_PARALLEL=1, so a
        # second concurrent call there buys queue latency and nothing else.
        _reset_selector()
        assert nodes.max_inflight("vps-b") == 1 and nodes.max_inflight("farm") == 12
        with _LOCK:
            _INFLIGHT["farm"] = 12
        chain = select_chain(300, t)
        assert chain[0] == "vps-b", "a saturated farm must yield: %s" % chain
        assert "farm" in chain, "...but stay reachable when everything else is busy too"

        # THE IN-FLIGHT COUNTER MUST COME BACK DOWN ON FAILURE. Leaking one per failed call
        # makes a node look permanently busy after max_inflight failures -- it is never
        # chosen again, and the capacity loss is silent and reads as the node being down.
        _reset_selector()
        os.environ["LLM_RETRIES"] = "2"
        try:
            generate("hi", node="vps-b", table=t,
                     post=lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
        except _Transport:
            pass
        assert inflight().get("vps-b", 0) == 0, "in-flight leaked: %s" % inflight()

        # a single live node needs no ceremony
        os.environ["LLM_NODE_ORDER"] = "vps-b"
        _reset_selector()
        assert select_chain(300) == ["vps-b"]
        os.environ["LLM_NODE_ORDER"] = "vps-b,vps-a,dc,farm"

        # ...and a broken order still yields an empty chain rather than raising
        os.environ["LLM_NODE_ORDER"] = "vps-b,nope"
        assert select_chain(300) == []
        print("    routing: budget-derived eligibility, fastest-first, cooling demotes, "
              "over-budget demotes, nothing is ever removed")
    finally:
        os.environ.clear()
        os.environ.update(base)
        _reset_selector()


def _demo_app():
    """THE TEST THAT WAS MISSING, and whose absence shipped a dead container.

    Everything else here exercises generate()/gliner() directly with injected fakes. The
    container runs `uvicorn llmapi.server:app`, which resolves an ATTRIBUTE on an imported
    module -- a path no test touched. A stray `app = None` shadowed the module __getattr__,
    uvicorn got None, and every request 500'd while all three demos printed ok.

    So: resolve the attribute the way uvicorn does, then actually drive the endpoints.
    """
    import importlib

    mod = importlib.import_module("llmapi.server")
    try:
        from uvicorn.importer import import_from_string
        resolved = import_from_string("llmapi.server:app")
    except ImportError:
        resolved = getattr(mod, "app")
    assert resolved is not None, "llmapi.server:app resolved to None -- the container is dead"
    assert callable(resolved), "llmapi.server:app is not callable: %r" % type(resolved)
    assert "app" not in vars(mod), \
        "a module-level `app` shadows __getattr__; that is exactly the bug this test exists for"

    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("    (fastapi absent -- endpoint drive skipped, attribute check still ran)")
        return

    # NO NETWORK. The first version of this test posted a real /v1/generate at
    # 127.0.0.1:11434 and asserted 502 -- which passes only on a machine where nothing
    # useful is listening. On vps-b, the box this whole thing deploys to, a real Ollama
    # answers there: the assert would fail and the test would first burn a real 300-token
    # generation. A regression test that breaks on the production host is worse than none.
    global _HTTP
    saved = _HTTP

    class _Dead:
        @staticmethod
        def post(*a, **k):
            raise OSError("connection refused (self-check: no network)")

    _HTTP = _Dead()
    # Pin every node key, so build_app()'s load_env() cannot pull the operator's real .env
    # into the assertions below -- a stray VPSA_ENABLED=1 on this machine would fail them.
    for k, v in (("VPSA_URL", ""), ("VPSA_ENABLED", "0"),
                 ("DC_URL", ""), ("DC_ENABLED", "0"), ("GLINER_ENABLED", "1"),
                 ("GLINER_URL", "https://farm.example/extract")):
        os.environ[k] = v
    try:
        c = TestClient(build_app(), raise_server_exceptions=False)

        # healthz must be 503, not 500, when the config cannot serve -- and must say why
        os.environ["FARM_API_KEY"] = ""
        r = c.get("/healthz")
        assert r.status_code == 503 and r.json()["problems"], r.text
        os.environ["FARM_API_KEY"] = "k"
        assert c.get("/healthz").status_code == 200, c.get("/healthz").text

        # A TYPO'D LLM_NODE_ORDER MUST BE A 503 THAT NAMES IT, NEVER A BARE 500. The
        # per-request check_config() fix originally left order() unguarded right beside it,
        # so the one endpoint that must always answer 500'd on the very config error it
        # exists to report.
        good = os.environ["LLM_NODE_ORDER"]
        os.environ["LLM_NODE_ORDER"] = "vps-b,farmm"
        for path in ("/healthz", "/v1/nodes", "/v1/budget?npredict=300"):
            r = c.get(path)
            assert r.status_code != 500, "%s 500'd on a typo'd node name: %s" % (path, r.text)
        assert "farmm" in c.get("/healthz").text, c.get("/healthz").text
        r = c.post("/v1/generate", json={"prompt": "x"})
        assert r.status_code == 400, "a typo'd order must be 400, got %s %s" % (r.status_code, r.text)
        os.environ["LLM_NODE_ORDER"] = good

        # a garbled operator-set threshold must not 500 either
        os.environ["GLINER_THRESHOLD"] = "0.2x"
        r = c.post("/v1/gliner", json={"texts": ["a"]})
        assert r.status_code != 500, "a bad GLINER_THRESHOLD 500'd: %s" % r.text
        os.environ["GLINER_THRESHOLD"] = "0.2"

        # bad input is the CALLER's fault: 400 with a reason, never an uncaught 500
        for body, why in (({}, "no prompt"), ({"prompt": "  "}, "blank prompt"),
                          ({"prompt": "x", "npredict": "abc"}, "non-numeric npredict"),
                          ({"prompt": "x", "npredict": 0}, "npredict below 1")):
            r = c.post("/v1/generate", json=body)
            assert r.status_code == 400, "%s should be 400, got %s %s" % (why, r.status_code, r.text)
        for body, why in (({}, "no texts"), ({"texts": []}, "empty texts"),
                          ({"texts": [1]}, "non-string text"),
                          ({"texts": ["a"], "threshold": "hi"}, "non-numeric threshold")):
            r = c.post("/v1/gliner", json=body)
            assert r.status_code == 400, "%s should be 400, got %s %s" % (why, r.status_code, r.text)

        # an unreachable node is 502 (upstream), not 500 (us)
        r = c.post("/v1/generate", json={"prompt": "x", "node": "vps-b"})
        assert r.status_code == 502, "%s %s" % (r.status_code, r.text)
        # a disabled node is 400: the caller asked for something this host cannot do
        r = c.post("/v1/generate", json={"prompt": "x", "node": "dc"})
        assert r.status_code == 400 and "not enabled" in r.text, r.text

        r = c.get("/v1/budget?npredict=300")
        assert r.json()["worst_case_s"] >= nodes.read_timeout(300, 11.95), r.text
        assert c.get("/v1/nodes").json()["origin"] == "vps-b"
    finally:
        _HTTP = saved


def __getattr__(name):
    """uvicorn imports `llmapi.server:app`; building lazily keeps --demo importable with
    no fastapi installed.

    THERE MUST BE NO MODULE-LEVEL `app = ...` ANYWHERE BELOW OR ABOVE THIS.
    PEP 562 only calls a module __getattr__ for names MISSING from the module dict, so a
    stray `app = None` -- however defensive it looks -- shadows this permanently: uvicorn
    resolves `llmapi.server:app` to None and the container answers 500 to every request
    while every self-check still passes. That shipped once. `_demo_app()` now resolves the
    attribute exactly the way uvicorn does, so it cannot ship again.
    """
    if name == "app":
        return build_app()
    raise AttributeError(name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--serve", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.serve:
        import uvicorn
        nodes.load_env()
        uvicorn.run(build_app(), host=os.environ.get("LLMAPI_BIND", "127.0.0.1"),
                    port=int(os.environ.get("LLMAPI_PORT", 8610)))
    else:
        nodes.load_env()
        print(json.dumps({"origin": nodes.origin(), "order": nodes.order(),
                          "problems": nodes.check_config()}, indent=2))
