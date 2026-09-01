"""LLM client for the signal-fill step (serving tables).

PRIMARY is the farm (GPU, OpenAI /v1 via LiteLLM) -- fast. FALLBACK is VPS-A's Ollama
(native /api/chat over the :11500 tunnel) -- slow CPU, used ONLY when the farm is
unreachable. Every failover and recovery prints a loud, greppable [ALERT] line to stderr
so it surfaces in `docker logs extraction-signals-1`.

A tripped farm is skipped for FARM_COOLDOWN_S before we probe it again, so a farm outage
doesn't pay a farm timeout on every single card.

Model ids differ per backend, so the caller's `model=` arg is ignored: farm uses C_MODEL
(the LiteLLM alias, default "text-model"), VPS-A uses FALLBACK_MODEL ("qwen2.5:7b-instruct").
"""
import os
import sys
import time
import httpx

# --- primary: farm (same vars the extraction workers already use) ---
FARM_URL = os.environ.get("OLLAMA_URL", "https://farm-llm.i3softlab.com").rstrip("/")
FARM_KEY = os.environ.get("OLLAMA_API_KEY", "")
FARM_MODEL = os.environ.get("C_MODEL", "text-model")

# --- fallback: VPS-A ollama over the reverse tunnel ---
FB_URL = os.environ.get("FALLBACK_URL", "http://127.0.0.1:11500").rstrip("/")
FB_MODEL = os.environ.get("FALLBACK_MODEL", "qwen2.5:7b-instruct")

TEMP = float(os.environ.get("KSSL_LLM_TEMP", "0"))
NUM_CTX = int(os.environ.get("KSSL_NUM_CTX", "8192"))
KEEP_ALIVE = os.environ.get("KSSL_KEEP_ALIVE", "15m")
COOLDOWN = int(os.environ.get("FARM_COOLDOWN_S", "60"))
FARM_TIMEOUT = float(os.environ.get("FARM_TIMEOUT_S", "120"))
UA = os.environ.get("C_USER_AGENT", "curl/8.4.0")

_HTTP = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
    headers={"User-Agent": UA},
)


def _alert(msg):
    print(f"[ALERT] signals: {msg}", file=sys.stderr, flush=True)


class _Client:
    def __init__(self):
        self._down = False          # is the farm currently considered down?
        self._skip_until = 0.0      # epoch; while now < this, don't probe the farm

    def _ask_farm(self, prompt, npredict, timeout):
        body = {
            "model": FARM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMP,
            "max_tokens": int(npredict),
        }
        h = {"Authorization": "Bearer " + FARM_KEY} if FARM_KEY else None
        r = _HTTP.post(FARM_URL + "/v1/chat/completions", json=body, headers=h,
                       timeout=timeout or FARM_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        meta = {"eval_count": (j.get("usage") or {}).get("completion_tokens", 0), "via": "farm"}
        return text, meta

    def _ask_vpsa(self, prompt, npredict, timeout):
        body = {
            "model": FB_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": NUM_CTX, "num_predict": int(npredict), "temperature": TEMP},
        }
        r = _HTTP.post(FB_URL + "/api/chat", json=body, timeout=timeout or 600.0)
        r.raise_for_status()
        j = r.json()
        text = (j.get("message") or {}).get("content", "")
        meta = {"eval_count": j.get("eval_count", 0), "via": "vps-a"}
        return text, meta

    def ask(self, prompt, npredict=300, timeout=None, model=None, with_meta=False):
        # PRIMARY: farm, unless it's in cooldown from a recent failure.
        if time.time() >= self._skip_until:
            try:
                text, meta = self._ask_farm(prompt, npredict, timeout)
                if self._down:
                    self._down = False
                    _alert(f"FARM RECOVERED -> primary restored [{FARM_URL}]")
                return (text, meta) if with_meta else text
            except Exception as e:
                self._skip_until = time.time() + COOLDOWN
                if not self._down:
                    self._down = True
                    _alert(f"FARM DOWN ({type(e).__name__}: {e}) "
                           f"-> failing over to VPS-A [{FB_URL}], retry farm in ~{COOLDOWN}s")
        # FALLBACK: VPS-A.
        text, meta = self._ask_vpsa(prompt, npredict, timeout)
        return (text, meta) if with_meta else text


client = _Client()


if __name__ == "__main__":
    # ponytail: self-check the failover logic with a fake transport (no network).
    c = _Client()
    calls = []

    def fake_farm(prompt, npredict, timeout):
        calls.append("farm")
        if os.environ.get("_FARM_BROKEN"):
            raise httpx.ConnectError("refused")
        return "farm-ok", {"via": "farm"}

    def fake_vpsa(prompt, npredict, timeout):
        calls.append("vps-a")
        return "vpsa-ok", {"via": "vps-a"}

    c._ask_farm, c._ask_vpsa = fake_farm, fake_vpsa

    assert c.ask("hi") == "farm-ok" and calls[-1] == "farm", "healthy -> farm"
    os.environ["_FARM_BROKEN"] = "1"
    assert c.ask("hi") == "vpsa-ok" and calls[-1] == "vps-a", "farm error -> vps-a"
    assert c._down and c._skip_until > time.time(), "tripped + cooldown set"
    calls.clear()
    assert c.ask("hi") == "vpsa-ok" and calls == ["vps-a"], "cooldown skips farm probe"
    del os.environ["_FARM_BROKEN"]
    c._skip_until = 0  # expire cooldown
    assert c.ask("hi") == "farm-ok" and not c._down, "farm back -> recovered"
    print("llmapi self-check OK")
