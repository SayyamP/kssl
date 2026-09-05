"""Each competitor's latest ANNUAL revenue, read from the extraction corpus.

    python fill_revenue.py --apply
    python fill_revenue.py --demo        # rule asserts, no DB

WHERE THIS COMES FROM, AND WHERE IT DOES NOT
--------------------------------------------
`serving.competitors.sales` is what the Profile panel renders under "Annual revenue /
sales". It used to be filled by pipeline/harvest, which fetched each company's own
investor-relations pages; that was retired on 2026-09-05 (see archive/README.md) because
the dashboard states facts from the corpus, and a figure scraped off a marketing page is
not one. The only source here is `extracted.proposition`, and every stored figure carries
the document URL and the verbatim sentence it was read from, exactly as every other
sourced surface does.

WHAT COUNTS AS AN ANNUAL REVENUE, AND WHAT DOES NOT
---------------------------------------------------
The corpus is full of money that sits near the word "revenue" and is not one. Every rule
below was written against a real proposition that reached this module's first run:

  not a subset      SIPRI's Top 100 lines state BOTH: "reported arms revenues of US$5,550
                    million and total revenues of US$6,030 million". Arms revenue is a
                    part of company revenue, so taking it understates every diversified
                    firm -- Saab by 8%, BAE by more.
  not a quarter     "Lockheed Martin's net sales totalled $15bn in the three-month period
                    that ended on 27 March 2022" is Q1, and it is written with a hyphen,
                    which a `three months` pattern walks straight past.
  not a forecast    "Papperger predicted ... EUR 15 billion in 2026", "maintained its 2022
                    revenue guidance of $65.25 billion", "approximately $74 billion in pro
                    forma 2019 net sales". None of these is a result.
  not a rate        "Saab invests 17 percent of revenue in R&D".
  not undated       a figure with no year cannot be ranked, and cannot be called "latest".
  not unit-less     "$400" and "US$186" were a share price and a list position sitting
                    beside the word revenue.

THE EVIDENCE SENTENCE GOVERNS. The extracted `object` is a fragment the model wrote; the
`ev_quote` is what the document actually said. Judging the fragment alone admitted a
prediction, because the word "predicted" lived only in the sentence around it.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aliases import canonical as canon_name, fold as fold_name  # noqa: E402

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
THIS_YEAR = datetime.date.today().year

REVENUE = re.compile(r"\b(revenues?|turnover|net sales|annual sales|total income|"
                     r"total revenue|gross sales)\b", re.I)
NOT_ANNUAL = re.compile(r"\bq[1-4]\b|\bquarter(?:ly)?\b|\bthree[- ]months?\b"
                        r"|\bsix[- ]months?\b|\bnine[- ]months?\b|\bhalf[- ]year\b"
                        r"|\bfirst half\b|\bsecond half\b|\bmonthly\b", re.I)
# Words that poison the whole sentence rather than the amount beside them: a look-behind
# cannot see a verb 200 characters away.
SPECULATIVE = re.compile(r"\bpro[- ]forma\b|\bpredict\w*|\bguidance\b|\bforecast\w*"
                         r"|\boutlook\b|\bprojection\w*|\bcould (?:reach|replace|hit)\b"
                         r"|\bwill (?:reach|hit|grow to)\b|\bby 20[3-9]\d\b"
                         r"|\btargeting\b|\bambition\b", re.I)
# The lettered codes need a left boundary or `Rs` matches inside "Registe(rs)" -- this
# repo's FORCE / "Air Force" bug. The symbols must not take one: they are not word chars.
# A currency this list does not know is worse than no currency at all: "increasing its
# turnover to TRY 2,4 billion (US$ 353 million)" produced "US$ 2,4 billion", because TRY
# was unrecognised so the amount looked bare and took the dollar from the parenthetical.
CCY = (r"(?:(?<![A-Za-z])(?:INR|Rs\.?|US\$|USD|EUR|GBP|SEK|NOK|DKK|CHF|AED|JPY|CAD|AUD"
       r"|TRY|TL|PLN|CZK|ILS|NIS|KRW|RUB|ZAR|BRL|SGD|TWD|CNY|RMB|HKD|NZD)"
       r"|₹|\$|€|£|¥|₺|₪|₩|₽)")
SCALE = r"(?:crore|cr\b|lakh|million|billion|trillion|bn\b|mn\b)"
MONEY = re.compile(r"(?:" + CCY + r"\s*[\d,]+(?:\.\d+)?\s*" + SCALE + r"?"
                   r"|[\d,]+(?:\.\d+)?\s*" + SCALE + r"\s*"
                   r"(?:" + CCY + r"|rupees|dollars|euros|kronor)?)", re.I)
CCY_RX = re.compile(CCY, re.I)
# The metric that owns an amount is the noun immediately before it.
NEAR_METRIC = re.compile(
    r"\b(order backlog|backlog|order book|order bookings?|order intake|ebitda|ebit|"
    r"operating (?:profit|income|result)|profit|net income|earnings|dividend|"
    r"market cap\w*|valuation|assets|equity|debt|capex|contract|deal|award|budget|"
    r"funding|cash flow|margin|percent|per cent|%"
    # Exports are a slice of revenue, and a company states them proudly next to it:
    # "Otokar exports amounted to US$307 Million, accounting for 75% of our annual
    # revenues" is not Otokar's revenue, and the revenue word sits right beside it.
    r"|exports?|export (?:revenues?|sales|turnover)|domestic sales"
    r"|arms revenues?|defen[cs]e revenues?)\b[^.;]{0,40}$", re.I)
QUALIFIER = re.compile(r"\b(exceed\w*|surpass\w*|more than|over|above|around|about|"
                       r"approximately|approx\.?|nearly|almost|up to|at least|estimated|"
                       r"target\w*|expect\w*|forecast|guidance|aims? for|plans? to|"
                       r"projected|goal of|pro forma|predicted|predicts|forecasts?|"
                       r"outlook)(?:\s+(?:of|at|to|for))?\s*$", re.I)
YEAR = re.compile(r"\b(?:FY\s?-?\s?20\d\d(?:\s?[-/]\s?\d{2,4})?"
                  r"|(?:fiscal|financial) year\s+(?:ended\s+)?(?:\d{1,2}\s+\w+\s+)?20\d\d"
                  r"|20\d\d\s?[-/]\s?\d{2}"
                  r"|(?:in|for|during|of|ended)\s+(?:the\s+year\s+)?20\d\d"
                  r"|20\d\d)\b", re.I)
Y4 = re.compile(r"(20\d\d)")
SAYS_ANNUAL = re.compile(r"\bannual(?:ised|ized)?\s+(?:revenues?|sales|turnover|income)"
                         r"|\b(?:revenues?|sales|turnover)\s+per\s+year"
                         r"|\byearly\s+(?:revenues?|sales|turnover)", re.I)


def year_of(period):
    """The comparable year in a period string; 0 when undated, so it sorts last.

    A straddling fiscal year ranks on the year it ENDS: "FY 2024-25" is 2025, and its
    trailing "25" is not a four-digit year, so it has to be reconstructed or every
    Indian FY sorts a year early against a calendar-year figure.
    """
    ys = [int(y) for y in Y4.findall(period or "")]
    tail = re.search(r"[-/]\s*(\d{2})\b", period or "")
    if ys and tail:
        cand = ys[0] // 100 * 100 + int(tail.group(1))
        if cand >= ys[0]:
            ys.append(cand)
    return max(ys) if ys else 0


def figures(obj, quote):
    """[(value, period)] -- the annual revenue figures this evidence states."""
    if NOT_ANNUAL.search(quote or "") or SPECULATIVE.search(quote or ""):
        return []
    out = []
    for text in (obj or "", quote or ""):
        if not REVENUE.search(text) or NOT_ANNUAL.search(text):
            continue
        if SPECULATIVE.search(text):
            continue
        years = [(m.start(), m.group(0).strip()) for m in YEAR.finditer(text)]
        line_ccy = CCY_RX.search(text)
        for mm in MONEY.finditer(text):
            amount = re.sub(r"\s+", " ", mm.group(0)).strip()
            if not re.search(r"\d", amount) or not re.search(SCALE, amount, re.I):
                continue                       # a revenue figure carries a unit
            before = text[:mm.start()]
            if NEAR_METRIC.search(before) or QUALIFIER.search(before):
                continue
            if re.match(r"\s*(?:%|per ?cent)", text[mm.end():]):
                continue
            if not CCY_RX.search(amount):
                if not line_ccy:
                    continue                   # nothing to denominate it with
                # ...and the currency must belong to the same family as the SCALE.
                # "annual turnover of USD 2.5 billion / 12,000 Crore" produced
                # "USD 12,000 Crore" for the client's own row: crore and lakh are
                # Indian units and pair with the rupee, never with a dollar or a euro.
                if re.search(r"crore|lakh", amount, re.I) and \
                        not re.search(r"INR|Rs|₹", line_ccy.group(0), re.I):
                    continue
                amount = "%s %s" % (line_ccy.group(0), amount)
            # each amount takes the period nearest it, not the sentence's first one
            period = (min(years, key=lambda pr: abs(pr[0] - mm.start()))[1]
                      if years else "")
            if period and year_of(period) > THIS_YEAR:
                continue                       # a year not yet reported is a target
            if not period and not SAYS_ANNUAL.search(text):
                continue
            # An undated figure is kept ONLY when the sentence calls it annual itself --
            # "Rafael ... with annual revenues of $2.9 billion" is a real figure that no
            # year appears beside, and requiring a year threw it away. The word `annual`
            # does the job the year was doing: it says this is not a quarter. It is
            # stored with an empty period, so the panel shows the amount without a year
            # rather than asserting one, and year_of("") == 0 puts it behind every dated
            # figure -- an undated figure is used only when nothing dated exists.
            out.append((amount, period))
        if out:
            break
    return out


def rank(rows):
    """Newest first; within a year the more precise figure wins, because the panel
    renders entry [0] -- a site states both 'EUR 1 billion' and 'EUR 1,086.7 million'."""
    return sorted(rows, key=lambda r: (year_of(r["detail"]),
                                       len(re.sub(r"\D", "", r["value"]))), reverse=True)


def collect(cur):
    """{comp_id: [row, ...]} -- every competitor's annual revenue figures, best first."""
    # THE CLIENT IS NOT ITS OWN COMPETITOR. serving.competitors carries the Kalyani
    # group with dir='client', and filling its revenue here put the client's own
    # turnover in a column the Competitor profile reads. Everything else in this
    # pipeline excludes it the same way.
    cur.execute("SELECT comp_id, name FROM serving.competitors "
                "WHERE name <> '' AND coalesce(dir, '') <> 'client'")
    comps = cur.fetchall()
    # The subject match must be WORD-BOUNDED. An `ilike '%'||name||'%'` join filed
    # Belaruskali's export revenue under BEL, which is the FORCE / "Air Force" bug at
    # the join rather than in a scorer.
    cur.execute("""SELECT p.subject, p.object, p.ev_quote, d.url
                     FROM extracted.proposition p
                     JOIN extracted.document d ON d.document_id = p.document_id
                    WHERE p.modality NOT IN ('planned', 'expected')
                      AND (p.predicate || ' ' || p.object) ~*
                          '(revenue|turnover|net sales|total income)'
                      AND (p.object ~ '[0-9]' OR p.ev_quote ~ '[0-9]')""")
    props = cur.fetchall()
    pats = [(cid, name, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I))
            for cid, name in comps if len(name) >= 3]
    folded = {fold_name(canon_name(n)): cid for cid, n in comps}
    out = {}
    for subject, obj, quote, url in props:
        subj = subject or ""
        hits = [cid for cid, _n, rx in pats if rx.search(subj)]
        if not hits:
            cid = folded.get(fold_name(canon_name(subj)))
            hits = [cid] if cid else []
        if not hits:
            continue
        for value, period in figures(obj, quote):
            row = {"value": value, "detail": period, "url": url,
                   "line": (quote or "")[:400]}
            for cid in hits:
                out.setdefault(cid, []).append(row)
    for cid in out:
        seen, uniq = set(), []
        for r in rank(out[cid]):
            key = (r["value"].lower(), r["detail"].lower())
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        out[cid] = uniq[:6]
    return out


