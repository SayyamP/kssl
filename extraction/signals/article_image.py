"""Pick the lead image out of an article's stored HTML.

The signal pipeline reads `documents.main_text` and never looked at the markup,
so every card it wrote had `image = NULL` and the dashboard filled the hole with
Unsplash stock photos. The picture the publisher chose for the article is already
in `documents.html` at the data centre -- this reads it out.

    from article_image import pick_image
    url = pick_image(html, "https://www.janes.com/a/story")

Pure and offline: no network, no HTML parser dependency, stdlib only. That is
deliberate -- it makes the thing unit-testable against saved pages, and the
extraction image does not have to grow a dependency for four regexes over
`<meta>` tags, which are the flattest markup on the page.

WHAT IT WILL NOT RETURN
-----------------------
A wrong image is worse than no image: an honest empty state reads as "no picture
was published", a site logo on every card reads as though the dashboard is
making things up. So `pick_image` returns None rather than guessing, and the
caller leaves the column NULL. Rejected outright: site furniture (logo, sprite,
icon, avatar, placeholder), tracking pixels, data: URIs, and SVG -- publishers
use SVG for chrome, not for photographs.
"""
import html as html_mod
import re
from urllib.parse import urljoin, urlparse

__all__ = ["pick_image", "image_candidates"]

# A <meta> tag's two halves can appear in either order, and the key sits on
# `property` (OpenGraph) or `name` (Twitter, and the many sites that get OG
# wrong). One pattern per direction rather than one clever pattern for both.
#
# The key match must be EXACT. An optional-quote pattern like `["']?og:image["']?`
# also matches the prefix of `og:image:type`, and then happily reads that tag's
# content -- which is the string "image/jpeg". That resolved against the article
# URL and wrote `thedefensepost.com/2026/06/25/image/jpeg` into a card. So the
# value is either quoted and closed, or unquoted and followed by whitespace or
# the end of the tag; `og:image:width` and `og:image:alt` are the same trap.
_KEY = r"""(?:"%(k)s"|'%(k)s'|%(k)s(?=[\s/>]))"""
_META_KEY_FIRST = (
    r"""<meta[^>]*?\b(?:property|name)\s*=\s*""" + _KEY + r"""[^>]*?"""
    r"""\bcontent\s*=\s*["']([^"']+)["']"""
)
_META_CONTENT_FIRST = (
    r"""<meta[^>]*?\bcontent\s*=\s*["']([^"']+)["'][^>]*?"""
    r"""\b(?:property|name)\s*=\s*""" + _KEY
)

# Ordered best-first. og:image is what the publisher hands to Facebook and is
# almost always the article's own lead photograph; twitter:image is the same
# promise to a different reader; image_src is the pre-OG version of it.
_META_KEYS = (
    "og:image:secure_url",
    "og:image:url",
    "og:image",
    "twitter:image:src",
    "twitter:image",
)

_LINK_IMAGE_SRC = re.compile(
    r"""<link[^>]*?\brel\s*=\s*["']?image_src["']?[^>]*?\bhref\s*=\s*["']([^"']+)["']""",
    re.I,
)

# JSON-LD carries "image" as a string, an array, or an ImageObject with a url.
# Matching the value shapes directly beats parsing the whole block: news pages
# routinely ship several JSON-LD islands, some of them invalid JSON.
_LD_IMAGE = re.compile(
    r'"image"\s*:\s*(?:'
    r'"(?P<s>https?://[^"]+)"'
    r'|\[\s*"(?P<a>https?://[^"]+)"'
    r'|\{[^{}]*?"url"\s*:\s*"(?P<o>https?://[^"]+)"'
    r'|\[\s*\{[^{}]*?"url"\s*:\s*"(?P<ao>https?://[^"]+)"'
    r")",
    re.I | re.S,
)

# Site furniture, not article photography.
_JUNK_WORDS = frozenset("""
    logo logos sprite sprites icon icons favicon avatar avatars
    placeholder placeholders default blank spacer dummy noimage
    pixel pixels tracking beacon transparent share social
""".split())

