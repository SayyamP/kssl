"""Throw out the pages that are not what they claim to be.

    python clean.py --report
    python clean.py --apply
    python clean.py --demo

A quality pass over the harvest found that 33 stored pages were SOFT-404s — HTTP 200
responses that are error pages — and that 21% of all pages were exact duplicates of
another page for the same company. Both are worse than a missing page, because a missing
page is visibly missing and these are not:

  ADANI   30 pages. Sitecore answers every unknown path with 200 and an identical
          1693-char body beginning "page-not-found Home About Us…". Seven of the nine
          needs recorded for that company were entirely fabricated.
  JINDAL   3 pages. HTTP 200, body is the fourteen characters "Page Not Found".
  JCBL     3 pages. Guessed paths redirect to "/" and the HOMEPAGE is stored as the
          leadership page. 13.5 KB of plausible text and no error marker anywhere — the
          most dangerous shape, and invisible to any length rule.

WHY THERE IS NO LENGTH THRESHOLD HERE
-------------------------------------
The obvious fix is "reject pages under N characters". It was measured and it does not
work. Catching ADANI's 1693-char error page needs a cut at 1700, which destroys 18
genuine pages and still misses JCBL entirely. The noise floor is per-site and spans three
orders of magnitude: one maker's median page is 38,604 characters because its navigation
chrome alone is 35 KB, while another maker's LARGEST page is 4,830.

The counterexample that settles it: sssdefence.com/products/assault-rifles is 924
characters — the shortest non-404 page in the whole corpus — and is the densest product
content in it, five rifles with their calibres. Any threshold that catches ADANI deletes
that page.

So the rejections here are EXACT signals, each of which caught real contamination with no
false positives, plus a 500-character floor that only catches the degenerate case.
"""
import argparse
import hashlib
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from targets import DSN                             # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A URL the server itself rewrote to an error route. The strongest signal there is: the
# site told us, in the final URL, that the page does not exist.
ERR_URL = re.compile(r"page-not-found|aspxerrorpath|/404(?:[/?.]|$)|/error(?:[/?.]|$)", re.I)
# The body saying so, in a 200.
ERR_TEXT = re.compile(r"\bpage[ -]not[ -]found\b|\berror 404\b|\b404 error\b"
                      r"|we (?:can'?t|could not|couldn'?t) find", re.I)
FLOOR = 500     # degenerate only: "Page Not Found" is 14 characters


def md5(s):
    return hashlib.md5((s or "").encode("utf-8", "replace")).hexdigest()


def normalise(url):
    """The same page must have the same URL, or it is fetched and stored many times.

    Four mechanical duplicate causes were measured, together accounting for most of the
    39 duplicate groups: a #fragment treated as a distinct page (one investor page was
    stored SIX times under three different needs), a trailing slash, an `index.php/`
    prefix, and a locale prefix (`/en-gb/...`).
    """
    try:
        u = urllib.parse.urlsplit(url)
    except Exception:
        return url
    path = re.sub(r"/index\.(php|html?|aspx)(?=/|$)", "", u.path, flags=re.I)
    path = re.sub(r"^/(?:en|en-gb|en-us|en-in)(?=/)", "", path, flags=re.I)
    if len(path) > 1:
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), path or "/",
                                    u.query, ""))          # fragment dropped


def verdict(page, home_md5):
    """Why this page should not be kept, or "" to keep it."""
    text = page.get("text") or ""
    if ERR_URL.search(page.get("final_url") or "") or ERR_URL.search(page.get("url") or ""):
        return "soft-404: the site redirected to its error route"
    if ERR_TEXT.search(text[:1500]):
        return "soft-404: the body says the page was not found"
    if len(text.strip()) < FLOOR:
        return "empty: %d chars" % len(text.strip())
    if home_md5 and md5(text) == home_md5 and page.get("need") not in ("home", "about"):
        return "homepage clone: identical to this company's own home page"
    return ""


