"""The node table: who can serve a model call, from THIS host, right now.

    python llmapi/nodes.py --demo        # self-check, no network
    python llmapi/nodes.py --status      # probe every enabled node and say what answers

WHY A TABLE AND NOT A URL
-------------------------
Every LLM call used to be `urllib.request.urlopen(OLLAMA + "/api/generate")` with OLLAMA
read from one environment variable, copied into four modules. That works exactly as long
as there is one model server. There are four, they are not interchangeable, and two of
them cannot be reached from the box this code runs on.

THE ADDRESS IS RELATIVE TO THE CALLER, AND THAT IS THE WHOLE POINT
------------------------------------------------------------------
`http://127.0.0.1:11434` is a correct address for vps-a's Ollama -- on vps-a. From
vps-b it is vps-b's own Ollama, and the call silently succeeds against the wrong
machine. `172.24.0.2:11434` is correct for the DC -- inside the DC's docker network;
from anywhere else it is a connect that hangs until the timeout.

Neither failure raises anything that says "wrong host". So every URL here is declared
as "the address as seen from LLM_ORIGIN", a node with no such address is DISABLED
rather than guessed at, and starting on the wrong host is a startup error.

WHY THE TIMEOUT IS DERIVED AND NOT CONFIGURED
---------------------------------------------
`stream: False` means the whole reply must arrive inside one read, so the read timeout
IS the total generation time. A fixed 180s is a GPU-era number: the 7B on vps-b's four
pinned cores does ~11 tok/s, so a 600-token answer needs 55s of generation plus prefill,
and a long one runs past it. The socket then closes with an empty body -- the reply is
lost whole and the work is charged anyway. Deriving it from the tokens actually asked
for lets an honest long generation finish while still bounding a degenerate one.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_env(path=None):
    """Read .env into os.environ without adding a dependency.

    Values already in the environment WIN: compose and the shell are more specific than
    a file on disk, and a config loader that overrides the operator is a trap.
    """
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), _value(v)
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


def _value(raw):
    """One .env value, with the inline comment removed and quotes stripped.

    A '#' INSIDE A VALUE IS A CHARACTER, NOT A COMMENT. Splitting on a bare '#' truncates
    any secret containing one -- and a Bearer token silently cut short makes the farm answer
    530, which reads exactly like the farm being down. So a comment must be preceded by
    whitespace, and a quoted value is taken whole.
    """
    v = raw.strip()
    for q in ('"', "'"):
        if len(v) >= 2 and v[0] == q:
            end = v.find(q, 1)
            if end > 0:
                return v[1:end]            # quoted: everything after the closing quote is comment
    cut = len(v)
    for i, ch in enumerate(v):
        if ch == "#" and (i == 0 or v[i - 1].isspace()):
            cut = i
            break
    return v[:cut].strip()


def _f(key, default):
    try:
        return float(os.environ.get(key) or default)
    except ValueError:
        return float(default)


def _i(key, default):
    try:
        return int(float(os.environ.get(key) or default))
    except ValueError:
        return int(default)


def _on(key, default="0"):
    return (os.environ.get(key) or default).strip().lower() in ("1", "true", "yes", "on")


# Node ids are fixed: these four are the fleet, and a typo in LLM_NODE_ORDER must be an
# error rather than a silently ignored name.
KNOWN = ("vps-b", "vps-a", "dc", "farm")
# Origins that are NOT fleet nodes: a workstation running the code while every model
# server stays remote. See check_config for what this changes.
LOCAL_ORIGINS = ("local", "workstation")
_PREFIX = {"vps-b": "VPSB", "vps-a": "VPSA", "dc": "DC", "farm": "FARM"}


def table():
    """-> {node_id: dict}. Pure function of the environment; no network."""
    out = {}
    for nid in KNOWN:
        p = _PREFIX[nid]
        url = (os.environ.get("%s_URL" % p) or "").strip().rstrip("/")
        out[nid] = {
            "id": nid,
            "url": url,
            # A node with no URL is not enabled, whatever the flag says. Two switches for
            # one decision is how a node ends up "enabled" and undialable.
            "enabled": _on("%s_ENABLED" % p) and bool(url),
            "enabled_flag": _on("%s_ENABLED" % p),
            "tok_s": _f("%s_TOK_S" % p, 4.0),
            "openai": _on("%s_OPENAI" % p),
            # A per-node model, because the farm serves "text-model" while the Ollama nodes
            # serve "qwen2.5:7b-instruct" -- a single NODE_MODEL cannot name both. Falls back
            # to NODE_MODEL in call_node when blank.
            "model": (os.environ.get("%s_MODEL" % p) or "").strip(),
            "api_key": (os.environ.get("%s_API_KEY" % p) or "").strip(),
            "threads": _i("%s_THREADS" % p, 0),
            "cpu": _on("%s_CPU" % p),
        }
    return out


def order():
    """Preference order, filtered to nodes that are actually dialable. RAISES on a typo.

    Strict on purpose, and therefore ONLY for validation and the CLI. A serving path must
    call live_order() instead: a bad LLM_NODE_ORDER is exactly the config error /healthz
    exists to REPORT, so letting it raise inside the handler turns the one endpoint that
    must always answer into a bare 500 with no reason attached.
    """
    t = table()
    want = [n.strip() for n in (os.environ.get("LLM_NODE_ORDER") or "vps-b").split(",") if n.strip()]
    bad = [n for n in want if n not in KNOWN]
    if bad:
        raise ValueError("LLM_NODE_ORDER names unknown node(s) %s; known: %s"
                         % (", ".join(bad), ", ".join(KNOWN)))
    return [n for n in want if t[n]["enabled"]]


def live_order():
    """order() for request handlers: a bad config is an empty chain, never an exception.

    Every serving path uses this. check_config() still reports the typo by name, so the
    operator gets a 503 that says what is wrong instead of a 500 that says nothing.
    """
    try:
        return order()
    except ValueError:
        return []


def origin():
    return (os.environ.get("LLM_ORIGIN") or "").strip() or None


# --- the cost model, taken from route.py rather than re-invented ----------------------
# route.py routes DOCUMENTS to nodes; this routes CALLS to model servers. Same fleet, same
# constants, and deliberately the same shape of decision, because two routers on one fleet
# that disagree about what a node can do is how a queue and its workers drift apart.
#
# WHAT WAS NOT COPIED, AND WHY: route.py's `class` ladder. Freshness and trust tier are
# properties of a DOCUMENT waiting in a queue; a model call has already been admitted --
# route.py decided that. Re-deciding priority here would be a second admission control
# behind the first.
#
# WHAT WAS COPIED, because it is the part that generalises:
#   * a node has a TIME BUDGET, and its capacity is derived from that budget and its own
#     measured rate -- never a hand-set share
#   * eligibility is STRICT first; the length/size limit relaxes only when nothing is
#     eligible, and the FALLBACK_MULTIPLE that bounds the relaxation is route.py's 3.0
#   * health is checked BEFORE dispatch, cached, and a bad result is re-checked sooner
#     than a good one (SVC_TTL_BAD < SVC_TTL_OK)
#   * a node that cannot take this call is DEMOTED, never removed. route.py: parking is
#     terminal, so it must mean "impossible", never "nobody is up right now"
FALLBACK_MULTIPLE = 3.0
SVC_TTL_OK, SVC_TTL_BAD = 60.0, 15.0

# Each node's own budget for ONE unit of work, in minutes -- route.NODES's `minutes`.
_BUDGET_MIN = {"vps-a": 20, "vps-b": 22, "dc": 85, "farm": 40}


def budget_s(nid):
    return 60.0 * _f("%s_BUDGET_MIN" % _PREFIX[nid], _BUDGET_MIN.get(nid, 20))


def est_seconds(npredict, tok_s):
    """How long this node should take to produce `npredict` tokens.

    route.py estimates output tokens from input chars (ALPHA = 4.82 tokens per char)
    because a queued document has no other signal. Here npredict IS the request, so the
    estimate starts one step further along and needs no ALPHA.
    """
    return float(npredict) / max(0.01, tok_s)


# --- GLiNER: a second service on the same fleet, routed the same way -----------------
# It runs on EVERY node now, not just the farm. The farm is measured as "often not alive
# 2-3 hours straight", and a design whose only GLiNER is the farm's has a single point of
# failure wearing a redundancy label. In-process torch was the other option and is worse
# at scale: a ~2 GB model in every extraction process, and capacity no router can see.
#
# COST IS NOT TOKENS. A generation's cost is npredict / tok_s. GLiNER is a forward pass
# over text -- cost scales with how much text goes in, and nothing comes out to meter. So
# it needs its own rate, in characters per second, and its own budget.
#
# GLINER_CPS IS UNMEASURED. This project's own rule: `unrated` is not a synonym for a bad
# score, it means nobody has assessed it. 20,000 c/s is a deliberately conservative
# placeholder for a small CPU model -- measure it per node and set <NODE>_GLINER_CPS
# before trusting the routing to prefer one node over another for GLiNER.
_GLINER_CPS_DEFAULT = 20000.0


def gliner_url(nid):
    return (os.environ.get("%s_GLINER_URL" % _PREFIX[nid]) or "").strip().rstrip("/")


def gliner_enabled(nid):
    """A node serves GLiNER only if it has a URL. Same rule as the model server: two
    switches for one decision is how a node ends up enabled and undialable."""
    return bool(gliner_url(nid)) and _on("%s_GLINER_ENABLED" % _PREFIX[nid], "1")


def gliner_cps(nid):
    return _f("%s_GLINER_CPS" % _PREFIX[nid], _GLINER_CPS_DEFAULT)


def gliner_order():
    """Which nodes may serve GLiNER, in configured preference order."""
    want = [n.strip() for n in
            (os.environ.get("GLINER_NODE_ORDER") or os.environ.get("LLM_NODE_ORDER")
             or "vps-b").split(",") if n.strip()]
    return [n for n in want if n in KNOWN and gliner_enabled(n)]


def est_gliner_seconds(chars, cps):
    return float(chars) / max(1.0, cps)


def gliner_fits(nid, chars, relaxed=False):
    limit = budget_s(nid) * (FALLBACK_MULTIPLE if relaxed else 1.0)
    return est_gliner_seconds(chars, gliner_cps(nid)) <= limit


def fits(nid, npredict, tok_s, relaxed=False):
    """Can this node finish this call inside its budget? route.py's `cap`, per call.

    The cap there is `minutes * 60 * tok_s / ALPHA` -- a length limit derived from a TIME
    budget. Same idea: the dc at 1.5 tok/s can honestly serve an 80-token verdict (53s) and
    cannot serve a 2,000-token profile (22 min, over its own budget). That one rule routes
    small calls anywhere and large calls to the fast nodes, with nothing to tune.
    """
    limit = budget_s(nid) * (FALLBACK_MULTIPLE if relaxed else 1.0)
    return est_seconds(npredict, tok_s) <= limit


def max_inflight(nid):
    """Concurrent calls this node may hold.

    NOT a tuning knob -- it is a property of the server. vps-b and the dc run Ollama with
    OLLAMA_NUM_PARALLEL=1, so they serve ONE request at a time and everything else sits in
    OLLAMA_MAX_QUEUE; sending a second concurrent call there buys queue latency and nothing
    else. The farm was measured at N=12 concurrent, and route.py's note is worth repeating:
    it is a FAST node, not a wide one -- do not model it as unlimited.
    """
    return max(1, _i("%s_MAX_INFLIGHT" % _PREFIX[nid], 12 if nid == "farm" else 1))


def check_config():
    """-> list of problems. Empty means this config can work on this host.

    Called at server startup. A config that cannot serve a single call should fail loudly
    on boot, not on the first request an hour later.
    """
    bad = []
    t = table()
    o = origin()
    # `local` is a legitimate origin: the code runs on a workstation that is NOT part of
    # the fleet, and every node -- including vps-b -- is reached through a local ssh
    # forward. That inverts the loopback rule below, so it has to be a declared value
    # rather than something inferred from an unrecognised string.
    if o and o not in KNOWN and o not in LOCAL_ORIGINS:
        bad.append("LLM_ORIGIN=%r is not one of %s (or %s for an off-fleet workstation)"
                   % (o, ", ".join(KNOWN), "/".join(sorted(LOCAL_ORIGINS))))
    if o in LOCAL_ORIGINS:
        # WITH LOCAL FORWARDS, LOOPBACK IS EXPECTED AND THE REAL HAZARD IS A SHARED PORT.
        # Every node is 127.0.0.1:<some port> here, so the "is this another host's
        # loopback" check cannot fire -- but two nodes pointed at the SAME forward would
        # silently send one box's work to another, with both reporting healthy. That is
        # the same class of error, one layer along, so it is checked instead.
        seen = {}
        for nid, n in t.items():
            for kind, url in (("model", n["url"]), ("gliner", gliner_url(nid))):
                if not url or (kind == "model" and not n["enabled"]):
                    continue
                if kind == "gliner" and not gliner_enabled(nid):
                    continue
                if url in seen:
                    bad.append("%s and %s both point at %s -- one forward cannot serve two "
                               "nodes; give each its own port" % (seen[url], "%s %s" % (nid, kind), url))
                seen[url] = "%s %s" % (nid, kind)
    try:
        live = order()
    except ValueError as e:
        return [str(e)]
    if not live:
        bad.append("no node in LLM_NODE_ORDER is enabled with a URL -- nothing can serve a call")
    for nid, n in t.items():
        if n["enabled_flag"] and not n["url"]:
            bad.append("%s is ENABLED but has no %s_URL" % (nid, _PREFIX[nid]))
        if n["enabled"] and n["openai"] and not n["api_key"]:
            # The farm answers 530 without a key, which reads exactly like "the farm is
            # down" -- and would take the fastest node out of service while blaming it.
            bad.append("%s is OpenAI-shaped and enabled but %s_API_KEY is empty; it will "
                       "530 and look like an outage" % (nid, _PREFIX[nid]))
        # The loopback trap: only the origin may legitimately call its own loopback.
        if n["enabled"] and o in KNOWN and nid != o and _is_loopback(n["url"]):
            bad.append("%s points at %s, which from %s is %s's OWN Ollama, not %s's"
                       % (nid, n["url"], o, o, nid))
    return bad


def _is_loopback(url):
    """Is this URL's HOST a loopback address?

    Delegated to `ipaddress`, not hand-parsed. Hand-parsing kept missing forms that are all
    the same address: `127.0.0.2` (any of 127/8), `127.1` (inet_aton shorthand), the full
    `[0:0:0:0:0:0:0:1]`, and `::ffff:127.0.0.1`. `localhost.example.com` is a real remote
    host and must NOT match, and either string inside a PATH is not a host at all.
    """
    import ipaddress
    from urllib.parse import urlsplit
    u = (url or "").strip()
    if not u:
        return False
    if "//" not in u:
        u = "//" + u                       # a scheme-less value still has a host
    try:
        host = (urlsplit(u).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # `127.1` is a valid loopback address that ip_address rejects; inet_aton is the
        # thing that actually implements the shorthand, so ask it rather than guessing.
        import socket
        try:
            ip = ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))
        except (OSError, ValueError):
            return False                   # a real hostname, e.g. localhost.example.com
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_loopback or ip.is_unspecified)   # 0.0.0.0 binds everything, incl. loopback


def worst_case_s(npredict=300, table=None):
    """Longest a generate can legitimately take: every node, every attempt, plus backoff.

    Lives here because BOTH sides need it. The client has to out-wait the whole failover
    chain, not one call -- a client whose patience covers only one call abandons work the
    server is still legitimately doing, and the generation is charged with nothing to show.
    """
    t = table if table is not None else table_or_empty()
    per_node = max(1, _i("LLM_RETRIES", 2))
    backoff = _f("LLM_BACKOFF_S", 1.0)
    total = 0.0
    for nid in live_order():
        total += per_node * read_timeout(npredict, t[nid]["tok_s"])
        total += backoff * sum(range(1, per_node))
    return round(total, 1)


def table_or_empty():
    try:
        return table()
    except Exception:
        return {n: {"tok_s": 4.0} for n in KNOWN}


def read_timeout(tokens, tok_s):
    """Seconds to allow a generation asking for `tokens` output tokens.

    Floored so this can only ever grant MORE time than the old fixed value -- no call
    that used to succeed can start failing. Ceilinged because a model ignoring its stop
    condition should not hold a worker for an hour; against a repetition loop a bigger
    budget only buys a longer loop.
    """
    floor = _f("LLM_TIMEOUT_FLOOR", 180)
    ceil = _f("LLM_TIMEOUT_CEIL", 1800)
    safety = _f("LLM_TIMEOUT_SAFETY", 1.5)
    want = tokens / max(0.1, tok_s) * safety + 30.0
    return max(floor, min(ceil, want))


def options(node, npredict):
    """Ollama `options` for one call, from the node's own measured characteristics."""
    o = {"temperature": 0, "num_predict": int(npredict),
         "num_ctx": _i("NODE_NUM_CTX", 8192)}
    if node.get("cpu"):
        o["num_gpu"] = 0
    # Ollama sizes its thread pool from the HOST's core count and ignores the cgroup
    # quota, so a capped container spends its slice context-switching between threads it
    # cannot run. Measured on the 8-core VPS: 4 cores 6.0 -> 11.4 tok/s when pinned.
    if node.get("threads"):
        o["num_thread"] = int(node["threads"])
    return o


