"""Per-company news for the Profile / Products / Geo panels, from the signal feed.

    python fill_competitor_news.py --dry-run     # default: report, write nothing
    python fill_competitor_news.py --apply
    python fill_competitor_news.py --demo        # parser asserts, no DB

`serving.competitor_news` was created with a serving_live view and never given a
writer, so the four news panels in the dashboard read from a hard-coded template
with the company name substituted into it -- the same five invented stories for
all 119 competitors, attributed to real publishers.

Nothing here generates text. Every row is a signal card the pipeline already
produced, wrote a date for from the article's own markup, and cited:

    title        the card's headline          serving.signal_card.title
    description  the card's one-line read     serving.signal_card.sowhat
    source       the publisher                parsed from meta / the url host
    url          the article                  serving.signal_card.url
    image        the article's own picture    serving.signal_card.image
    category     the news topic               news_category(): see NEWS_CATEGORIES
    published_date  the article's date        serving_fill.article_date (markup first)

Two fields are deliberately NOT written. `is_trending` stays false: nothing in the
pipeline measures trend, and the UI's "top story" slot is served honestly by the
newest row, which the ordering already gives it. There is no `impact` or
`fullText`: the panel's long-form fields are fed from signal_detail, which is real,
not from prose invented here.

Identity goes through aliases.canonical/same -- the SAME layer serving_fill and
enrich_serving use -- so "Kongsberg Defence & Aerospace" and "KONGSBERG" reach one
competitor row instead of being two feeds.
"""
import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# KSSL_DSN is what the extraction containers actually export; the other three are
# the source-tree names. Getting this wrong fails as "no such socket", which
# reads like the database is down rather than like an unset variable.
#
# KSSL_CORPUS_DSN is in the list because it is the ONLY one a replica has:
# provision_env.sh generates extraction/.env with that name alone, so without it this
# script runs on production (where both are set) and dies on staging and dev.
DSN = (os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
       or os.environ.get("KSSL_SERVING_DSN") or os.environ.get("DSN") or "")

# Only the publisher's own host is a source name. A card whose meta lost its
# "from <host>" tail still has the url, and the url host is the publisher.
_FROM = re.compile(r"\bfrom\s+([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*$")
_HOST = re.compile(r"^https?://(?:www\.)?([^/:]+)", re.I)


def source_of(meta, url):
    """-> the publishing host, or None. Never a guess: meta's own tail, else the url."""
    m = _FROM.search(meta or "")
    if m:
        return m.group(1).lower()
    m = _HOST.match(url or "")
    return m.group(1).lower() if m else None


def as_date(ymd):
    """-> 'YYYY-MM-DD' from article_date's (y, m, d), or None.

    A partial date stays partial by REFUSING, not by inventing a first-of-month.
    published_date is a timestamp column: writing 2026-07-01 for a card the
    publisher only dated to July would print "1 Jul 2026" in the panel, which is a
    day the article was not published on. The card keeps its month label; the news
    row is simply not written with a date it cannot prove.
    """
    if not ymd:
        return None
    y, m, d = (list(ymd) + [None, None])[:3]
    if not (y and m and d):
        return None
    try:
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ category
#
# `category` is what the Profile page's filter pills read, and those pills are a
# fixed NEWS-TOPIC vocabulary -- Defence, Financial, Government, Workforce, Markets --
# matched by substring. The first version of this writer copied signal_card.tags
# into it, and tags is the PORTFOLIO BAND ("Artillery", "UAVs & Drones", "Marine /
# Naval", ...). No band contains the word "workforce" or "markets", so those two
# pills were empty for every company by construction, and "Defence" matched only
# the one band that happens to contain it ("Missiles & Air Defence").
#
# The topic is derived from evidence the pipeline already wrote for the card --
# its title, one-line read, and the detail's what/why -- plus the lane the signal
# filler put it in. Nothing is inferred from a company name or a source host: a
# publisher covers every topic, and "Senator" is Roshel's armoured vehicle.
#
# Each lexicon is deliberately narrow, and the exclusions are measured, not
# theoretical. On the 1,127 production cards the broad first draft put "Corsair
# maritime drones used in combat" under Workforce (strike), "Australia to acquire
# AIM-260A missiles" under Financial (acquisition), "Ukraine receives 2,500 Senator
# vehicles" under Government (senator) and 408 cards under Markets because every
# analyst sentence says "market" or "demand". A row with no topic evidence but a
# portfolio band is "Defence": the band is the pipeline's own finding that the story
# is defence-industry news. A row with neither is left uncategorised (None), and
# the UI shows its own placeholder rather than a label nothing supports.

