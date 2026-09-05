# -*- coding: utf-8 -*-
"""Which articles are the same running story, and which merely repeat it.

    python news_chain.py --demo      # hermetic: the rules, no database
    python news_chain.py             # report against the live feed, write nothing
    python news_chain.py --apply     # write story_key / continues_url / duplicate_of_url

A company page lists its articles newest to oldest, and that ordering is all the
reader gets: three separate PAC-3 stories in a fortnight read as three unrelated
events, and the same wire piece republished by four outlets reads as four. This
module says which of those are one thread.

WHAT JOINS TWO ARTICLES IS AN ENTITY THE EXTRACTOR ALREADY FOUND.

`extracted.span` holds 10.9 million typed spans over the corpus -- WeaponSystem,
Platform, Program, Product, Identifier among them -- and 262 of the 276 published
news rows join to a document that has them. So the thread key is not a regex over
headlines: it is a span the extraction layer typed, on both articles, in both
headlines.

THE TYPE IS NOT ENOUGH, AND THAT IS THE WHOLE PROBLEM.

The extractor types "GlobalEye" as Platform, and it types "aircraft" as Platform
too. Joining on shared typed spans produced 137 candidate pairs whose commonest
joiners were `missile` (117 pairs), `aircraft` (64), `program` (44) and -- from a
share button in the page furniture -- `whatsapp` (14). A chain built on those
asserts a continuity the sources never claimed, and a wrong chain is worse than no
chain, so a category noun has to be told from a name. Two measured properties do
it, and both are computed from the corpus rather than listed by hand:

  RARITY. A designator names one programme; a category noun names a class of them.
  Measured over 39,307 documents: system 6,565 documents, aircraft 5,413, missile
  3,182, weapons 2,730 -- against BrahMos 494, Gripen 416, PAC-3 243, GlobalEye
  184, NLAW 70, RCH 155 51. The cut is 2% of the corpus -- BrahMos at 1.26% and
  Gripen at 1.06% are what a tighter one costs.

  CASE, WHERE THE SCRIPT HAS CASE. A name keeps its capital in running text; a
  common noun does not. Measured as the share of a surface's occurrences that are
  entirely lower-case: interceptors 97%, munitions 92%, artillery 91%, howitzer
  87%, munition 57% -- against `the missile` 9%, Thunder 7%, BrahMos 3%, Patriot
  1%, Gripen 0%, PAC-3 0%. The cut is 25%, with a margin of 30 points either side.

  A caseless script -- CJK, Arabic, Hebrew, Devanagari -- has no capital to keep,
  so a lower-case test applied to it refuses every designator in those languages.
  This repo has shipped that fault three times under three different names, so the
  case rule runs ONLY where the surface actually has a cased letter, and rarity
  alone decides the rest. That is also why a surface must contain a letter at all:
  `001` is 100% lower-case and 40 documents rare, and passes both tests by having
  no letters for either to bite on. It is a fragment of `A3-001`, and it names
  nothing.

A THREAD IS NOT A WINDOW.

Every article naming NLAW for Saab belongs to one thread, whether they are a week
or a year apart -- that is what the reader is being offered. A time limit belongs
on the CONTINUATION LINK, which claims that this article follows from that one:
93 candidate pairs, 54 of them within a week and 87 within 90 days. Beyond that
the claim is not supportable from a shared name alone, so the thread still holds
them and the link does not.

A SYNDICATED REWRITE IS A DUPLICATE, NOT A CONTINUATION. Same thread, near-identical
headline, different publisher: that is one event reported twice, and calling it a
continuation would invent a development that never happened.
"""
import argparse
import collections
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

DSN = (os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
       or os.environ.get("KSSL_SERVING_DSN") or os.environ.get("DSN") or "")

# The span types that can name a running story. Organization is deliberately absent:
# every article about a company names the company, so it would thread the whole feed.
SPAN_TYPES = ("WeaponSystem", "Platform", "Program", "Product", "Identifier")