# ---------------------------------------------------------------- the crawler fallback
#
# THE SECOND SOURCE, AND WHY IT IS NOT A STEP. The extraction layer holds 59,726 of the
# crawler's 1.85M documents, so a competitor can be absent from `extracted.proposition`
# and still be written about. `public.documents` on the crawler is the fallback -- the
# same corpus, one stage earlier, and the same rules applied to it.
#
# It is an operator mode rather than an enrich step because it costs a full sequential
# scan: there is no text index on 1.85M rows, so one pass takes about forty minutes and
# saturates a database this pipeline shares. Measured 2026-09-06: 7,031 documents match
# the revenue predicate, and across the 25 competitors the extraction cannot cover it
# yields exactly two -- Kalashnikov and Otokar. That ratio is the argument for running it
# by hand, occasionally, and not every two hours.
CRAWLER_SQL = """SELECT url, left(main_text, 40000) FROM public.documents
                  WHERE main_text ~* '(annual (revenue|turnover)|revenues? of'
                        '|turnover of|net sales of|posted revenues?'
                        '|reported revenues?|revenues? (?:stood|totall?ed|reached))'"""
SENTENCE = re.compile(r"[^.\n]{0,220}(?:revenue|turnover|net sales)[^.\n]{0,220}", re.I)


def collect_crawler(cur, names):
    """{name: [row]} for `names` -- [(comp_id, name)] the extraction could not cover."""
    src_dsn = os.environ.get("KSSL_CORPUS_SRC_DSN")
    if not src_dsn:
        print("crawler: KSSL_CORPUS_SRC_DSN unset -- skipping the fallback", flush=True)
        return {}
    import psycopg2
    pats = [(cid, n, re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)", re.I))
            for cid, n in names if len(n) >= 4]
    con = psycopg2.connect(src_dsn, connect_timeout=20)
    sc = con.cursor(name="revscan")            # server-side: never buffer 1.85M rows
    sc.itersize = 2000
    sc.execute(CRAWLER_SQL)
    out, n_docs = {}, 0
    for url, txt in sc:
        n_docs += 1
        t = txt or ""
        for cid, name, rx in pats:
            if not rx.search(t):
                continue
            for m in SENTENCE.finditer(t):
                line = re.sub(r"\s+", " ", m.group(0)).strip()
                if not rx.search(line):
                    continue
                for value, period in figures("", line):
                    out.setdefault(cid, []).append(
                        {"value": value, "detail": period, "url": url,
                         "line": line[:400]})
    print("crawler: scanned %d document(s), %d compan(ies) gained"
          % (n_docs, len(out)), flush=True)
    for cid in out:
        seen, uniq = set(), []
        for r in rank(out[cid]):
            key = (r["value"].lower(), r["detail"].lower())
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        out[cid] = uniq[:6]
    return out