NEWS_CATEGORIES = ("Defence", "Financial", "Government", "Workforce", "Markets")

_WORKFORCE = re.compile(
    r"\b(jobs|hiring|hires|hired|employees|workforce|headcount|layoffs?|laid off"
    r"|redundanc\w+|recruit(s|ed|ing|ment)|apprentice\w*|appoint(s|ed|ment)"
    r"|named (as )?(ceo|chief executive|president|chairman|managing director)"
    r"|new ceo|chief executive officer|steps? down as|resigns? as)\b", re.I)
# "employment" is excluded: in defence text it is the employment OF a weapon.

_FINANCIAL = re.compile(
    r"\b(merger|merges with|takeover|stake in|buyout|ipo|share price|shares"
    r"|shareholders?|dividends?|ebitda|net (profit|income|loss)|operating (profit|income)"
    r"|(revenue|profit|earnings|order intake) growth"
    r"|(reports?|reported|posts?|posted|record|annual|quarterly|half-year|full-year"
    r"|h[12]|q[1-4]|fy ?\d{2,4}) (\w+ ){0,3}(revenues?|profits?|earnings|order intake|results)"
    r"|(raise[sd]?|upgrade[sd]?|exceed(s|ed)?|cut|cuts|lower(s|ed)?|maintain(s|ed)?"
    r"|reaffirm(s|ed)?|fy ?\d{2,4}|full-year|annual|profit|revenue|earnings) guidance"
    r"|quarterly results|financial results|order backlog|backlog"
    r"|invest(s|ed)? (\$|€|£|₹|us\$|[0-9])|investment of"
    r"|funding round|raises? (\$|€|£|₹)|series [a-d] (round|funding)|valuation"
    r"|bond issue|credit facility)\b", re.I)
# Bare "revenue"/"profit" and bare "guidance" are excluded: the analyst's
# why-sentence says "adds to X's revenue" on ordinary contract wins, and a TACAN
# is a navigation GUIDANCE system. Results need a reporting word next to them.
# "acquire/acquisition" alone is procurement language ("acquire 200 missiles",
# "Defence Acquisition Council"). It is corporate finance only next to a corporate
# noun: "acquires Iveco Defence BUSINESS", "acquisition of the COMPANY".
_ACQUIRE = re.compile(r"\bacqui(res|red|re|sition|sitions)\b", re.I)
_CORPORATE = re.compile(
    r"\b(business(es)?|company|companies|firm|subsidiary|division|unit|holdings?"
    r"|stake|deal|takeover|merger|shareholders?)\b", re.I)

_GOVERNMENT = re.compile(
    r"\b(parliament(ary)?|congress(ional)?|lawmakers?|legislat\w+|regulat(ory|ion|ions)"
    r"|budgets?|budgetary|allocat(es|ed|ion)|appropriat(es|ed|ion|ions)"
    r"|polic(y|ies)|sanction(s|ed)?|approv(es|ed|al)|clears|cleared|clearance"
    r"|tender(s|ed)?|rfp|rfi|request for (proposal|information)"
    r"|tariffs?|subsid(y|ies|ised|ized)|bans?|banned|foreign military sales?|fms"
    r"|defence acquisition council|military aid"
    r"|export (control|ban|licen[cs]e)|licen[cs]e (approval|granted))\b", re.I)
# A bare "ministry", "government" or "Pentagon" is excluded: it is the CUSTOMER in
# most contract stories, and the story is then the contract, not a government act.
# "senator" is excluded because it is a Roshel product line, and a bare "licence"
# because licensed PRODUCTION is an industrial arrangement, not a government act.