# 2% of the corpus, not 1%: BrahMos appears in 494 documents and Gripen in 416, and
# a cut at 393 refused both. Rarity is the backstop here -- the case rule is what
# actually separates a name from a category noun, and it refuses every one of the
# category nouns rarity alone let through (munition, artillery, submarine,
# interceptor, howitzer). Rarity still has to run, because it is the ONLY test a
# caseless script gets.
MAX_DF_SHARE = 0.02
MAX_LOWER_SHARE = 0.25  # ... and keeps its capital, where the script has one
MIN_LEN, MAX_LEN = 3, 60
CONTINUES_DAYS = 90     # the link claims a development; the thread does not
DUP_SIMILARITY = 0.75   # headline overlap that means "the same piece, elsewhere"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fold(s):
    """Case- and accent-insensitive, punctuation collapsed. Script-preserving:
    NFKD strips the accents Latin text carries without touching CJK."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", s.lower(), flags=re.UNICODE).strip()


def has_case(s):
    """Does this surface contain a letter that HAS an upper and a lower form?

    False for 一式, العربية, हिन्दी and for `001` -- and for those the lower-case
    test below cannot mean anything, so it is not run.
    """
    return any(c.isalpha() and c.lower() != c.upper() for c in str(s or ""))


def has_letter(s):
    return any(c.isalpha() for c in str(s or ""))


def is_designator(surface, df, n_total, n_lower, corpus_docs):
    """Is this surface a name, or a category noun?

    df           documents in the corpus containing it
    n_total      occurrences of it
    n_lower      occurrences written entirely in lower case
    corpus_docs  documents in the corpus
    """
    s = (surface or "").strip()
    if not (MIN_LEN <= len(s) <= MAX_LEN):
        return False
    if not has_letter(s):
        return False           # `001` is a fragment, not a designator
    if not corpus_docs or df > MAX_DF_SHARE * corpus_docs:
        return False
    if has_case(s) and n_total:
        if float(n_lower) / n_total >= MAX_LOWER_SHARE:
            return False
    return True


def _tokens(s):
    return [t for t in fold(s).split() if t]


def similarity(a, b):
    """Jaccard over headline tokens. Not a language model, and it does not need to
    be: a syndicated rewrite keeps the words."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def domain(url):
    m = re.match(r"https?://([^/]+)", str(url or ""), re.I)
    return (m.group(1).lower().replace("www.", "") if m else "").strip()


