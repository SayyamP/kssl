"""What the pipeline imports. One way to reach a model, from anywhere in the codebase.

    from llmapi.client import ask, gliner
    text = ask("summarise this", npredict=300)

    python llmapi/client.py --demo      # self-check, no network
    python llmapi/client.py --ping      # is the API up, and what will serve a call

STDLIB ONLY, ON PURPOSE
-----------------------
The pipeline gets no new dependency from this. The API server pools connections with
httpx because it makes many outbound calls; a pipeline module makes one call per document
through a loopback socket, where pooling buys nothing worth a requirements line.

NO SILENT FALLBACK TO A DIRECT OLLAMA CALL
------------------------------------------
If the API is down this raises. The obvious "helpful" alternative -- fall back to
$KSSL_OLLAMA and call the model directly -- would mean the thing this module exists to
prevent (four modules dialling a model server on their own) reappears exactly when
nobody is watching, and the failure that caused it goes unnoticed because output still
appears. A missing API must be visible.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llmapi import nodes  # noqa: E402


class LLMAPIError(RuntimeError):
    """The API could not serve the call. Never swallow this into an empty string."""


def base_url():
    nodes.load_env()
    return (os.environ.get("LLMAPI_URL") or "http://127.0.0.1:8610").rstrip("/")


def _post(path, body, timeout, opener=None):
    url = base_url() + path
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            pass
        raise LLMAPIError("%s -> HTTP %s %s" % (url, e.code, detail))
    except Exception as e:
        raise LLMAPIError("%s -> %s: %s" % (url, type(e).__name__, str(e)[:90]))


def ask(prompt, npredict=300, timeout=None, model=None, fmt=None, node=None,
        with_meta=False, opener=None):
    """One generation. -> str (or (str, meta) when with_meta).

    `timeout` is the CLIENT's patience, and it must out-wait the WHOLE failover chain --
    every node, every attempt, plus backoff -- not one call. Sized to one call, the client
    hangs up on a request the server is still legitimately serving, and the generation is
    charged with nothing to show for it. nodes.worst_case_s() is that number, computed from
    the same config the server routes by.
    """
    if not prompt or not str(prompt).strip():
        raise LLMAPIError("prompt is empty")
    if timeout is None:
        nodes.load_env()
        # worst_case_s is computed from the CLIENT's view of the config. A client whose
        # .env does not describe the nodes (compose sets them only inside the server
        # container) computes 0, and 0 + 60 would hang up after a minute on a generation
        # the server is still legitimately running -- so fall back to one full-ceiling call.
        #
        # `or`, NOT `max`. With max() the fallback won every configured case too: the real
        # 722s chain was rounded up to a flat 1860s, so an 80-token verdict waited 31
        # minutes on a hung API and the tokens-derived patience never applied at all. The
        # fallback is for the degenerate case only.
        timeout = (nodes.worst_case_s(npredict) or nodes._f("LLM_TIMEOUT_CEIL", 1800)) + 60
    body = {"prompt": str(prompt), "npredict": int(npredict)}
    for k, v in (("model", model), ("format", fmt), ("node", node)):
        if v:
            body[k] = v
    d = _post("/v1/generate", body, timeout, opener=opener)
    text = (d.get("response") or "").strip()
    return (text, d) if with_meta else text


def gliner(texts, labels=None, threshold=None, node=None, timeout=180, opener=None):
    """Batched NER. -> list of per-text entity lists.

    Offsets are relative to each input string, exactly as the upstream service returns
    them. The caller shifts them into document coordinates and slices the span text from
    the document, so `document.text[start:end] == span.text` holds by construction.
    """
    texts = list(texts)
    if not texts:
        return []
    body = {"texts": texts}
    if labels:
        body["labels"] = list(labels)
    if threshold is not None:
        body["threshold"] = float(threshold)
    if node:
        body["node"] = node
    return _post("/v1/gliner", body, timeout, opener=opener).get("results", [])


def health(timeout=10, opener=None):
    url = base_url() + "/healthz"
    try:
        with (opener or urllib.request.urlopen)(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "problems": ["HTTP %s" % e.code]}
    except Exception as e:
        return {"ok": False, "problems": ["%s: %s" % (type(e).__name__, str(e)[:90])]}


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _demo():
    base = dict(os.environ)
    try:
        os.environ["LLMAPI_URL"] = "http://127.0.0.1:8610/"
        assert base_url() == "http://127.0.0.1:8610", base_url()

        sent = []

        def ok(req, timeout=None):
            sent.append((req.full_url, json.loads(req.data.decode()), timeout))
            return _Resp({"response": "  hi  ", "node": "vps-b", "eval_count": 4})

        assert ask("q", opener=ok) == "hi"
        url, body, timeout = sent[0]
        assert url == "http://127.0.0.1:8610/v1/generate", url
        assert body == {"prompt": "q", "npredict": 300}, body
        # THE CLIENT MUST OUT-WAIT THE WHOLE CHAIN, not one call. Two nodes at two attempts
        # each is four generations plus backoff; patience sized to one abandons work in
        # flight. Computed against the real config, not against the constant it came from.
        os.environ.update({"LLM_NODE_ORDER": "vps-b,farm", "LLM_RETRIES": "2",
                           "VPSB_URL": "http://127.0.0.1:11434", "VPSB_ENABLED": "1",
                           "VPSB_TOK_S": "11.95", "FARM_URL": "https://f.example",
                           "FARM_ENABLED": "1", "FARM_TOK_S": "53.5", "FARM_OPENAI": "1",
                           "FARM_API_KEY": "k"})
        chain = nodes.worst_case_s(300)
        one_call = nodes.read_timeout(300, 11.95)
        assert chain > one_call, "a 2-node x 2-attempt chain must exceed one call"
        sent.clear()
        ask("q", opener=ok)
        assert sent[0][2] > chain, "client patience %s must exceed the chain %s" % (sent[0][2], chain)

        text, meta = ask("q", with_meta=True, opener=ok)
        assert text == "hi" and meta["node"] == "vps-b", meta

        # optional fields are only sent when set -- an explicit null model would override
        # the server's own default with nothing
        sent.clear()
        ask("q", npredict=600, model="m", node="farm", fmt={"type": "object"}, opener=ok)
        assert sent[0][1] == {"prompt": "q", "npredict": 600, "model": "m",
                              "node": "farm", "format": {"type": "object"}}, sent[0][1]

        # an empty prompt never reaches the wire
        sent.clear()
        for bad in ("", "   ", None):
            try:
                ask(bad, opener=ok)
                raise AssertionError("empty prompt must raise")
            except LLMAPIError:
                pass
        assert not sent, "an empty prompt must not be sent: %s" % sent

        # A DOWN API RAISES. It must never come back as an empty string, which downstream
        # would store as a real "no answer".
        def dead(req, timeout=None):
            raise OSError("connection refused")
        try:
            ask("q", opener=dead)
            raise AssertionError("a down API must raise, not return ''")
        except LLMAPIError as e:
            assert "connection refused" in str(e), str(e)

        # a server-side error surfaces its detail rather than a bare status
        def http500(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 502, "Bad Gateway", {},
                __import__("io").BytesIO(json.dumps({"detail": "every node failed"}).encode()))
        try:
            ask("q", opener=http500)
            raise AssertionError("502 must raise")
        except LLMAPIError as e:
            assert "every node failed" in str(e), str(e)

        # gliner: empty input short-circuits without a call; results pass through untouched
        sent.clear()
        assert gliner([], opener=ok) == []
        assert not sent

        def gl(req, timeout=None):
            sent.append(json.loads(req.data.decode()))
            return _Resp({"results": [[{"start": 2, "end": 5, "label": "person"}], []]})

        res = gliner(["ab cde", "x"], threshold=0.3, opener=gl)
        assert res[0][0]["start"] == 2 and res[1] == [], res
        assert sent[0] == {"texts": ["ab cde", "x"], "threshold": 0.3}, sent[0]

        # health degrades to a dict rather than raising -- a status call must always answer
        h = health(opener=dead)
        assert h["ok"] is False and h["problems"], h
        print("ok  a down API raises instead of returning '', and empty prompts never "
              "reach the wire")
    finally:
        os.environ.clear()
        os.environ.update(base)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--ping", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.ping:
        print(json.dumps(health(), indent=2))
    else:
        print(base_url())