def probe(node, timeout=6.0, fetch=None, model=None):
    """Is this node answering, and does it hold the model we require?

    Checking the MODEL and not just the port matters: an Ollama with nothing pulled
    answers /api/tags instantly and 200s, then fails or spends 150s loading on the first
    real request.
    """
    # The FULL tag, not the family. Splitting on ':' matches `qwen2.5:0.5b` when `qwen2.5:7b`
    # is required -- the probe then reports healthy while the model we actually ask for is
    # absent, and the first real call either fails or spends ~150s loading.
    # The per-node model is authoritative: the farm serves "text-model" while the Ollama nodes
    # serve "qwen2.5:7b-instruct". status()/healthz call probe(n) with no model arg, so without
    # this the farm was probed for NODE_MODEL and reported down while generate() (which does read
    # node["model"]) called it fine -- an accurate-looking dashboard lie that also skips the farm
    # anywhere dispatch is probe-gated.
    want = model or node.get("model") or os.environ.get("NODE_MODEL") or "qwen2.5:7b"
    url = node["url"] + ("/v1/models" if node["openai"] else "/api/tags")
    try:
        body = fetch(url, node, timeout) if fetch else _get(url, node, timeout)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:70])
    # PARSE the list; do not substring-match the body. `want in body` is true for a node
    # holding only `qwen2.5:0.5b` when `qwen2.5` is wanted, and true for `qwen2.5:7b` when
    # the node holds only `qwen2.5:7b-instruct-q4_0` -- a different model. Both report a
    # healthy node whose first real call fails or spends ~150s loading.
    have = _model_names(body)
    if have is None:
        # Unparseable: fall back to substring rather than calling a live node dead, but say
        # the check was weak instead of claiming a match it did not really verify.
        return (want in body, "unparseable model list; matched by substring")
    tag = want if ":" in want else want + ":latest"
    ok = want in have or tag in have
    return (True, "serving %s" % want) if ok else (
        False, "up but %s absent (has %s)" % (want, ", ".join(sorted(have)[:4]) or "nothing"))


