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
# HOW MANY TIMES THE FARM IS ASKED BEFORE IT COUNTS AS DOWN. The gateway 502s under
# load and recovers in seconds; one attempt then a 60s blackout meant a single
# transient error handed the next minute of SERVING-TABLE writes to a 7b on a CPU box,
# while the very next log line said FARM RECOVERED. Measured on production
# 2026-09-06: the enrich log is pairs of DOWN/RECOVERED seconds apart, and every call
# in between was answered by the fallback.
FARM_TRIES = int(os.environ.get("FARM_TRIES", "3"))
FARM_RETRY_S = float(os.environ.get("FARM_RETRY_S", "1.5"))
FARM_TIMEOUT = float(os.environ.get("FARM_TIMEOUT_S", "120"))
UA = os.environ.get("C_USER_AGENT", "curl/8.4.0")

_HTTP = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
    headers={"User-Agent": UA},
)


def _alert(msg):
    print(f"[ALERT] signals: {msg}", file=sys.stderr, flush=True)


def _is_config_error(e):
    """True for a failure that WILL repeat: a bad model name, a bad key. 429 is not
    one -- that is the gateway asking us to slow down, and it is worth retrying."""
    r = getattr(e, "response", None)
    code = getattr(r, "status_code", None)
    return code is not None and 400 <= code < 500 and code not in (408, 429)


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
        """The farm answers, or the fallback does -- but the farm gets asked properly
        first. THE FALLBACK IS FOR A FARM THAT IS DOWN, not for a farm that hiccuped.
        """
        # PRIMARY: farm, unless it's in cooldown from a recent run of failures.
        if time.time() >= self._skip_until:
            last, tried = None, 0
            for attempt in range(1, max(1, FARM_TRIES) + 1):
                tried = attempt
                try:
                    text, meta = self._ask_farm(prompt, npredict, timeout)
                    if self._down:
                        self._down = False
                        _alert(f"FARM RECOVERED -> primary restored [{FARM_URL}]")
                    return (text, meta) if with_meta else text
                except Exception as e:                            # noqa: BLE001
                    last = e
                    # A CONFIG ERROR IS NOT AN OUTAGE. 400 "Invalid model name" and 401
                    # fail identically on every retry and on every later call; retrying
                    # them wastes the pass and hides the cause. This is the shape that
                    # cost two days in September 2026, when a retired alias 400'd and
                    # both containers looked healthy while writing nothing.
                    if _is_config_error(e):
                        _alert(f"FARM CONFIG ERROR ({type(e).__name__}: {e}) -- the "
                               f"model name or key is wrong, not the farm. Check "
                               f"C_MODEL={FARM_MODEL!r}. Falling back to {FB_URL}, "
                               f"which runs {FB_MODEL} -- NOT the serving model.")
                        break
                    if attempt < max(1, FARM_TRIES):
                        time.sleep(FARM_RETRY_S * attempt)
            # Only now is the farm considered down.
            self._skip_until = time.time() + COOLDOWN
            if not self._down:
                self._down = True
                _alert(f"FARM DOWN after {tried} attempt(s) "
                       f"({type(last).__name__}: {last}) -> failing over to VPS-A "
                       f"[{FB_URL}], retry farm in ~{COOLDOWN}s")
        # FALLBACK: VPS-A.
        text, meta = self._ask_vpsa(prompt, npredict, timeout)
        return (text, meta) if with_meta else text


client = _Client()


if __name__ == "__main__":
    # ponytail: self-check the failover logic with a fake transport (no network).
    # Retries are real sleeps, so the backoff is zeroed here -- the thing under test is
    # WHICH backend answers and WHEN the farm is written off, not how long it waits.
    FARM_RETRY_S = 0.0
    c = _Client()
    calls = []

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def _http_error(code):
        e = httpx.HTTPStatusError("boom", request=None, response=_Resp(code))
        return e

    def fake_farm(prompt, npredict, timeout):
        calls.append("farm")
        code = os.environ.get("_FARM_HTTP")
        if code:
            raise _http_error(int(code))
        if os.environ.get("_FARM_BROKEN"):
            raise httpx.ConnectError("refused")
        return "farm-ok", {"via": "farm"}

    def fake_vpsa(prompt, npredict, timeout):
        calls.append("vps-a")
        return "vpsa-ok", {"via": "vps-a"}

    c._ask_farm, c._ask_vpsa = fake_farm, fake_vpsa

    assert c.ask("hi") == "farm-ok" and calls[-1] == "farm", "healthy -> farm"

    # A HICCUP IS NOT AN OUTAGE. This is the whole point: the gateway 502s under load
    # and recovers in a second, and one attempt then a 60s blackout handed a minute of
    # SERVING-TABLE writes to a 7b on a CPU box while the next log line said RECOVERED.
    calls.clear()
    _n = {"i": 0}

    def flaky_farm(prompt, npredict, timeout):
        calls.append("farm")
        _n["i"] += 1
        if _n["i"] == 1:
            raise _http_error(502)
        return "farm-ok", {"via": "farm"}

    c._ask_farm = flaky_farm
    assert c.ask("hi") == "farm-ok", "one 502 must not reach the fallback"
    assert calls == ["farm", "farm"], f"expected a retry on the farm, got {calls}"
    assert not c._down and c._skip_until <= time.time(), \
        "a single transient error must not write the farm off"

    # 429 is the gateway asking us to slow down, not a broken config: retry it.
    calls.clear(); _n["i"] = 0
    c._ask_farm = flaky_farm
    os.environ.pop("_FARM_HTTP", None)
    assert c.ask("hi") == "farm-ok" and calls.count("farm") == 2, "429/502 are retried"

    # A REAL OUTAGE still fails over, and only after the farm has actually been tried.
    calls.clear()
    c._ask_farm = fake_farm
    os.environ["_FARM_BROKEN"] = "1"
    assert c.ask("hi") == "vpsa-ok" and calls[-1] == "vps-a", "farm error -> vps-a"
    assert calls.count("farm") == FARM_TRIES, \
        f"the farm gets {FARM_TRIES} attempts before it counts as down, got {calls}"
    assert c._down and c._skip_until > time.time(), "tripped + cooldown set"
    calls.clear()
    assert c.ask("hi") == "vpsa-ok" and calls == ["vps-a"], "cooldown skips farm probe"
    del os.environ["_FARM_BROKEN"]

    # A CONFIG ERROR IS NOT RETRIED. A bad model name fails identically every time, and
    # burning three attempts per call on it is how a two-day outage looks healthy.
    c2 = _Client()
    c2._ask_farm, c2._ask_vpsa = fake_farm, fake_vpsa
    calls.clear()
    os.environ["_FARM_HTTP"] = "400"
    assert c2.ask("hi") == "vpsa-ok", "config error still answers, via the fallback"
    assert calls.count("farm") == 1, \
        f"a 400 must be tried once, not {calls.count('farm')} times"
    del os.environ["_FARM_HTTP"]

    # ...and recovery is announced once the farm answers again.
    c._skip_until = 0.0
    calls.clear()
    assert c.ask("hi") == "farm-ok" and not c._down, "farm back -> primary restored"
    print("ok - the fallback is for a farm that is down, not one that hiccuped")
