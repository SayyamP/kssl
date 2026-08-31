"""A GLiNER server, one per node. Same wire contract as the farm's /extract.

    uvicorn llmapi.gliner_server.app:app --host 0.0.0.0 --port 8620
    python llmapi/gliner_server/app.py --demo     # self-check, no model, no network

    POST /extract   {"text": [...], "labels": [...], "threshold": 0.2}
                 -> {"results": [[{start, end, label, score}], ...]}
    GET  /healthz   200 once the model is resident, 503 while loading or if it failed

WHY THIS EXISTS
---------------
GLiNER used to run in-process, as a torch model inside whichever worker happened to need
it. That put a ~2 GB model in every extraction process, made GLiNER capacity invisible to
any router, and meant the only alternative was the farm -- a node measured as "often not
alive 2-3 hours straight". One unreliable remote or N copies of a local model is not a
choice worth having.

So GLiNER becomes a service, deployed per node, and the router treats it exactly like a
model server: budget, health, concurrency cap, circuit breaker.

THE CONTRACT IS THE FARM'S, NOT A NEW ONE
-----------------------------------------
`{"text": [...]}` is a LIST of sentences and the reply is a list of per-sentence entity
lists, in the same order. That is what the farm already serves and what comprehend.py's
`_gliner_remote` already parses, so this drops in behind the same client with no change on
either side -- and the router can put a local node and the farm in one chain because they
answer identically.

OFFSETS ARE PER-SENTENCE AND STAY THAT WAY
------------------------------------------
Each entity's start/end are relative to ITS sentence, not the document. The caller adds the
sentence offset and slices the span text from the document, so
`document.text[start:end] == span.text` holds by construction. Doing that arithmetic here
would mean this service needed the document, which it does not have and must not need.
"""
import argparse
import os
import sys
import threading
import time

_MODEL = None
_STATE = {"status": "cold", "detail": "not loaded yet", "loaded_at": None}
# GLiNER is a torch model and a single instance is not safe to call concurrently. The
# extraction pipeline learned this already and serialises on its own lock; the cap is
# enforced by the ROUTER (MAX_INFLIGHT), and this lock is the backstop for anything that
# reaches the service another way.
_LOCK = threading.Lock()

MODEL_NAME = os.environ.get("GLINER_MODEL", "urchade/gliner_multi-v2.1")
DEFAULT_THRESHOLD = float(os.environ.get("GLINER_THRESHOLD", "0.2"))
DEFAULT_LABELS = [x.strip() for x in (os.environ.get(
    "GLINER_LABELS",
    "person,organization,location,product,event,document or standard,date,"
    "money amount,measurement")).split(",") if x.strip()]


def load():
    """Load once, at startup. -> (ok, detail).

    Loading lazily on the first request is the tempting alternative and it is worse: the
    first caller pays a ~30s model load inside its own timeout, the router records that as
    a slow node, and the cold start looks exactly like a degraded one.
    """
    global _MODEL
    if _MODEL is not None:
        return True, _STATE["detail"]
    t0 = time.time()
    try:
        from gliner import GLiNER
    except ImportError as e:
        _STATE.update(status="failed", detail="gliner not installed: %s" % e)
        return False, _STATE["detail"]
    try:
        torch_threads = int(os.environ.get("GLINER_THREADS", "0") or 0)
        if torch_threads > 0:
            import torch
            # Match the container's cpu cap. torch scales at ~6% efficiency past 8 threads
            # and competes with the model server for the same cores.
            torch.set_num_threads(torch_threads)
        _MODEL = GLiNER.from_pretrained(MODEL_NAME)
        _STATE.update(status="ready", loaded_at=time.time(),
                      detail="%s in %.1fs" % (MODEL_NAME, time.time() - t0))
        return True, _STATE["detail"]
    except Exception as e:
        _STATE.update(status="failed", detail="%s: %s" % (type(e).__name__, str(e)[:120]))
        return False, _STATE["detail"]


def extract(texts, labels=None, threshold=None):
    """-> list of per-text entity lists. Raises RuntimeError if the model is not resident."""
    if _MODEL is None:
        raise RuntimeError("model not loaded: %s" % _STATE["detail"])
    labels = list(labels) if labels else list(DEFAULT_LABELS)
    th = DEFAULT_THRESHOLD if threshold is None else float(threshold)
    out = []
    with _LOCK:
        for t in texts:
            # A blank sentence is not an error and must not shift the reply: the caller
            # zips this list against its own sentence list by POSITION.
            if not (t or "").strip():
                out.append([])
                continue
            ents = _MODEL.predict_entities(t, labels, threshold=th)
            out.append([{"start": int(e["start"]), "end": int(e["end"]),
                         "label": str(e["label"]),
                         "score": round(float(e.get("score", 0.0)), 3)}
                        for e in ents])
    return out


