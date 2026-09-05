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

A SYNDICATED REWRITE IS A DUPLICATE, NOT A CONTINUATION -- and the test that catches
one is the DATE, not the wording. On the live feed five outlets covered a single
Saab-DGA contract on 2026-06-16 under five different headlines, with token overlap
around a third, nowhere near any similarity cut; four covered Anduril's Thunder
unveiling on 2026-07-20. Nothing developed between them. Same thread, same day is one
event. The headline test stays for the reprint that surfaces days later, and it needs
the publisher to differ, because two of the Caracal reports were one Rheinmetall press
release in German and in English.
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
    in_title = set()
    for r in rows:
        head = fold(r.get("title") or "")
        hay = fold("%s %s" % (r.get("title") or "", r.get("description") or ""))
        for d in sorted(r.get("designators") or ()):
            if d not in designator_of:
                continue
            fd = fold(d)
            if fd and fd in hay:
                by_key[(r.get("comp_id"), d)].append(r)
                if fd in head:
                    in_title.add((r.get("url"), d))

    # ONE ARTICLE CAN NAME TWO DESIGNATORS, AND ITS HEADLINE SAYS WHICH IT IS ABOUT.
    #
    # Neither size rule worked on the live feed. Preferring the SMALLEST thread let
    # "the missile" (2 articles) rob "brahmos" (5), publishing one story as two.
    # Preferring the LARGEST then let "gripen" (4) swallow "a3-001" (3) -- and with
    # those two Saab stories sharing a thread on one day, a Gripen/Taurus firing was
    # published as a duplicate of an A3-001 drone reveal.
    #
    # The article settles it: A3-001 is in that headline and Gripen is only in the
    # standfirst; BrahMos is in its headline and "the missile" is only in the
    # standfirst. Size decides only between two designators the headline names
    # equally -- PAC-3 and PAC-3 MSE, both in the same headline, are one story.
    # A THREAD OF ONE IS NOT A THREAD, AND CHOOSING KEYS CAN CREATE ONE.
    #
    # The size test below runs on the candidate membership, before each article picks
    # its key -- so a key with two candidates can end up with one member once the
    # other article picks a different key. Both MQ-28 articles were candidates for
    # "mq-28"; one also named "MQ-28 Ghost Bat" in its headline and went there, and
    # the live feed published two threads holding one article each. Dropping a
    # singleton frees its member to fall back to its next key, which can strand
    # another, so this repeats until nothing changes.
    dead = set()
    for _ in range(len(by_key) + 1):
        best = {}
        for (comp, d), members in by_key.items():
            if (comp, d) in dead or len(members) < 2:
                continue
            for r in members:
                rank = (1 if (r["url"], d) in in_title else 0, len(members), len(d))
                cur = best.get(r["url"])
                if cur is None or rank > cur[1]:
                    best[r["url"]] = (d, rank, comp)
        held = collections.Counter((v[2], v[0]) for v in best.values())
        singles = {k for k, n in held.items() if n < 2}
        if not singles:
            break
        dead |= singles
    best = dict((u, v) for u, v in best.items()
                if (v[2], v[0]) not in dead)

    out = {}
    threads = collections.defaultdict(list)
    for url, (d, _rank, comp) in best.items():
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
                if gap == 0:
                    # ONE EVENT, REPORTED SEVERAL TIMES. Nothing developed between
                    # two reports published the same day.
                    #
                    # Headline similarity alone did not catch this. Five outlets
                    # covered one Saab-DGA contract on 2026-06-16 under five
                    # different headlines, and four covered Anduril's Thunder
                    # unveiling on 2026-07-20 -- all published as "continues", which
                    # asserted developments that never happened. The domain test did
                    # not catch it either: two of the Caracal reports were one
                    # Rheinmetall press release, in German and in English, on one
                    # domain.
                    rec["duplicate_of_url"] = prev["url"]
                    rec["chain_evidence"]["same_day"] = True
                elif sim >= DUP_SIMILARITY and domain(prev.get("url")) != domain(r.get("url")):
                    # THE SAME PIECE SOMEWHERE ELSE, days later. Calling this a
                    # continuation would invent a development between two printings.
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