def _model_names(body):
    """-> set of exact model names, or None if the body is not a shape we know.

    Ollama /api/tags is {"models":[{"name": "qwen2.5:7b"}]}; the OpenAI-shaped gateway is
    {"data":[{"id": "qwen2.5:7b"}]}.
    """
    try:
        d = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    for key, field in (("models", "name"), ("data", "id")):
        v = d.get(key)
        if isinstance(v, list):
            out = set()
            for m in v:
                if isinstance(m, dict) and m.get(field):
                    out.add(str(m[field]))
                elif isinstance(m, str) and m:
                    out.add(m)            # some servers return a bare list of names
            # AN EMPTY LIST IS AN ANSWER, NOT A PARSE FAILURE. `if out:` here made a freshly
            # pulled-nothing Ollama -- the exact state this probe exists to catch -- fall
            # through to the substring branch and report "unparseable model list" instead of
            # the truthful "up but <model> absent (has nothing)".
            return out
    return None


def _get(url, node, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "kssl-llmapi/1"})
    if node.get("api_key") and url.startswith("https"):
        req.add_header("Authorization", "Bearer " + node["api_key"])
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # 20000 bytes held ~58 ollama tag entries (~344 bytes each). A node with more
        # models returned TRUNCATED JSON, which no longer parses, so the probe fell back to
        # substring and could report a perfectly healthy node as DOWN. The list is small
        # even at 500 models; the cap is here to bound a hostile body, not to trim a real one.
        return r.read(_i("PROBE_MAX_BYTES", 1_000_000)).decode("utf-8", "replace")