def build_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(title="GLiNER", version="1")
    load()

    @app.get("/healthz")
    def healthz():
        ok = _STATE["status"] == "ready"
        return JSONResponse({"ok": ok, "model": MODEL_NAME, **_STATE},
                            status_code=200 if ok else 503)

    @app.post("/extract")
    def do_extract(req: dict):
        req = req or {}
        texts = req.get("text", req.get("texts"))
        if not isinstance(texts, list) or not texts:
            raise HTTPException(400, "text must be a non-empty list of strings")
        if not all(isinstance(x, str) for x in texts):
            raise HTTPException(400, "every element of text must be a string")
        th = req.get("threshold")
        if th is not None:
            try:
                th = float(th)
            except (TypeError, ValueError):
                raise HTTPException(400, "threshold must be a number, got %r" % req.get("threshold"))
        t0 = time.time()
        try:
            results = extract(texts, req.get("labels"), th)
        except RuntimeError as e:
            # Not loaded is a SERVER state, not a bad request -- 503 so the router's
            # breaker treats it as this node being unavailable rather than as our bug.
            raise HTTPException(503, str(e))
        return {"results": results, "n_texts": len(texts),
                "elapsed_s": round(time.time() - t0, 3), "model": MODEL_NAME}

    return app


def __getattr__(name):
    # uvicorn imports `...app:app`. Built lazily so --demo runs with no fastapi and no
    # model present. There must be NO module-level `app = ...` -- see llmapi/server.py.
    if name == "app":
        return build_app()
    raise AttributeError(name)


def _demo():
    global _MODEL
    saved = _MODEL

    seen = []

    class _Fake:
        @staticmethod
        def predict_entities(text, labels, threshold=0.2):
            seen.append({"text": text, "labels": list(labels), "threshold": threshold})
            return ([{"start": 0, "end": 5, "label": "person", "score": 0.912345}]
                    if text.startswith("Cubic") else [])

    try:
        _MODEL = _Fake()
        out = extract(["Cubic wins a contract", "nothing here", "   ", ""])
        assert len(out) == 4, out
        # position is the contract: a blank input must yield [] IN PLACE, not vanish, or
        # the caller's zip against its own sentence list silently shifts by one
        assert out[0][0]["start"] == 0 and out[0][0]["label"] == "person", out[0]
        assert out[0][0]["score"] == 0.912, "score must be rounded to 3dp: %s" % out[0][0]
        assert out[1] == [] and out[2] == [] and out[3] == [], out

        # offsets are per-INPUT and untouched -- the caller owns document coordinates
        assert extract(["Cubic x"])[0][0]["end"] == 5

        # blanks never reach the model at all
        assert [s["text"] for s in seen] == ["Cubic wins a contract", "nothing here",
                                             "Cubic x"], [s["text"] for s in seen]
        # the default label set and threshold are applied when the caller sends neither
        assert "person" in seen[0]["labels"] and seen[0]["threshold"] == DEFAULT_THRESHOLD

        # a caller-supplied label set REPLACES the default rather than extending it, and a
        # caller-supplied threshold overrides
        seen.clear()
        extract(["Cubic x"], labels=["organization"], threshold=0.5)
        assert seen[0]["labels"] == ["organization"], seen[0]["labels"]
        assert seen[0]["threshold"] == 0.5, seen[0]["threshold"]

        _MODEL = None
        try:
            extract(["x"])
            raise AssertionError("an unloaded model must raise, not return []")
        except RuntimeError as e:
            assert "not loaded" in str(e), e
        print("ok  per-sentence offsets untouched, blanks hold their position, "
              "an unloaded model raises instead of quietly finding nothing")
    finally:
        _MODEL = saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--serve", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.serve:
        import uvicorn
        uvicorn.run(build_app(), host=os.environ.get("GLINER_BIND", "0.0.0.0"),
                    port=int(os.environ.get("GLINER_PORT", 8620)))
    else:
        ok, detail = load()
        print("%s  %s" % ("ok" if ok else "FAILED", detail))