def run(apply_it=False):
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            cur.execute("""select page_id, cid, need, url, final_url, text
                           from harvest.page order by cid, page_id""")
            rows = cur.fetchall()

        homes, by_cid = {}, {}
        for pid, cid, need, url, final, text in rows:
            by_cid.setdefault(cid, []).append((pid, need, url, final, text))
            if need == "home" and cid not in homes:
                homes[cid] = md5(text)

        drop, dupes, seen = [], [], {}
        for cid, items in by_cid.items():
            for pid, need, url, final, text in items:
                why = verdict({"need": need, "url": url, "final_url": final, "text": text},
                              homes.get(cid))
                if why:
                    drop.append((pid, cid, need, url, why))
                    continue
                key = (cid, md5(text))
                if key in seen:
                    dupes.append((pid, cid, need, url,
                                  "duplicate of page %d" % seen[key]))
                else:
                    seen[key] = pid

        print("pages: %d" % len(rows))
        print("  reject   %4d  not what they claim to be" % len(drop))
        print("  dupes    %4d  byte-identical to another page for the same company"
              % len(dupes))
        print("  keep     %4d" % (len(rows) - len(drop) - len(dupes)))

        by_reason = {}
        for _, cid, _, _, why in drop:
            by_reason.setdefault(why.split(":")[0], []).append(cid)
        print()
        for why, cids in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            u = sorted(set(cids))
            print("  %4d  %-22s %s" % (len(cids), why, ", ".join(u[:6])))
        print()
        for pid, cid, need, url, why in drop[:12]:
            print("   %-16s %-11s %s" % (cid[:16], need, url[:62]))
            print("        %s" % why)

        if not apply_it:
            print("\nREPORT ONLY — nothing deleted. Re-run with --apply")
            return
        ids = [d[0] for d in drop] + [d[0] for d in dupes]
        with cx.cursor() as cur:
            cur.execute("delete from harvest.page where page_id = any(%s)", (ids,))
            # the TASK is reset, not deleted: a soft-404 means the guessed path was wrong,
            # and marking it done would hide that this need is still unmet
            cur.execute("""update harvest.task t set state='failed', reason='soft-404'
                           where t.task_id in (select task_id from harvest.page
                                               where page_id = any(%s))""", (ids,))
        cx.commit()
        print("\nDELETED %d pages (%d rejected, %d duplicate)"
              % (len(ids), len(drop), len(dupes)))


def demo():
    assert normalise("https://x.com/investors/#board") == "https://x.com/investors"
    assert normalise("https://x.com/about/") == normalise("https://X.com/about")
    assert normalise("https://x.com/index.php/products") == "https://x.com/products"
    assert normalise("https://x.com/en-gb/optronics") == "https://x.com/optronics"
    assert normalise("https://x.com/") == "https://x.com/"

    home = md5("HOME PAGE TEXT " * 90)
    # the site's own error route is the strongest signal
    assert verdict({"need": "leadership", "url": "https://a.com/leadership",
                    "final_url": "https://a.com/page-not-found?item=%2fleadership",
                    "text": "x" * 2000}, home).startswith("soft-404")
    # a 200 whose body says so
    assert verdict({"need": "facilities", "url": "u", "final_url": "u",
                    "text": "Page Not Found"}, home).startswith("soft-404")
    # a homepage stored as a leadership page
    assert verdict({"need": "leadership", "url": "u", "final_url": "u",
                    "text": "HOME PAGE TEXT " * 90}, home).startswith("homepage clone")
    # ...but the home page itself is legitimately the home page
    assert not verdict({"need": "home", "url": "u", "final_url": "u",
                        "text": "HOME PAGE TEXT " * 90}, home)
    # THE PAGE THAT MUST SURVIVE: 924 chars, the densest product content in the corpus
    sss = ("Assault Rifles P72 AR 7.62x39mm T72 AR 7.62x51mm M72 5.56x45mm NATO " * 12)
    assert not verdict({"need": "products", "url": "https://sssdefence.com/products/"
                        "assault-rifles", "final_url": "", "text": sss}, home), \
        "a short but dense product page must never be rejected on length"
    print("clean demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        run(a.apply)