def thread(rows, designator_of):
    """-> {url: {story_key, continues_url, duplicate_of_url, chain_evidence}}

    `rows`          [{url, comp_id, title, description, published_date(date), designators}]
                    newest-first order is NOT assumed; the dates decide.
    `designator_of` a set of surfaces that passed is_designator().

    A designator counts for a row only when it is in that row's own headline or
    standfirst. A span buried in the body -- or in the page furniture, which is
    where `whatsapp` lives -- does not make the article ABOUT that thing.
    """
    by_key = collections.defaultdict(list)
    for r in rows:
        hay = fold("%s %s" % (r.get("title") or "", r.get("description") or ""))
        for d in sorted(r.get("designators") or ()):
            if d not in designator_of:
                continue
            if fold(d) and fold(d) in hay:
                by_key[(r.get("comp_id"), d)].append(r)

    # One article can name two designators. It belongs to the thread whose key is
    # the rarest -- the most specific thing it is about -- so an article naming both
    # "PAC-3" and "PAC-3 MSE" threads with the MSE stories, not against them.
    best = {}
    for (comp, d), members in by_key.items():
        if len(members) < 2:
            continue                    # a thread of one is not a thread
        for r in members:
            cur = best.get(r["url"])
            if cur is None or len(members) < cur[1] or (
                    len(members) == cur[1] and d > cur[0]):
                best[r["url"]] = (d, len(members), comp)

    out = {}
    threads = collections.defaultdict(list)
    for url, (d, _n, comp) in best.items():
        threads[(comp, d)].append(url)

    for (comp, d), urls in threads.items():
        members = [r for r in rows if r["url"] in set(urls)]
        members.sort(key=lambda r: (r.get("published_date") or "", r.get("url")))
        prev = None
        for r in members:
            rec = {"story_key": d, "continues_url": None, "duplicate_of_url": None,
                   "chain_evidence": {"designator": d, "thread_size": len(members)}}
            if prev is not None:
                sim = similarity(prev.get("title"), r.get("title"))
                gap = None
                if prev.get("published_date") and r.get("published_date"):
                    gap = (r["published_date"] - prev["published_date"]).days
                if sim >= DUP_SIMILARITY and domain(prev.get("url")) != domain(r.get("url")):
                    # THE SAME PIECE SOMEWHERE ELSE. Calling this a continuation
                    # would invent a development between two printings of one story.
                    rec["duplicate_of_url"] = prev["url"]
                    rec["chain_evidence"]["headline_overlap"] = round(sim, 2)
                elif gap is not None and gap <= CONTINUES_DAYS:
                    rec["continues_url"] = prev["url"]
                    rec["chain_evidence"]["days_after"] = gap
                else:
                    rec["chain_evidence"]["unlinked"] = (
                        "same thread, %s" % ("no date" if gap is None
                                             else "%d days apart" % gap))
            out[r["url"]] = rec
            # A duplicate is not the thread's new head: the next article continues
            # the story, not the reprint of it.
            if rec["duplicate_of_url"] is None:
                prev = r
    return out


# ---------------------------------------------------------------- database ----
STATS_SQL = """
select lower(btrim(text)) surf,
       count(distinct document_id) df,
       count(*) n_total,
       count(*) filter (where btrim(text) = lower(btrim(text))) n_lower
from extracted.span
where type = any(%s) and length(btrim(text)) between %s and %s
group by 1
"""

ROWS_SQL = """
select n.url, n.comp_id, n.title, n.description, n.published_date::date
from serving.competitor_news n
where n.url is not null
order by n.published_date desc nulls last
"""

SPANS_SQL = """
select d.url, lower(btrim(s.text))
from serving.competitor_news n
join extracted.document d on d.url = n.url
join extracted.span s on s.document_id = d.document_id
where s.type = any(%s) and length(btrim(s.text)) between %s and %s
"""

DDL = """
alter table serving.competitor_news add column if not exists story_key text;
alter table serving.competitor_news add column if not exists continues_url text;
alter table serving.competitor_news add column if not exists duplicate_of_url text;
alter table serving.competitor_news add column if not exists chain_evidence jsonb;
"""