# A directory called /logos/ or /icons/ holds site furniture whatever the file
# inside it is named.
_JUNK_DIRS = frozenset(
    "logo logos icon icons sprite sprites favicon avatar avatars "
    "placeholder placeholders social share".split()
)

# A token that carries no meaning of its own: a resize suffix or a bare number.
# Stripped before judging a stem, so `logo_2x.png` is still read as "logo".
_SIZE_TOKEN = re.compile(r"^\d{1,4}x\d{1,4}$|^\d+x$|^\d+$", re.I)

# The whole filename is nothing but a size -- a spacer or an ad slot.
_BARE_SIZE = re.compile(r"^\d{1,4}x\d{1,4}$", re.I)

# Publishers use SVG for chrome and .gif for spacers far more than for news
# photographs. .webp/.avif are modern photo formats and stay.
_BAD_EXT = re.compile(r"\.(?:svg|ico|bmp|tif|tiff)(?:[?#]|$)", re.I)

# ponytail: token heuristic, not a classifier. A real lead image is named for
# its story ("logos-of-war-lead.jpg", 4 tokens); furniture is named for what it
# is ("logo", "site-logo", "default-image"), which is short. Three tokens is the
# line. If a publisher ever ships a 2-token story slug that collides with a junk
# word we lose one image and show an honest empty state -- the failure is in the
# safe direction. Upgrade path if that gets noisy: HEAD the URL and judge by
# Content-Length and pixel dimensions instead of the name.
_MAX_JUNK_TOKENS = 3


def _is_junk_path(path):
    segs = [s for s in path.split("/") if s]
    if not segs:
        return False
    if any(s.lower() in _JUNK_DIRS for s in segs[:-1]):
        return True
    stem = segs[-1].rsplit(".", 1)[0].lower()
    tokens = [t for t in re.split(r"[-_.]+", stem) if t]
    if not tokens:
        return False
    # A spacer is named ONLY for its size: 1x1.gif, 300x250.png. Rejecting any
    # stem whose tokens all look numeric is far too broad -- a camera filename
    # with a CDN resize suffix (20240110_125758-360x245.jpg) is entirely digits
    # and is the article's own photograph. That rule cost two real images.
    if _BARE_SIZE.match(stem):
        return True
    meaningful = [t for t in tokens if not _SIZE_TOKEN.match(t)]
    if len(meaningful) <= _MAX_JUNK_TOKENS and any(t in _JUNK_WORDS for t in meaningful):
        return True
    return False

_MAX_LEN = 2000


def _clean(raw, base_url):
    """Turn one raw attribute value into an absolute http(s) URL, or None."""
    if not raw:
        return None
    # Stored markup is entity-escaped, so a query string arrives as
    # `?format=jpg&amp;name=small`. Left alone that 302s or 404s at the CDN --
    # the existing rows in serving.signal_card carry exactly this bug.
    u = html_mod.unescape(raw.strip())
    if not u or u.startswith("data:"):
        return None
    # Protocol-relative (`//cdn.example/x.jpg`) is common and perfectly valid;
    # urljoin resolves it against the article's scheme.
    if base_url:
        u = urljoin(base_url, u)
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    if len(u) > _MAX_LEN:
        return None
    if _BAD_EXT.search(p.path):
        return None
    if _is_junk_path(p.path):
        return None
    return u