_MARKETS = re.compile(
    r"\b(exports?|exported|exporters?|market (entry|expansion|share|size|growth"
    r"|forecast|opportunity)|forecasts?|projected (to|at)|expan(ds|ded|sion) (into|to)"
    r"|enters? the [\w -]{0,30}market|new markets?|overseas|global market"
    r"|international (sales|customers|orders|market)"
    r"|foreign (buyers?|customers?|sales|market))\b", re.I)
# Bare "market" and "demand" are excluded: the analyst's why-sentence says one of
# them on a third of all cards ("signals growing demand for ...").


def news_category(card):
    """-> one of NEWS_CATEGORIES, or None when nothing on the card supports a label.

    `card` is the signal_card row as a dict, optionally carrying the detail's
    "what" and "why". The order is specificity: a story that names jobs or an
    acquisition is filed there even if it also mentions a budget; the pipeline's
    MARKET lane is a weaker, structural piece of evidence used only when the text
    itself names no topic; the portfolio band is the last resort and yields only
    the generic label. A band never becomes a category name of its own, and never
    becomes a specific topic.
    """
    text = " ".join(str(card.get(k) or "") for k in ("title", "sowhat", "what", "why"))
    if _WORKFORCE.search(text):
        return "Workforce"
    if _FINANCIAL.search(text) or (_ACQUIRE.search(text) and _CORPORATE.search(text)):
        return "Financial"
    if _GOVERNMENT.search(text):
        return "Government"
    if _MARKETS.search(text):
        return "Markets"
    if (card.get("lane") or "").lower() == "market":
        # The signal filler's own verdict: "a procurement or demand event with no
        # single winning maker". That is market news by the pipeline's definition.
        return "Markets"
    if (card.get("tags") or "").strip():
        return "Defence"
    return None


def build(cards, comp_index, date_of):
    """-> (rows, stats). Pure: no DB, no network. `cards` are dicts, `comp_index`
    maps a folded company name to comp_id, `date_of` resolves a document id."""
    rows, stats = [], {"no_company": 0, "unmatched": 0, "no_url": 0, "undated": 0}
    for c in cards:
        if not c.get("company"):
            stats["no_company"] += 1
            continue
        cid = comp_index.get(c["company"])
        if not cid:
            stats["unmatched"] += 1
            continue
        if not c.get("url"):
            # A news item with no link is not checkable, and the panel renders it
            # as a click target. Refuse it rather than ship a dead card.
            stats["no_url"] += 1
            continue
        when = date_of(c["id"])
        if not when:
            stats["undated"] += 1
            continue
        rows.append({
            "comp_id": cid,
            "title": c["title"],
            "description": c.get("sowhat") or None,
            "source": source_of(c.get("meta"), c["url"]),
            "published_date": when,
            "category": news_category(c),
            "url": c["url"],
            "image": c.get("image") or None,
        })
    rows.sort(key=lambda r: (r["comp_id"], r["published_date"]), reverse=False)
    return rows, stats


# ------------------------------------------------------------------------ db side

def _comp_index(cur):
    """folded competitor name -> comp_id, via the shared identity layer.

    The roster's own names are kept alongside the index: a division has to be matched
    against them one at a time, and equality alone cannot do it.
    """
    from aliases import canonical, fold
    cur.execute("SELECT comp_id, name FROM serving.competitors "
                "WHERE origin='pipeline' ORDER BY ord")
    idx, roster = {}, []
    for cid, name in cur.fetchall():
        roster.append((cid, name))
        for key in {fold(name), fold(canonical(name) or name)}:
            if key:
                idx.setdefault(key, cid)          # first ord wins on a collision
    idx["__roster__"] = roster
    return idx