def status():
    load_env()
    t, o = table(), origin()
    print("origin: %s   order: %s" % (o or "(unset)", ",".join(order()) or "(none live)"))
    for nid in KNOWN:
        n = t[nid]
        if not n["enabled"]:
            print("  %-6s DISABLED  %s" % (nid, n["url"] or "(no url)"))
            continue
        ok, why = probe(n)
        print("  %-6s %-9s %-38s %s" % (nid, "OK" if ok else "DOWN", n["url"], why))
    bad = check_config()
    print("\nconfig: %s" % ("ok" if not bad else "%d problem(s)" % len(bad)))
    for b in bad:
        print("  ! %s" % b)


def _demo():
    base = dict(os.environ)
    try:
        for k in list(os.environ):
            if k.split("_")[0] in ("VPSA", "VPSB", "DC", "FARM", "LLM", "NODE", "GLINER"):
                del os.environ[k]

        # a node with a flag but no URL is not dialable, and says so
        os.environ["VPSB_ENABLED"] = "1"
        os.environ["LLM_NODE_ORDER"] = "vps-b"
        assert table()["vps-b"]["enabled"] is False, "no URL must mean not enabled"
        assert any("no VPSB_URL" in b for b in check_config()), check_config()

        os.environ["VPSB_URL"] = "http://127.0.0.1:11434"
        assert table()["vps-b"]["enabled"] is True
        os.environ["LLM_ORIGIN"] = "vps-b"
        assert check_config() == [], check_config()

        # THE BUG THIS PINS: vps-a's loopback address, dialled from vps-b, silently hits
        # vps-b's own Ollama. It must be refused, not "worked".
        os.environ["VPSA_URL"] = "http://127.0.0.1:11434"
        os.environ["VPSA_ENABLED"] = "1"
        os.environ["LLM_NODE_ORDER"] = "vps-b,vps-a"
        probs = check_config()
        assert any("OWN Ollama" in p for p in probs), probs

        # a remote address for the same node is fine
        os.environ["VPSA_URL"] = "http://10.0.0.7:11434"
        assert check_config() == [], check_config()

        # an OpenAI node with no key is refused: it 530s and looks like an outage
        os.environ["FARM_URL"] = "https://farm.example/"
        os.environ["FARM_ENABLED"] = "1"
        os.environ["FARM_OPENAI"] = "1"
        os.environ["LLM_NODE_ORDER"] = "vps-b,farm"
        assert any("530" in p for p in check_config()), check_config()
        os.environ["FARM_API_KEY"] = "k"
        assert check_config() == [], check_config()
        # trailing slash must not become a double slash in the probe URL
        assert table()["farm"]["url"] == "https://farm.example"

        # a typo in the order is an error for VALIDATION, never a silently dropped node...
        os.environ["LLM_NODE_ORDER"] = "vps-b,vpsb"
        try:
            order()
            raise AssertionError("a typo'd node name must raise")
        except ValueError as e:
            assert "vpsb" in str(e), e
        # ...but a SERVING path must never raise on it: check_config() already reports the
        # typo by name, so a handler that also calls order() turns a 503-with-a-reason into
        # a bare 500. live_order() is what every request path uses.
        assert live_order() == [], live_order()
        assert any("vpsb" in p for p in check_config()), check_config()
        assert worst_case_s(300) == 0.0, "a broken order must not raise inside a budget call"
        os.environ["LLM_NODE_ORDER"] = "vps-b,farm"

        # disabled nodes drop out of the order but are not an error
        os.environ["FARM_ENABLED"] = "0"
        assert order() == ["vps-b"], order()

        # timeout is derived, floored and ceilinged
        os.environ["LLM_TIMEOUT_FLOOR"] = "180"
        os.environ["LLM_TIMEOUT_CEIL"] = "1800"
        assert read_timeout(10, 11.95) == 180.0, read_timeout(10, 11.95)
        slow = read_timeout(6000, 1.5)
        assert slow == 1800.0, slow
        mid = read_timeout(600, 11.95)
        assert 180.0 <= mid <= 1800.0, mid
        # a slower node must be given MORE time for identical work, not less
        assert read_timeout(4000, 1.5) > read_timeout(4000, 53.5)

        # options carry the node's own characteristics, not a global
        n = dict(table()["vps-b"], threads=4, cpu=True)
        o = options(n, 300)
        assert o["num_thread"] == 4 and o["num_gpu"] == 0 and o["num_predict"] == 300, o
        assert options(dict(n, threads=0, cpu=False), 5) == {
            "temperature": 0, "num_predict": 5, "num_ctx": 8192}

        # probe checks the MODEL, not just the port
        os.environ["NODE_MODEL"] = "qwen2.5:7b"
        far = dict(table()["farm"], url="https://x", openai=True, api_key="k")
        ok, _ = probe(far, fetch=lambda u, n, t: '{"data":[{"id":"qwen2.5:7b"}]}')
        assert ok
        ok, why = probe(far, fetch=lambda u, n, t: '{"data":[{"id":"llama3:8b"}]}')
        assert not ok and "absent" in why, why

        def boom(u, n, t):
            raise urllib.error.URLError("refused")
        ok, why = probe(far, fetch=boom)
        assert not ok and "URLError" in why, why
        # A '#' INSIDE A VALUE IS A CHARACTER. Splitting on a bare '#' truncates any secret
        # containing one, and a Bearer token cut short makes the farm 530 -- which reads
        # exactly like the farm being down, the failure this file lectures about twice.
        assert _value("abc#def") == "abc#def", _value("abc#def")
        assert _value("abc # a comment") == "abc"
        assert _value("abc\t# tabbed comment") == "abc"
        assert _value('"has # hash" # comment') == "has # hash"
        assert _value("'single # quoted'") == "single # quoted"
        assert _value("  spaced  ") == "spaced"
        assert _value("") == ""
        assert _value("# only a comment") == ""
        # a DSN keeps its '=' and a URL keeps its fragment
        assert _value("host=x port=5460 password=p#1") == "host=x port=5460 password=p#1"

        # load_env must not override what the operator already set
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / ".env").write_text("A_KEY=fromfile\nB_KEY=b#1\n# comment\n\nBAD LINE\n")
        os.environ["A_KEY"] = "fromenv"
        load_env(d / ".env")
        assert os.environ["A_KEY"] == "fromenv", "the environment must win over the file"
        assert os.environ["B_KEY"] == "b#1", os.environ["B_KEY"]
        assert load_env(d / "nope.env") == 0, "a missing file is not an error"
        del os.environ["A_KEY"], os.environ["B_KEY"]

        # loopback is resolved by `ipaddress`, not matched by eye. Every form below is the
        # same address, and hand-parsing missed most of them.
        for same in ("http://127.0.0.1:11434", "http://127.0.0.2:11434", "http://127.1:11434",
                     "http://localhost:11434", "http://LOCALHOST:11434", "http://0.0.0.0:11434",
                     "http://[::1]:11434", "http://[0:0:0:0:0:0:0:1]/",
                     "http://[::ffff:127.0.0.1]/", "127.0.0.1:11434"):
            assert _is_loopback(same), "missed a loopback form: %s" % same
        for remote in ("http://localhost.example.com:11434", "http://10.0.0.7/proxy/127.0.0.1",
                       "http://llm:11434", "https://ollama.i3softlab.com", "", "   ",
                       "http://10.0.0.7:11434"):
            assert not _is_loopback(remote), "wrongly flagged as loopback: %r" % remote

        # the probe matches the FULL TAG: a node holding only qwen2.5:0.5b must not pass as
        # "serving qwen2.5:7b" -- healthz would be green while every real call fails
        os.environ["NODE_MODEL"] = "qwen2.5:7b"
        n = dict(table()["vps-b"], url="http://x", openai=False)

        def tags(*names):
            return lambda u, nn, t: json.dumps({"models": [{"name": x} for x in names]})

        # The list is PARSED and names compared exactly. Substring matching passed all three
        # of these: a smaller sibling, a quantised variant, and -- because "m" is a substring
        # of the literal key "models" -- absolutely anything when the name was short.
        for held, why in ((["qwen2.5:0.5b"], "a smaller sibling"),
                          (["qwen2.5:7b-instruct-q4_0"], "a quantised variant is a different model"),
                          ([], "nothing at all")):
            ok_, detail = probe(n, fetch=tags(*held))
            assert not ok_, "%s must not satisfy qwen2.5:7b (%s)" % (why, detail)
        ok_, _ = probe(n, fetch=tags("llama3:8b", "qwen2.5:7b"))
        assert ok_, "the exact tag among others must match"
        # a bare name in .env means the :latest tag -- and must NOT match a sibling
        ok_, _ = probe(n, fetch=tags("m:latest"), model="m")
        assert ok_, "a bare model name must match its :latest tag"
        ok_, _ = probe(n, fetch=tags("m:7b"), model="m")
        assert not ok_, "a bare name must not match an arbitrary tag of the same family"
        # the OpenAI-shaped gateway reports {"data":[{"id":...}]}
        ok_, _ = probe(dict(n, openai=True),
                       fetch=lambda u, nn, t: '{"data":[{"id":"qwen2.5:7b"}]}')
        assert ok_, "the OpenAI-shaped model list must parse too"
        # an unparseable body degrades honestly rather than calling a live node dead
        ok_, detail = probe(n, fetch=lambda u, nn, t: "not json at all qwen2.5:7b")
        assert ok_ and "substring" in detail, detail
        # ...but AN EMPTY LIST IS AN ANSWER, not a parse failure. A fresh Ollama with
        # nothing pulled is the exact state this probe exists to catch, and it must say so
        # rather than claiming the list was unreadable.
        ok_, detail = probe(n, fetch=lambda u, nn, t: '{"models":[]}')
        assert not ok_ and "nothing" in detail and "unparseable" not in detail, detail
        # a bare list of names is a shape some servers use
        assert _model_names('{"models":["a:1","b:2"]}') == {"a:1", "b:2"}
        assert _model_names("[1,2]") is None, "a non-object body is not a model list"
        assert _model_names("nope") is None

        # THE PROBE MUST NOT TRUNCATE A REAL TAG LIST. At 20000 bytes a node holding ~58
        # models returned unparseable JSON and was reported DOWN while serving perfectly.
        # A real /api/tags entry is ~344 bytes: name, digest, size, modified_at, details.
        def entry(name):
            return {"name": name, "model": name, "modified_at": "2026-08-28T09:52:13.123456789Z",
                    "size": 4683087332, "digest": "a" * 64,
                    "details": {"parent_model": "", "format": "gguf", "family": "qwen2",
                                "families": ["qwen2"], "parameter_size": "7.6B",
                                "quantization_level": "Q4_K_M"}}

        big = json.dumps({"models": [entry("m%03d:7b" % i) for i in range(60)]
                                    + [entry("qwen2.5:7b")]})
        assert len(big) > 20000, "make the fixture big enough to prove the point: %d" % len(big)
        names = _model_names(big)
        assert names and "qwen2.5:7b" in names, "a 400-model list must still parse"

        # worst_case_s covers the whole chain, and grows with both nodes and attempts
        os.environ.update({"LLM_NODE_ORDER": "vps-b,farm", "LLM_RETRIES": "2",
                           "FARM_ENABLED": "1", "FARM_URL": "https://f.example",
                           "FARM_API_KEY": "k", "FARM_OPENAI": "1", "FARM_TOK_S": "53.5",
                           "VPSB_URL": "http://127.0.0.1:11434", "VPSB_ENABLED": "1"})
        two = worst_case_s(300)
        assert two > read_timeout(300, table()["vps-b"]["tok_s"]), two
        os.environ["LLM_RETRIES"] = "1"
        assert worst_case_s(300) < two, "fewer attempts must mean a shorter worst case"
        os.environ["LLM_NODE_ORDER"] = "vps-b"
        one_node = worst_case_s(300)
        os.environ["LLM_NODE_ORDER"] = "vps-b,farm"
        assert worst_case_s(300) > one_node, "a second node must extend the worst case"
        os.environ["LLM_RETRIES"] = "2"

        # LOCAL ORIGIN: the code runs off-fleet and every node is a local forward, so
        # loopback is expected everywhere and the check that matters inverts.
        for k in list(os.environ):
            if k.split("_")[0] in ("VPSA", "VPSB", "DC", "FARM", "LLM", "NODE", "GLINER"):
                del os.environ[k]
        os.environ.update({
            "LLM_ORIGIN": "local", "LLM_NODE_ORDER": "vps-b,vps-a,dc",
            "VPSB_URL": "http://127.0.0.1:11501", "VPSB_ENABLED": "1",
            "VPSA_URL": "http://127.0.0.1:11502", "VPSA_ENABLED": "1",
            "DC_URL": "http://127.0.0.1:11503", "DC_ENABLED": "1",
        })
        assert check_config() == [], check_config()
        assert order() == ["vps-b", "vps-a", "dc"], order()

        # ...and TWO NODES ON ONE FORWARD is the error it swaps in: both report healthy
        # while one box's work silently goes to another.
        os.environ["VPSA_URL"] = "http://127.0.0.1:11501"
        probs = check_config()
        assert any("both point at" in p for p in probs), probs
        os.environ["VPSA_URL"] = "http://127.0.0.1:11502"
        assert check_config() == [], check_config()

        # a GLiNER endpoint colliding with another node's is caught the same way
        os.environ["VPSB_GLINER_URL"] = "http://127.0.0.1:11511/extract"
        os.environ["VPSA_GLINER_URL"] = "http://127.0.0.1:11511/extract"
        assert any("both point at" in p for p in check_config()), check_config()
        os.environ["VPSA_GLINER_URL"] = "http://127.0.0.1:11512/extract"
        assert check_config() == [], check_config()

        # an unknown origin is still an error -- `local` is declared, not a free-for-all
        os.environ["LLM_ORIGIN"] = "my-laptop"
        assert any("LLM_ORIGIN" in p for p in check_config()), check_config()
        os.environ["LLM_ORIGIN"] = "local"

        # GLiNER routes over its own order and its own budget
        os.environ["DC_GLINER_URL"] = "http://127.0.0.1:11513/extract"
        os.environ["GLINER_NODE_ORDER"] = "vps-b,vps-a,dc"
        assert gliner_order() == ["vps-b", "vps-a", "dc"], gliner_order()
        os.environ["VPSA_GLINER_URL"] = ""
        assert gliner_order() == ["vps-b", "dc"], "no URL means no GLiNER on that node"
        os.environ["VPSA_GLINER_URL"] = "http://127.0.0.1:11512/extract"
        # GLINER_NODE_ORDER falls back to LLM_NODE_ORDER when unset
        del os.environ["GLINER_NODE_ORDER"]
        assert gliner_order() == ["vps-b", "vps-a", "dc"], gliner_order()
        # cost scales with TEXT, not tokens -- a huge batch stops fitting a small budget
        assert gliner_fits("vps-b", 10_000)
        assert not gliner_fits("vps-b", 10_000_000_000), "a vast batch must not fit"

        # a garbled numeric setting falls back instead of raising inside a request handler
        os.environ["LLM_RETRIES"] = "abc"
        assert _i("LLM_RETRIES", 2) == 2
        os.environ["LLM_TIMEOUT_FLOOR"] = "not-a-number"
        assert _f("LLM_TIMEOUT_FLOOR", 180) == 180.0
        os.environ["LLM_RETRIES"] = "2"
        del os.environ["LLM_TIMEOUT_FLOOR"]

        print("ok  '#' survives inside a secret, loopback is parsed not matched, the probe "
              "checks the full tag, and the budget covers the whole failover chain")
    finally:
        os.environ.clear()
        os.environ.update(base)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    elif "--status" in sys.argv:
        status()
    else:
        load_env()
        print(json.dumps({"origin": origin(), "order": order(),
                          "nodes": table(), "problems": check_config()}, indent=2))
