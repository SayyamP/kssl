"""One URL in, one page out — escalating only as far as the page actually forces.

    C1  httpx            plain HTTP. Handles most maker sites and every PDF.
    C3  CamoFox          a real stealth browser. For JS-rendered pages and soft blocks.
    C4  host solver      CamoFox driven on the HOST, with the GPU. The only tier that
                         clears Cloudflare's interactive challenge and Incapsula.

WHY A LADDER AND NOT JUST A BROWSER
-----------------------------------
A browser costs roughly 1.2 cores per concurrent render on a GPU-less box, which caps a
fleet at about 2.5 pages/s no matter how many workers are started. httpx costs almost
nothing. So the ladder is a throughput decision, not a fastidiousness one: rendering every
page would make this run 20x slower for no extra data on the ~90% of pages that are plain
HTML.

Escalation is driven by EVIDENCE THE PAGE GAVE US, never by a per-host guess:
  * a transport failure, a 403/429/503, or a challenge fingerprint in the body -> C3
  * a Cloudflare interactive or Incapsula fingerprint, or C3 came back with a block
    page -> C4
A short body is NOT on its own a reason to escalate: plenty of real pages are short, and
"looks thin, try the browser" is how a run spends its whole budget on rendering.

ONE MEASURED CAVEAT (from this codebase's own history)
------------------------------------------------------
A 969-character response from a WAF-fronted host was once recorded as a permanent verdict
when it was a TRANSIENT block; the same URL returned 353k characters through C4 later. So
a block is recorded as `blocked`, which is retryable, and never as `gone`.
"""
import io
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the crawler's CamoFox client is already written, already handles the /tabs userId +
# sessionKey requirement and the /evaluate Bearer key, and already tears tabs down.
sys.path.insert(0, str(HERE.parent.parent.parent / "cralwer"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
C3_URL = os.environ.get("CAMOFOX_URL", "http://127.0.0.1:9377")
C4_URL = os.environ.get("HOST_SOLVER_URL", "http://127.0.0.1:9378")

# Fingerprints in the BODY. A 200 with one of these is a block wearing a success code,
# which is the single most common way a crawler records an empty page as a real one.
CHALLENGE = re.compile(
    r"just a moment|checking your browser|cf-browser-verification|cf_chl_opt"
    r"|_Incapsula_Resource|incident id|access denied|attention required"
    r"|enable javascript and cookies|ddos protection by|verifying you are human"
    r"|request unsuccessful|radware|bot detection", re.I)
INTERACTIVE = re.compile(
    r"cf_chl_opt|turnstile|_Incapsula_Resource|challenge-platform|hcaptcha|recaptcha", re.I)

RETRY_STATUS = {403, 405, 406, 409, 423, 429, 500, 502, 503, 504, 520, 521, 522, 525}


class Page(dict):
    """{url, final_url, status, via, text, html, bytes, ok, reason}"""

    @property
    def ok(self):
        return bool(self.get("ok"))


# Structural markers: markup a challenge page emits and a real page does not.
STRUCTURAL = re.compile(
    r"cf_chl_opt|cf-browser-verification|_Incapsula_Resource|challenge-platform"
    r"|<title>\s*(just a moment|attention required|access denied)"
    r"|ddos protection by|radware", re.I)


def _blocked(status, body):
    """A block, or a page that merely talks about blocking?

    On a NON-2xx the status is the evidence. On a 2xx it must be structural, or a phrase
    match alone condemns real pages: a defence maker's cybersecurity article containing
    "bot detection" or "Access Denied" was marked blocked at C1, matched the interactive
    fingerprint via the Cloudflare script tag every CF-proxied page carries, skipped C3,
    burned a serialised C4 solve, and failed there on the same article text - a legitimate
    page that no tier could ever record, re-attempted forever because `blocked` retries.

    So: a 2xx is a block when it carries challenge MARKUP, or when it says the words AND
    is short enough to be a challenge page rather than an article about one.
    """
    if status in RETRY_STATUS:
        return True
    if not body:
        return False
    head = body[:6000]
    if STRUCTURAL.search(head):
        return True
    return bool(len(body) < 5000 and CHALLENGE.search(head))


def c1(url, timeout=40):
    """Plain HTTP. Returns a Page; `ok` False does not mean the URL is dead."""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(40 * 1024 * 1024)
            ctype = r.headers.get("Content-Type", "")
            final = r.geturl()
            status = r.status
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(200000)
        except Exception:
            raw = b""
        # The body MATTERS here. A Cloudflare interactive challenge is a 403 whose body
        # carries cf_chl_opt/turnstile; dropping it left `interactive` permanently False,
        # so every URL of every such site paid a guaranteed-loss C3 render first.
        body = _decode(raw)
        return Page(url=url, final_url=url, status=e.code, via="c1",
                    text=body, html=body, bytes=b"", ok=False,
                    reason="blocked" if _blocked(e.code, body) else "http %s" % e.code)
    except Exception as e:
        return Page(url=url, final_url=url, status=0, via="c1", text="", html="",
                    bytes=b"", ok=False, reason="transport: %s" % type(e).__name__)

    if "pdf" in ctype.lower() or raw[:4] == b"%PDF":
        return Page(url=url, final_url=final, status=status, via="c1", text="",
                    html="", bytes=raw, ok=True, reason="pdf")
    body = _decode(raw)
    if _blocked(status, body):
        return Page(url=url, final_url=final, status=status, via="c1", text=body,
                    html=body, bytes=b"", ok=False, reason="blocked")
    return Page(url=url, final_url=final, status=status, via="c1",
                text=_text_of(body), html=body, bytes=b"", ok=True, reason="")


def _decode(raw):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


TAG = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def _text_of(html):
    s = TAG.sub(" ", html or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
          .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def c3(url, timeout=60):
    """CamoFox. A real browser, but on this box without a GPU it cannot clear an
    interactive Cloudflare challenge — that is what C4 exists for."""
    try:
        os.environ.setdefault("CAMOFOX_URL", C3_URL)
        from crawler import camofox_client
        snap = camofox_client.render(url, timeout_s=timeout, base_url=C3_URL)
    except Exception as e:
        return Page(url=url, final_url=url, status=0, via="c3", text="", html="",
                    bytes=b"", ok=False, reason="c3 error: %s" % type(e).__name__)
    if not snap:
        return Page(url=url, final_url=url, status=0, via="c3", text="", html="",
                    bytes=b"", ok=False, reason="c3 empty")
    html = snap.get("html") or ""
    text = snap.get("text") or _text_of(html)
    if _blocked(snap.get("status") or 200, html or text):
        return Page(url=url, final_url=snap.get("final_url") or url, status=0, via="c3",
                    text=text, html=html, bytes=b"", ok=False, reason="blocked")
    return Page(url=url, final_url=snap.get("final_url") or url,
                status=snap.get("status") or 200, via="c3", text=text, html=html,
                bytes=b"", ok=bool(text), reason="" if text else "c3 no text")


def c4(url, timeout=120):
    """The host solver: CamoFox on the host, with the real GPU behind it.

    llvmpipe is what fails a Cloudflare interactive challenge, so this tier exists
    precisely because the containerised browser cannot pass one.

    THE CONTRACT IS THE SERVER'S, NOT A GUESS. cralwer/scripts/host_solver.py serves
    `POST /solve` with `{"url": ...}` and answers HTTP 200 ALWAYS, carrying
    `{ok, html, title, chars, elapsed, via, solved, error}`. It has no `text`, no
    `status` and no `url` key. This function previously posted to `/fetch` and read
    `text`/`status`/`url`, so every call 404'd and every Cloudflare-fronted site in the
    run was recorded as failed - a tier with a 0% success rate that looked like a set of
    hostile websites.

    The server also serialises on one browser lock and cold-starts (~28s) whenever the
    host changes, so a client-side timeout here is a QUEUE symptom, not a verdict about
    the URL - it is reported retryable.
    """
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            C4_URL.rstrip("/") + "/solve",
            data=json.dumps({"url": url}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout + 60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # a timeout means the solver queue is long, not that the page is gone
        kind = "blocked" if "timeout" in type(e).__name__.lower() else "c4 error: %s" % type(e).__name__
        return Page(url=url, final_url=url, status=0, via="c4", text="", html="",
                    bytes=b"", ok=False, reason=kind)
    html = d.get("html") or ""
    text = _text_of(html)
    # the server's own verdict leads; ours is only a second opinion
    if not d.get("ok"):
        return Page(url=url, final_url=url, status=0, via="c4", text=text, html=html,
                    bytes=b"", ok=False,
                    reason=(d.get("error") or "blocked")[:120])
    if _blocked(200, html):
        return Page(url=url, final_url=url, status=0, via="c4", text=text, html=html,
                    bytes=b"", ok=False, reason="blocked")
    return Page(url=url, final_url=url, status=200, via="c4", text=text, html=html,
                bytes=b"", ok=bool(text), reason="" if text else "c4 no text")


_C3_FAILS = {"n": 0}
C3_BREAK_AT = 5


def get(url, allow_browser=True, allow_solver=True):
    """The ladder. Returns the first Page that came back with content.

    Each escalation needs a REASON from the rung below it, and `reason` on the returned
    Page always names the last thing that went wrong, so a caller can tell "this host
    blocks us" from "this URL does not exist".
    """
    p = c1(url)
    if p.ok or not allow_browser:
        return p
    # 404/410 is an answer, not a block. Escalating on it burns a browser render to be
    # told the same thing more slowly.
    if p.get("status") in (400, 401, 404, 410, 451):
        return p
    def _interactive(pg):
        blob = (pg.get("html") or pg.get("text") or "")[:8000]
        return bool(INTERACTIVE.search(blob))

    interactive = _interactive(p)
    c3_down = _C3_FAILS["n"] >= C3_BREAK_AT
    if not interactive and not c3_down:
        b = c3(url)
        if b.ok:
            _C3_FAILS["n"] = 0
            return b
        # Distinguish "C3 says this page is blocked" from "C3 itself is broken". CamoFox
        # wedges and does not recover; without this counter a dead container escalated
        # EVERY url to the host solver, which holds one global browser lock and cold
        # starts on each host change - turning the whole fleet into a serial queue.
        if str(b.get("reason", "")).startswith("c3 error"):
            _C3_FAILS["n"] += 1
        else:
            _C3_FAILS["n"] = 0
        p = b
        interactive = _interactive(b)

    # C4 is serialised box-wide and cold-starts per host, so it is spent only on evidence
    # that a browser challenge is actually in the way.
    if allow_solver and (interactive or p.get("reason") == "blocked"):
        s = c4(url)
        if s.ok:
            return s
        # keep whichever attempt actually carried text, so a partial read is not lost
        if len(s.get("text") or "") > len(p.get("text") or ""):
            p = s
    return p


def demo():
    assert _blocked(200, "Just a moment... checking your browser"), "200 + challenge is a block"
    assert _blocked(403, "anything")
    assert not _blocked(200, "<html><body>Our products include the ATAGS gun.</body></html>")
    # a short but real page must NOT read as blocked - shortness is not evidence
    assert not _blocked(200, "<html><body>Contact us.</body></html>")
    assert "ATAGS" in _text_of("<html><script>var x=1</script><p>ATAGS gun</p></html>")
    assert "var x" not in _text_of("<html><script>var x=1</script><p>ATAGS</p></html>")
    # a long real article that merely MENTIONS blocking is not a block
    article = "<html><body>" + ("Our platform provides bot detection. " * 300) + "</body></html>"
    assert not _blocked(200, article), "an article about bot detection is not a challenge"
    assert _blocked(200, "<html><head><title>Just a moment...</title></head></html>")
    assert _blocked(200, "<script src='/cdn-cgi/challenge-platform/x'></script>")
    assert INTERACTIVE.search("<div id=cf_chl_opt>")
    assert not INTERACTIVE.search("<p>ordinary page</p>")
    print("fetch demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        for u in sys.argv[1:]:
            p = get(u)
            print("%-4s %-6s %6d chars  %s  %s" % (
                p["via"], p["status"], len(p.get("text") or ""), p["reason"], u[:70]))