def run(dsn=DSN, apply=False):
    import json
    import psycopg2
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    cur.execute("select count(distinct document_id) from extracted.span")
    corpus_docs = cur.fetchone()[0]
    cur.execute(STATS_SQL, (list(SPAN_TYPES), MIN_LEN, MAX_LEN))
    stats = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    good = {s for s, (df, nt, nl) in stats.items()
            if is_designator(s, df, nt, nl, corpus_docs)}
    print("corpus: %d documents, %d candidate surfaces, %d designators"
          % (corpus_docs, len(stats), len(good)))

    cur.execute(ROWS_SQL)
    rows = [{"url": u, "comp_id": c, "title": t, "description": d,
             "published_date": p, "designators": set()}
            for u, c, t, d, p in cur.fetchall()]
    by_url = {r["url"]: r for r in rows}
    cur.execute(SPANS_SQL, (list(SPAN_TYPES), MIN_LEN, MAX_LEN))
    hit = 0
    for url, surf in cur.fetchall():
        r = by_url.get(url)
        if r is not None and surf in good:
            r["designators"].add(surf)
            hit += 1
    print("%d rows, %d with a document, %d designator mentions"
          % (len(rows), sum(1 for r in rows if r["designators"]), hit))

    linked = thread(rows, good)
    threads = collections.Counter(v["story_key"] for v in linked.values())
    cont = sum(1 for v in linked.values() if v["continues_url"])
    dups = sum(1 for v in linked.values() if v["duplicate_of_url"])
    print("\n%d articles in %d threads: %d continuations, %d duplicates"
          % (len(linked), len(threads), cont, dups))
    for key, n in threads.most_common(20):
        print("   %-34s %d article(s)" % (key, n))

    if not linked:
        print("\n   WARNING: nothing threaded. A rule that never fires is not running.")

    if apply:
        cur.execute(DDL)
        cur.execute("update serving.competitor_news set story_key=null,"
                    " continues_url=null, duplicate_of_url=null, chain_evidence=null")
        for url, rec in linked.items():
            cur.execute("update serving.competitor_news set story_key=%s,"
                        " continues_url=%s, duplicate_of_url=%s, chain_evidence=%s"
                        " where url=%s",
                        (rec["story_key"], rec["continues_url"],
                         rec["duplicate_of_url"], json.dumps(rec["chain_evidence"]),
                         url))
        conn.commit()
        print("\nwrote %d threaded rows" % len(linked))
    else:
        print("\n(report only; --apply writes)")
    return 0