def run(dsn=DSN, apply=False, crawler=False):
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=15) as con:
        with con.cursor() as cur:
            found = collect(cur)
            if crawler:
                cur.execute("SELECT comp_id, name FROM serving.competitors "
                            "WHERE coalesce(dir,'') <> 'client'")
                missing = [(cid, n) for cid, n in cur.fetchall() if cid not in found]
                print("crawler: %d competitor(s) the extraction cannot cover"
                      % len(missing), flush=True)
                for cid, rows in collect_crawler(cur, missing).items():
                    found[cid] = rows
            cur.execute("SELECT count(*) FROM serving.competitors")
            total = cur.fetchone()[0]
            print("revenue: %d of %d competitor(s) have an annual figure in the corpus"
                  % (len(found), total), flush=True)
            if not apply:
                print("dry run: nothing written (pass --apply)", flush=True)
                return {"companies": len(found), "total": total, "written": 0}
            # FAIL FAST IF A REBUILD IS MID-FLIGHT. step_companies deletes every
            # origin='pipeline' competitor and then sits idle-in-transaction for the
            # length of its profile calls, so an UPDATE here blocks rather than fails
            # and looks like a run that wrote nothing. Same reasoning, and the same
            # 30s, as fill_competitor_news.
            cur.execute("SET lock_timeout='30s'")
            n = 0
            for cid, rows in found.items():
                cur.execute("""UPDATE serving.competitors
                                  SET sales = %s::jsonb, updated_at = now()
                                WHERE comp_id = %s""",
                            (json.dumps(rows, ensure_ascii=False), cid))
                n += cur.rowcount
        con.commit()
    print("revenue: wrote %d row(s)" % n, flush=True)
    return {"companies": len(found), "total": total, "written": n}


