"""THE ONE UNHASHED FILE MUST NOT BE CACHED.

vite gives every bundle a content hash, so /assets/index-<hash>.js is a new URL on
every build and can safely be cached forever. index.html is the only file that is NOT
renamed -- and it is the file that NAMES the bundles. Cache it and a viewer keeps
asking for the previous build's asset names, so a deploy that succeeded in every other
respect still serves the old app.

That failure is silent and reads exactly like a broken deploy. On staging 2026-09-08 the
severity badge shipped, the served bundle contained `sevtag`, the served CSS contained
`.sevtag.high`, /api/dataset returned a severity on 477 of 939 cards -- and the page
showed none of them. The deploy was green and correct; the browser was holding
index.html from before it.

The Caddyfile lives inside frontend/Dockerfile as a printf, so it has no config file
anyone would think to review and no syntax check of its own. This asserts the two rules
survive edits to that line.
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
DOCKERFILE = HERE.parent / "frontend" / "Dockerfile"

fails = []


def ck(name, ok, detail=""):
    print("  %-62s %s%s" % (name, "ok" if ok else "FAIL", "" if ok else "  " + detail))
    if not ok:
        fails.append(name)


def caddyfile():
    """The Caddyfile as it will exist in the image, with printf's escapes resolved."""
    src = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(r"RUN printf '(.*?)' > /etc/caddy/Caddyfile", src, re.S)
    if not m:
        ck("frontend/Dockerfile still writes a Caddyfile with printf", False,
           "the printf line is gone or reshaped; this test cannot see the config")
        return None
    # printf resolves \n, \t and \" -- the shell has already removed nothing else,
    # because the format string is single-quoted.
    return (m.group(1).replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"'))


conf = caddyfile()
if conf is None:
    sys.exit(1)

print("frontend cache policy:")
ck("the hashed assets are matched separately from everything else",
   "@assets" in conf and "path /assets/*" in conf)
ck("...and everything that is NOT a hashed asset is matched too",
   "@rest" in conf and "not path /assets/*" in conf)

asset_rule = re.search(r"header @assets Cache-Control \"([^\"]+)\"", conf)
rest_rule = re.search(r"header @rest Cache-Control \"([^\"]+)\"", conf)

ck("hashed assets are cacheable", bool(asset_rule) and "max-age=" in asset_rule.group(1),
   conf)
ck("...and immutable, so a viewer never revalidates a URL that cannot change",
   bool(asset_rule) and "immutable" in asset_rule.group(1))
ck("index.html and every SPA route are NOT cached",
   bool(rest_rule) and "no-cache" in rest_rule.group(1),
   "this is the bug: index.html names the bundles, so caching it pins the old build")
ck("...and no rule quietly makes index.html cacheable anyway",
   not (rest_rule and "max-age=" in rest_rule.group(1)
        and "max-age=0" not in rest_rule.group(1)))

# THE TWO RULES MUST NOT BOTH FIRE. `@rest` is defined as the negation of `@assets`,
# so a hashed asset can only ever match one of them -- written as a default plus an
# override, the order of Caddy's directives would decide, and it would decide silently.
ck("the two matchers are mutually exclusive, not a default plus an override",
   conf.count("not path /assets/*") == 1 and conf.count("header ") == 2, conf)

# The SPA fallback must still be there; a cache header is no use on a 404.
ck("the SPA fallback and the subdirectory probe are untouched",
   "try_files {path} {path}/index.html /index.html" in conf)

print()
if fails:
    print("%d FAILED" % len(fails))
    sys.exit(1)
print("ok - the hashed bundles are cached forever, the file that names them never is")