# -------------------------------------------------------------------- demo ----
def demo():
    from datetime import date
    fails = []

    def ck(name, ok, d=""):
        print("  %-66s %s%s" % (name, "PASS" if ok else "FAIL", "  " + str(d) if d else ""))
        if not ok:
            fails.append(name)

    N = 39307
    # Measured over the live corpus. Every number below was read off extracted.span.
    ck("a category noun is refused on rarity",
       not is_designator("missile", 3182, 3200, 2900, N))
    ck("so is one that is rare enough but written lower-case",
       not is_designator("munition", 447, 684, 390, N))       # 57% lower
    ck("and one at the very edge of the case rule",
       not is_designator("loitering munition", 109, 183, 128, N))  # 70% lower
    ck("a designator passes both",
       is_designator("BrahMos", 494, 2710, 81, N))            # 3% lower, 1.26% of docs
    ck("... and a tighter rarity cut would have refused it",
       not is_designator("BrahMos", 494, 2710, 81, N // 2))
    ck("a rare designator passes",
       is_designator("NLAW", 70, 281, 0, N))
    ck("a designator that is common but always capitalised still passes rarity",
       is_designator("Patriot", 339, 696, 7, N))
    ck("page furniture is refused by the headline rule, not by these",
       is_designator("WhatsApp", 313, 400, 0, N))   # rarity+case cannot see it

    # THE LANGUAGE-DETECTOR TRAP, WHICH THIS REPO HAS PAID FOR THREE TIMES.
    ck("a caseless script is judged on rarity alone, not refused wholesale",
       is_designator("あきづき型護衛艦", 12, 30, 30, N))
    ck("... and the same in Hebrew",
       is_designator("כיפת ברזל", 40, 90, 90, N))
    ck("... and in Devanagari",
       is_designator("ब्रह्मोस", 30, 60, 60, N))
    ck("a common noun in a caseless script is still refused on rarity",
       not is_designator("ミサイル", 3000, 5000, 5000, N))
    ck("a digit fragment is refused: it has no letter for either test to bite on",
       not is_designator("001", 40, 136, 136, N))

    # THREADING
    rows = [
        {"url": "https://a.com/1", "comp_id": "saab", "title": "Saab wins NLAW order",
         "description": "", "published_date": date(2026, 1, 5), "designators": {"nlaw"}},
        {"url": "https://a.com/2", "comp_id": "saab",
         "title": "NLAW deliveries begin under the January order",
         "description": "", "published_date": date(2026, 2, 3), "designators": {"nlaw"}},
        {"url": "https://b.com/9", "comp_id": "saab", "title": "Saab wins NLAW order",
         "description": "", "published_date": date(2026, 1, 6), "designators": {"nlaw"}},
        {"url": "https://c.com/7", "comp_id": "saab", "title": "Saab reports Q4 revenue",
         "description": "", "published_date": date(2026, 1, 20), "designators": set()},
        {"url": "https://a.com/5", "comp_id": "rheinmetall",
         "title": "Rheinmetall unveils Skyranger 35",
         "description": "", "published_date": date(2026, 1, 8), "designators": {"skyranger"}},
    ]
    good = {"nlaw", "skyranger"}
    out = thread(rows, good)

    ck("an article naming no designator is not threaded",
       "https://c.com/7" not in out)
    ck("a lone article about a designator is not a thread of one",
       "https://a.com/5" not in out, out.get("https://a.com/5"))
    ck("the follow-up continues the original",
       out.get("https://a.com/2", {}).get("continues_url") == "https://a.com/1")
    ck("the same headline elsewhere is a DUPLICATE, not a continuation",
       out.get("https://b.com/9", {}).get("duplicate_of_url") == "https://a.com/1"
       and out["https://b.com/9"]["continues_url"] is None)
    ck("a duplicate does not become the thread's head",
       out.get("https://a.com/2", {}).get("continues_url") != "https://b.com/9")
    ck("the thread key is the designator",
       out.get("https://a.com/1", {}).get("story_key") == "nlaw")
    ck("the evidence names what joined them",
       out.get("https://a.com/2", {}).get("chain_evidence", {}).get("designator") == "nlaw")

    # A designator that is only in the body does not make the article about it.
    body_only = [
        {"url": "https://a.com/10", "comp_id": "saab", "title": "Saab annual results",
         "description": "Revenue up.", "published_date": date(2026, 3, 1),
         "designators": {"nlaw"}},
        {"url": "https://a.com/11", "comp_id": "saab", "title": "Saab board changes",
         "description": "New chair.", "published_date": date(2026, 3, 5),
         "designators": {"nlaw"}},
    ]
    ck("a designator absent from both headlines threads nothing",
       thread(body_only, good) == {})

    # Two companies are two threads even on the same designator.
    cross = [
        {"url": "https://a.com/20", "comp_id": "saab", "title": "NLAW order",
         "description": "", "published_date": date(2026, 1, 1), "designators": {"nlaw"}},
        {"url": "https://a.com/21", "comp_id": "thales", "title": "NLAW subsystem deal",
         "description": "", "published_date": date(2026, 1, 2), "designators": {"nlaw"}},
    ]
    ck("one designator across two companies is not one thread",
       thread(cross, good) == {})

    # Beyond the window: same thread, no continuation claim.
    far = [
        {"url": "https://a.com/30", "comp_id": "saab", "title": "NLAW order",
         "description": "", "published_date": date(2024, 1, 1), "designators": {"nlaw"}},
        {"url": "https://a.com/31", "comp_id": "saab", "title": "NLAW production ends",
         "description": "", "published_date": date(2026, 1, 1), "designators": {"nlaw"}},
    ]
    f = thread(far, good)
    ck("two years apart stay one thread but claim no continuation",
       f.get("https://a.com/31", {}).get("continues_url") is None
       and f.get("https://a.com/31", {}).get("story_key") == "nlaw")

    ck("a rewrite on the SAME domain is a continuation, not a duplicate",
       thread([dict(rows[0]), dict(rows[0], url="https://a.com/1b",
                                   published_date=date(2026, 1, 7))], good)
       .get("https://a.com/1b", {}).get("continues_url") == "https://a.com/1")

    print("\n%s" % ("all checks passed" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.demo:
        return demo()
    if not DSN:
        raise SystemExit("no DSN in the environment")
    return run(DSN, apply=a.apply)


if __name__ == "__main__":
    sys.exit(main())