def _demo():
    # Every string below is a real ev_quote from extracted.proposition.
    ok = figures("", "General Dynamics employs more than 120,000 people worldwide and "
                     "generated $52.6 billion in revenue in 2025.")
    assert ok and ok[0][0] == "$52.6 billion" and "2025" in ok[0][1], ok

    # SIPRI states arms AND total in one sentence; total is the company's revenue.
    got = figures("", "In 2024, Saab ranked number 28 in the SIPRI Top 100 and reported "
                      "arms revenues of US$5,550 million and total revenues of "
                      "US$6,030 million.")
    assert [g[0] for g in got] == ["US$6,030 million"], got

    # a quarter, written with a hyphen
    assert not figures("", "Lockheed Martin's net sales totalled $15bn in the "
                           "three-month period that ended on 27 March 2022."), "Q1"
    # guidance, a prediction, and a pro-forma merger figure are not results
    assert not figures("", "Lockheed Martin maintained its 2022 revenue guidance of "
                           "$65.25 billion despite supply chain headwinds.")
    assert not figures("EUR 15 billion in revenue in 2026",
                       "Papperger predicted that defence production could replace a "
                       "third of jobs, noting EUR 15 billion in revenue in 2026."), \
        "the evidence sentence governs, not the extracted fragment"
    assert not figures("", "Raytheon Technologies is one of the largest with "
                           "approximately $74 billion in pro forma 2019 net sales.")
    # a rate is not an amount
    assert not figures("", "Saab invests 17 percent of revenue in research and development.")
    # undated, and unit-less, cannot be "the latest annual revenue"
    assert not figures("", "Elbit Systems reported revenues of $2.3 billion.")
    # ...unless the sentence calls it annual ITSELF. Rafael's only figure in the whole
    # corpus is "annual revenues of $2.9 billion" with no year beside it; `annual` does
    # the job the year was doing, which is to say this is not a quarter.
    got = figures("", "Rafael Advanced Defense Systems is one of Israel's largest "
                      "defense companies with annual revenues of $2.9 billion.")
    assert got == [("$2.9 billion", "")], got
    assert year_of("") == 0, "and it ranks behind every dated figure"
    assert not figures("", "Annual revenues aside, it posted $1bn in the three-month "
                           "period."), "an annual WORD does not rescue a quarter"
    assert not figures("", "Lockheed Martin reported revenue of $400 in 2023.")
    # a future year is a target
    assert not figures("", "Kongsberg expects revenues of NOK 150 billion in 2033.")

    # A CURRENCY IS NOT PORTABLE ACROSS SCALE FAMILIES. The client's own row came out
    # as "USD 12,000 Crore" -- the line's dollar sign glued to an Indian scale.
    got = figures("", "The group has annual turnover of USD 2.5 billion and 12,000 "
                      "Crore in revenue in 2024.")
    assert [g[0] for g in got] == ["USD 2.5 billion"], got
    assert figures("", "Revenue for FY 2024-25 stood at Rs. 1,250 crore.")[0][0] \
        == "Rs. 1,250 crore", "the rupee still pairs with crore"

    # AN UNKNOWN CURRENCY IS WORSE THAN NO CURRENCY. Found by scanning the crawler
    # corpus: TRY was unrecognised, so "TRY 2,4 billion" looked bare and took the US$
    # from the conversion beside it, giving "US$ 2,4 billion" -- off by a factor of 7.
    got = figures("", "Otokar achieved record growth of 45% in 2019, increasing its "
                      "turnover to TRY 2,4 billion (US$ 353 million)")
    assert got[0][0] == "TRY 2,4 billion", got
    # Exports are a slice of revenue and are stated right beside it.
    assert not figures("", "In 2020, Otokar exports amounted to US$307 Million, "
                           "accounting for 75% of our annual revenues"), \
        "an export figure is not the company's revenue"

    assert year_of("In 2021") == 2021 and year_of("FY 2024-25") == 2025
    assert year_of("") == 0, "an undated figure sorts last"
    r = rank([{"value": "EUR 900 million", "detail": "in 2023"},
              {"value": "EUR 1,100 million", "detail": "in 2025"}])
    assert r[0]["value"] == "EUR 1,100 million", r
    print("fill_revenue demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--crawler", action="store_true",
                    help="also scan the crawler corpus for competitors the extraction "
                         "cannot cover (~40 min: a full sequential scan of 1.85M rows)")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(a.dsn, apply=a.apply, crawler=a.crawler)