# The four columns are NOT created here. db/migrations/2026-09-06_news_chain.sql owns
# them, because it also recreates serving_live.competitor_news -- a view that
# enumerates its columns and cannot see one added to the table beneath it. An ALTER
# TABLE here produced exactly that: 84 rows written, and a dashboard that read the
# view and showed none of them.
COLUMNS = ("story_key", "continues_url", "duplicate_of_url", "chain_evidence")


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
        cur.execute("select column_name from information_schema.columns"
                    " where table_schema='serving_live'"
                    " and table_name='competitor_news'")
        served = set(r[0] for r in cur.fetchall())
        missing = [c for c in COLUMNS if c not in served]
        if missing:
            raise SystemExit(
                "serving_live.competitor_news is missing %s.\n"
                "Run db/migrations/2026-09-06_news_chain.sql first: it adds the "
                "columns AND recreates the view, and writing without the view means "
                "writing rows the dashboard cannot read."
                % ", ".join(missing))
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

    # THE SPLIT THAT LEAVES TWO SINGLETONS. Both articles are about the MQ-28; one
    # headline also names the fuller "MQ-28 Ghost Bat". Sending it there on the
    # headline rule would leave one article under each key and publish neither as a
    # story, so the narrower key is dropped and both fall back to the one they share.
    mq = [
        {"url": "https://a.com/m1", "comp_id": "rheinmetall",
         "title": "MQ-28 Ghost Bat completes 150 test flights", "description": "",
         "published_date": date(2026, 6, 10),
         "designators": {"mq-28", "mq-28 ghost bat"}},
        {"url": "https://a.com/m2", "comp_id": "rheinmetall",
         "title": "Boeing and Rheinmetall pitch MQ-28 for the CCA programme",
         "description": "", "published_date": date(2026, 8, 12),
         "designators": {"mq-28"}},
    ]
    mqo = thread(mq, {"mq-28", "mq-28 ghost bat"})
    ck("a narrower key that would strand both articles is dropped",
       len(mqo) == 2 and set(v["story_key"] for v in mqo.values()) == {"mq-28"},
       dict((k, v["story_key"]) for k, v in mqo.items()))
    ck("... and nothing published is a thread of one",
       all(v["chain_evidence"]["thread_size"] >= 2 for v in mqo.values()))
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

    # THE SAME EVENT, THREE OUTLETS, ONE DAY. Every one of these was published as a
    # continuation before the date test existed.
    same_day = [
        {"url": "https://a.com/x", "comp_id": "saab",
         "title": "Saab receives French order for NLAW anti-tank weapon",
         "description": "", "published_date": date(2026, 6, 16), "designators": {"nlaw"}},
        {"url": "https://b.com/y", "comp_id": "saab",
         "title": "Saab wins NLAW contract from French DGA",
         "description": "", "published_date": date(2026, 6, 16), "designators": {"nlaw"}},
        {"url": "https://saab.com/de/z", "comp_id": "saab",
         "title": "Saab signs NLAW deal with the French defence ministry",
         "description": "", "published_date": date(2026, 6, 16), "designators": {"nlaw"}},
    ]
    sd = thread(same_day, good)
    ck("one event covered by three outlets on one day is not three developments",
       all(v["continues_url"] is None for v in sd.values()))
    ck("... they are duplicates of the first report",
       sd["https://b.com/y"]["duplicate_of_url"] == "https://a.com/x"
       and sd["https://saab.com/de/z"]["duplicate_of_url"] == "https://a.com/x")
    ck("... and headline wording would not have caught them",
       similarity(same_day[0]["title"], same_day[1]["title"]) < DUP_SIMILARITY,
       round(similarity(same_day[0]["title"], same_day[1]["title"]), 2))
    # Which of two same-day reports is called the original is arbitrary -- they were
    # published the same day and nothing in the data ranks them. What matters is that
    # exactly one of the pair is a duplicate of the other, so the reader sees one
    # event and not two.
    lang = thread([dict(same_day[0], url="https://r.com/en"),
                   dict(same_day[1], url="https://r.com/de")], good)
    dups = [v["duplicate_of_url"] for v in lang.values() if v["duplicate_of_url"]]
    ck("one press release in two languages on one domain is still one event",
       len(dups) == 1 and dups[0] in lang, dups)

    # A WEAK KEY MUST NOT ROB A STRONG ONE.
    two_keys = [
        {"url": "https://a.com/b1", "comp_id": "brahmos-aerospace",
         "title": "BrahMos-NG design changes", "description": "the missile is revised",
         "published_date": date(2026, 6, 11), "designators": {"brahmos", "the missile"}},
        {"url": "https://a.com/b2", "comp_id": "brahmos-aerospace",
         "title": "Thailand evaluates BrahMos", "description": "the missile is offered",
         "published_date": date(2026, 8, 4), "designators": {"brahmos", "the missile"}},
        {"url": "https://a.com/b3", "comp_id": "brahmos-aerospace",
         "title": "BrahMos order book grows", "description": "",
         "published_date": date(2026, 6, 16), "designators": {"brahmos"}},
    ]
    tk = thread(two_keys, {"brahmos", "the missile"})
    ck("the headline decides: a standfirst-only key does not take the story",
       all(v["story_key"] == "brahmos" for v in tk.values()),
       dict((k, v["story_key"]) for k, v in tk.items()))

    # ... AND THE SAME RULE THE OTHER WAY ROUND. Here the specific designator has the
    # SMALLER thread, and it must still win, because it is what the headlines name.
    saab = [
        {"url": "https://a.com/s1", "comp_id": "saab",
         "title": "Saab displays A3-001 full-scale model",
         "description": "the Gripen maker's new concept",
         "published_date": date(2026, 8, 23), "designators": {"a3-001", "gripen"}},
        {"url": "https://a.com/s2", "comp_id": "saab",
         "title": "Saab showcases unmanned A3-001 combat aircraft",
         "description": "alongside Gripen",
         "published_date": date(2026, 8, 24), "designators": {"a3-001", "gripen"}},
        {"url": "https://a.com/s3", "comp_id": "saab",
         "title": "Hungary to modernise its air force with Saab",
         "description": "Gripen fleet", "published_date": date(2026, 3, 24),
         "designators": {"gripen"}},
        {"url": "https://a.com/s4", "comp_id": "saab",
         "title": "Swedish Gripen C fires KEPD-350 Taurus for the first time",
         "description": "", "published_date": date(2026, 8, 24),
         "designators": {"gripen"}},
    ]
    sb = thread(saab, {"a3-001", "gripen"})
    ck("a bigger thread does not swallow the one the headline names",
       sb["https://a.com/s1"]["story_key"] == "a3-001"
       and sb["https://a.com/s2"]["story_key"] == "a3-001",
       dict((k, v["story_key"]) for k, v in sb.items()))
    ck("... so an unrelated same-day story is not called a duplicate of it",
       sb["https://a.com/s4"]["duplicate_of_url"] is None,
       sb["https://a.com/s4"])

    ck("a rewrite on the SAME domain, days later, is a continuation not a duplicate",
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