def image_candidates(html, base_url=""):
    """Every plausible lead image, best first, deduplicated.

    Exposed separately from `pick_image` so a diagnostic run can show what was
    on offer and why the winner won -- when this picks a wrong image, the answer
    is nearly always visible in the runner-up.
    """
    if not html:
        return []
    # The lead image is declared in <head>. Capping the scan there keeps a 2 MB
    # page cheap and, more importantly, keeps body content (ad creatives,
    # related-story thumbnails, author headshots) out of the candidate list.
    head = html[:200000]

    out = []
    seen = set()

    def add(raw):
        u = _clean(raw, base_url)
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    for key in _META_KEYS:
        esc = re.escape(key)
        for pat in (_META_KEY_FIRST, _META_CONTENT_FIRST):
            for m in re.finditer(pat % {"k": esc}, head, re.I | re.S):
                add(m.group(1))

    for m in _LINK_IMAGE_SRC.finditer(head):
        add(m.group(1))

    for m in _LD_IMAGE.finditer(head):
        add(m.group("s") or m.group("a") or m.group("o") or m.group("ao"))

    return out


def pick_image(html, base_url=""):
    """The article's lead image as an absolute URL, or None if it published none.

    Pure: what the page CLAIMS, with no network. `resolve_image` is the one that
    checks the claim is true.
    """
    c = image_candidates(html, base_url)
    return c[0] if c else None


# --------------------------------------------------------------------------
# Checking the claim. Everything below touches the network.
#
# A publisher's og:image is a claim, not a fact. thedefensepost.com declares
# every one of its images on `i.thedefensepost.com`, which answers 526 -- the
# origin behind Cloudflare has an invalid certificate. The same path on the
# apex host serves the picture. Trusting og:image blindly put eight broken
# frames on the dashboard; so the URL is probed before it is stored.
# --------------------------------------------------------------------------

# A refusal is not a 404. These mean "this CDN will not serve a datacentre IP
# without a browser's headers" -- hotlink protection, mod_security, rate limits.
# The URL is almost certainly right and a real viewer will load it, so treating
# them as broken would throw away good images (measured: 9 of 160).
_BLOCKED_NOT_BROKEN = frozenset((401, 403, 405, 406, 409, 429, 451))

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _head_ok(url, timeout, referer=""):
    """(usable, hard_failure). `usable` means store it; `hard_failure` means the
    URL is genuinely not an image, so a fallback is worth trying."""
    import urllib.error
    import urllib.request

    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", _UA)
        if referer:
            req.add_header("Referer", referer)
        if method == "GET":
            req.add_header("Range", "bytes=0-2047")   # never pull a whole photo
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype.startswith("image/"):
                    return True, False
                # 200 with text/html is a consent wall or an error page dressed
                # as success -- the frame would render blank.
                return False, True
        except urllib.error.HTTPError as e:
            if e.code in _BLOCKED_NOT_BROKEN:
                return True, False
            if method == "HEAD":
                continue                              # some CDNs only answer GET
            return False, True
        except Exception:                             # noqa: BLE001  DNS, TLS, timeout
            if method == "HEAD":
                continue
            return False, True
    return False, True


def _parent_host_variant(url):
    """Same path one label up: i.example.com/x.jpg -> example.com/x.jpg.

    A dedicated image subdomain that has broken away from its origin is a real
    and recurring shape, and the asset is nearly always still on the apex. Only
    ever tried AFTER the declared host has hard-failed, so a working URL is
    never second-guessed.
    """
    p = urlparse(url)
    labels = p.netloc.split(".")
    if len(labels) < 3:
        return None
    parent = ".".join(labels[1:])
    if parent.count(".") < 1:
        return None
    return p._replace(netloc=parent).geturl()


def resolve_image(html, base_url="", timeout=15, verify=True):
    """The article's lead image, proven to serve an image, or None.

    Walks the candidates best-first; on a hard failure tries the parent-host
    variant before moving on. Returns None rather than a URL that would render
    as a broken frame -- an honest empty state is the better failure.
    """
    cands = image_candidates(html, base_url)
    if not verify:
        return cands[0] if cands else None
    for c in cands:
        usable, hard = _head_ok(c, timeout, referer=base_url)
        if usable:
            return c
        if hard:
            alt = _parent_host_variant(c)
            if alt:
                usable, _ = _head_ok(alt, timeout, referer=base_url)
                if usable:
                    return alt
    return None