def _lookup(idx):
    """Find the competitor a card's company field names.

    THE FIELD IS HTML. `Adani Defence &amp; Aerospace` is what the extractor wrote,
    and `&amp;` never folds onto `&`, so four Adani articles reached no company at
    all. Unescaping is not cosmetic here: it is the difference between a competitor
    with news and one the dashboard shows as silent.

    THE FIELD IS ALSO OFTEN A DIVISION. "American Rheinmetall", "KNDS France",
    "Hanwha Defense USA", "BAE Systems Bofors" -- the roster holds the parent, and
    equality after folding sends all of them nowhere. aliases.same_org decides that,
    with the word-boundary guard that stops "Elbit" absorbing Elbit Imaging.
    """
    import html
    from aliases import canonical, fold, is_force, same_org
    roster = idx.get("__roster__", [])

    def f(name):
        name = html.unescape(name or "")
        for key in (fold(name), fold(canonical(name) or name)):
            if key and key in idx:
                return idx[key]
        # An armed service or a ministry is the CUSTOMER in the story, never the
        # company it is about. Checked before containment, because "Indian Navy"
        # would otherwise reach nobody anyway and "US Army" costs nothing to skip.
        if is_force(name):
            return None
        for cid, rname in roster:
            if same_org(name, rname):
                return cid
        return None
    return f


def run(dsn=DSN, apply=False):
    import psycopg2
    from serving_fill import article_date
    con = psycopg2.connect(dsn, connect_timeout=10, keepalives=1,
                           keepalives_idle=30, keepalives_interval=10)
    cur = con.cursor()
    # The detail's what/why are the card's own long-form read of the article; they
    # are the evidence news_category() classifies on, alongside title and sowhat.
    cur.execute("""SELECT c.id, c.title, c.sowhat, c.meta, c.company, c.tags, c.url,
                          c.image, c.lane, d.what, d.why
                     FROM serving.signal_card c
                     LEFT JOIN serving.signal_detail d ON d.id = c.id
                    WHERE c.origin='pipeline' ORDER BY c.ord""")
    cols = ("id", "title", "sowhat", "meta", "company", "tags", "url", "image",
            "lane", "what", "why")
    cards = [dict(zip(cols, r)) for r in cur.fetchall()]

    idx = _comp_index(cur)
    look = _lookup(idx)

    def date_of(card_id):
        # card ids are 'pl_<document_id>'; article_date reads the article's markup.
        did = card_id[3:] if card_id.startswith("pl_") else card_id
        try:
            return as_date(article_date(cur, did))
        except Exception as e:                                       # noqa: BLE001
            print("  date lookup failed for %s: %s" % (did, e), flush=True)
            return None

    class _Idx(dict):
        def get(self, k, default=None):
            return look(k) or default

    rows, stats = build(cards, _Idx(), date_of)
    per_company = len({r["comp_id"] for r in rows})
    print("cards: %d · rows: %d across %d compan(ies) · skipped: "
          "%d no company, %d not a tracked competitor, %d no link, %d no provable date"
          % (len(cards), len(rows), per_company, stats["no_company"],
             stats["unmatched"], stats["no_url"], stats["undated"]), flush=True)
    # Per pill, so an empty one is visible here before it is visible on the page.
    by_cat = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print("categories: " + ", ".join("%s %d" % (c, by_cat.get(c, 0))
                                     for c in NEWS_CATEGORIES + (None,)), flush=True)
    # Per company too: "news is missing for X" is answered here, by name, before
    # anyone opens X's profile. A tracked competitor absent from this list has no
    # dated, linked signal card -- which is a fact about the corpus, not a bug here.
    by_comp = {}
    for r in rows:
        by_comp[r["comp_id"]] = by_comp.get(r["comp_id"], 0) + 1
    print("per company: " + ", ".join("%s %d" % kv for kv in sorted(by_comp.items())),
          flush=True)

    if not apply:
        print("dry run: nothing written (pass --apply)", flush=True)
        for r in rows[:5]:
            print("  %-14s %s  %-22s %s" % (r["comp_id"], r["published_date"],
                                            (r["source"] or "-")[:22], r["title"][:60]),
                  flush=True)
        con.close()
        return {"rows": len(rows), "companies": per_company, **stats}

    # FAIL FAST IF A REBUILD IS MID-FLIGHT, INSTEAD OF HANGING FOR AN HOUR.
    #
    # Every INSERT below takes a foreign-key row lock on serving.competitors. An enrich
    # pass opens step_companies by DELETEing every origin='pipeline' competitor and then
    # sits idle-in-transaction for the length of its profile calls -- 51 minutes when
    # this was measured. So an --apply started during a pass does not fail and does not
    # finish: it blocks on `Lock / transactionid` behind that backend, prints its whole
    # summary first (the counts come before the write), and looks for all the world like
    # a successful run that wrote nothing. Three separate operator runs were lost to
    # exactly that on 2026-09-05, each killed by its own outer timeout mid-INSERT.
    #
    # 30s is far longer than this write needs when nothing holds the parent rows, and
    # far shorter than a pass. The error names the cause, so the next person sees "a
    # rebuild is running" rather than an unexplained hang.
    cur.execute("SET lock_timeout='30s'")
    try:
        # Idempotent: this writer owns every origin='pipeline' row in the table.
        cur.execute("DELETE FROM serving.competitor_news WHERE origin='pipeline'")
        deleted = cur.rowcount
        # It is the INSERTs that block, not the delete: each takes a foreign-key row
        # lock on the serving.competitors row it points at, and those are exactly the
        # rows a rebuild has deleted inside its open transaction.
        for r in rows:
            cur.execute("""INSERT INTO serving.competitor_news
                           (comp_id, title, description, source, published_date,
                            category, url, image, origin)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')""",
                        (r["comp_id"], r["title"], r["description"], r["source"],
                         r["published_date"], r["category"], r["url"], r["image"]))
    except psycopg2.errors.LockNotAvailable:
        con.rollback()
        con.close()
        print("REFUSED: serving.competitors is locked by a rebuild in flight "
              "(enrich step_companies holds those rows until its profile calls "
              "finish). Nothing was written -- the counts above are what WOULD have "
              "been written. The pass refills this table itself; run this by hand "
              "only between passes.", flush=True)
        return {"rows": 0, "companies": 0, "blocked": True, **stats}
    con.commit()
    print("written: %d row(s) (%d replaced)" % (len(rows), deleted), flush=True)
    con.close()
    return {"rows": len(rows), "companies": per_company, **stats}


