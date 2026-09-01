"""Minimal LLM client for the signal-fill step. Talks to VPS-A's Ollama over the reverse
tunnel (OLLAMA_URL, default 127.0.0.1:11500) using Ollama's NATIVE /api/chat endpoint.

Native (not the OpenAI /v1 shape) on purpose: qwen2.5:7b-instruct advertises a 32k default
context, and the OpenAI endpoint lets Ollama allocate a KV cache for the whole thing -- on a
CPU node that means minutes of thrash and an opaque HTTP 500. /api/chat takes options.num_ctx,
so we pin a small context (the prompt is ~1-2k tokens) and the request is cheap. keep_alive
holds the model in memory between docs so each call doesn't pay a cold reload.
"""
import os
import httpx

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
API_KEY = os.environ.get("OLLAMA_API_KEY", "")
UA = os.environ.get("C_USER_AGENT", "curl/8.4.0")
NUM_CTX = int(os.environ.get("KSSL_NUM_CTX", "8192"))
TEMP = float(os.environ.get("KSSL_LLM_TEMP", "0"))
KEEP_ALIVE = os.environ.get("KSSL_KEEP_ALIVE", "15m")

_HTTP = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
    headers={"User-Agent": UA},
)


class _Client:
    def ask(self, prompt, npredict=300, timeout=None, model=None, with_meta=False):
        opts = {"num_ctx": NUM_CTX, "num_predict": int(npredict), "temperature": TEMP}
        body = {
            "model": model or os.environ.get("KSSL_MODEL", "qwen2.5:7b-instruct"),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": opts,
        }
        headers = {"Authorization": "Bearer " + API_KEY} if API_KEY else None
        r = _HTTP.post(OLLAMA + "/api/chat", json=body, headers=headers,
                       timeout=timeout or 600.0)
        r.raise_for_status()
        j = r.json()
        text = (j.get("message") or {}).get("content", "")
        meta = {"eval_count": j.get("eval_count", 0)}
        return (text, meta) if with_meta else text


client = _Client()