def _demo():
    assert source_of("UAVs · L3Harris · from airandspaceforces.com",
                     "https://x.test/a") == "airandspaceforces.com"
    assert source_of("no tail here", "https://www.seapowermagazine.org/27585-2") \
        == "seapowermagazine.org", "www. is not part of the publisher's name"
    assert source_of(None, None) is None
    assert source_of("from not-a-host", "notaurl") is None, \
        "a bare word after 'from' is not a publisher"

    assert as_date((2026, 7, 13)) == "2026-07-13"
    assert as_date((2026, 7, None)) is None, \
        "a month-only date must NOT become the first of the month"
    assert as_date((2026, None, None)) is None and as_date(None) is None
    assert as_date(("2023", "01", "9")) == "2023-01-09"

    cards = [
        {"id": "pl_d1", "title": "A wins X", "sowhat": "so", "meta": "c · A · from p.com",
         "company": "Saab", "tags": "Artillery", "url": "https://p.com/1", "image": "i"},
        {"id": "pl_d2", "title": "no company", "company": None, "url": "https://p.com/2"},
        {"id": "pl_d3", "title": "untracked", "company": "Nobody Ltd",
         "url": "https://p.com/3"},
        {"id": "pl_d4", "title": "no link", "company": "Saab", "url": None},
        {"id": "pl_d5", "title": "undated", "company": "Saab", "url": "https://p.com/5"},
    ]
    idx = {"Saab": "saab"}
    dates = {"pl_d1": "2026-07-13", "pl_d5": None}
    rows, st = build(cards, idx, lambda i: dates.get(i))
    assert len(rows) == 1 and rows[0]["comp_id"] == "saab", rows
    assert rows[0]["source"] == "p.com" and rows[0]["image"] == "i"
    assert st == {"no_company": 1, "unmatched": 1, "no_url": 1, "undated": 1}, st
    assert "is_trending" not in rows[0], \
        "nothing here measures trend, so nothing here claims it"
    print("fill_competitor_news demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--apply", action="store_true",
                    help="write; without it this is a dry run")
    ap.add_argument("--dry-run", action="store_true", help="the default")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(dsn=a.dsn, apply=a.apply)
