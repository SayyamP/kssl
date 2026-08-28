"""What each pillar and tab needs, turned into a work queue.

    python targets.py --plan          # what would be fetched, and for whom
    python targets.py --build         # write the queue into harvest.task
    python targets.py --demo

The dashboard has three pillars and eleven tabs, and they do NOT need the same things.
Writing that down is the point of this file: a crawl aimed at "defence news" fills the
signal feeds and leaves Company Profile exactly as empty as it was, which is what has
happened up to now.

  PILLAR / TAB              what it renders from            where that lives
  ------------------------  ------------------------------  ----------------------------
  Competitive / Profile     products, news, partners,       the MAKER'S OWN SITE, plus
                            presence, patents, dev,         its brochure PDFs
                            leadership, facilities, sales
  Competitive / Positioning specs on BOTH sides             maker data sheets (PDF)
  Competitive / Partnership partner ties                    maker "partners" pages + news
  Competitive / Geo         country presence                maker "global"/"locations"
  Market / Report           tenders                          portals (separate harvest)
  Technology / Innovation   programmes in development       maker "R&D"/"innovation"

So the unit of work here is (company, need, url), and the needs are ordered so that
Profile — the operator's stated first target — is fetched first.

DISCOVERY, NOT GUESSING
-----------------------
Candidate URLs come from the site's OWN links wherever possible. A guessed path
("/leadership") is tried only after the real link graph has been read and only when the
graph offered nothing for that need, because a guessed URL that 404s is cheap but a
guessed URL that 200s onto the wrong page is a wrong fact.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")

# need -> (priority, link-text/href words that mean "this page serves that need")
# Priority 1 is fetched before priority 2 across the WHOLE fleet, so Profile fills first
# even while other needs are queued.
NEEDS = {
    "products":   (1, r"product|solution|portfolio|capabilit|platform|catalog|range|"
                      r"what we (do|make)|offering"),
    "brochure":   (1, r"brochure|catalog|download|datasheet|data-sheet|literature|media kit"),
    "leadership": (1, r"leadership|management|board|directors|our team|governance|"
                      r"executive|who we are"),
    "facilities": (1, r"facilit|plant|manufactur|infrastructur|location|where we|"
                      r"our sites|works|campus"),
    "about":      (1, r"about|company|profile|overview|corporate|heritage|history"),
    "sales":      (2, r"investor|financial|annual report|results|shareholder|"
                      r"quarterly|performance"),
    "partners":   (2, r"partner|alliance|collabor|joint venture|supplier|ecosystem"),
    "presence":   (2, r"global|worldwide|international|export|presence|market"),
    "innovation": (2, r"innovation|research|r&d|technolog|development|future"),
    "news":       (3, r"news|press|media|newsroom|announce|insight|blog|stories"),
}
NEED_RX = {k: re.compile(v, re.I) for k, (_, v) in NEEDS.items()}

# Tried only when the link graph gave nothing for a need. Ordered by how often they are
# actually the real path on a corporate site.
GUESS = {
    "products": ("/products", "/products/", "/solutions", "/capabilities", "/portfolio"),
    "leadership": ("/leadership", "/management", "/about/leadership", "/team",
                   "/board-of-directors"),
    "facilities": ("/facilities", "/manufacturing", "/infrastructure", "/locations"),
    "about": ("/about", "/about-us", "/company", "/who-we-are"),
    "sales": ("/investors", "/investor-relations", "/financials"),
    "partners": ("/partners", "/partnerships", "/alliances"),
    "presence": ("/global-presence", "/global", "/worldwide"),
    "innovation": ("/innovation", "/research", "/r-and-d", "/technology"),
    "news": ("/news", "/media", "/press", "/newsroom", "/press-releases"),
}

SKIP = re.compile(r"\.(jpg|jpeg|png|gif|svg|css|js|zip|mp4|webm|webp|ico|woff2?)$"
                  r"|/(login|signin|cart|privacy|cookie|terms|sitemap\.xml)", re.I)


def host_of(u):
    try:
        return urllib.parse.urlsplit(u).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def companies():
    """Every competitor, with whatever site we hold. A company with NO site is still
    returned — finding its site is itself a task, and dropping it here is how 23 of 58
    companies stayed invisible."""
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        cur.execute("select comp_id, name, site, "
                    "coalesce(jsonb_array_length(products),0), "
                    "coalesce(jsonb_array_length(partners),0) "
                    "from serving.competitors order by ord")
        return [{"cid": r[0], "name": r[1], "site": (r[2] or "").strip(),
                 "n_products": r[3], "n_partners": r[4]} for r in cur.fetchall()]


def classify(href, text):
    """Which needs a link serves. A link can serve more than one — "Products & Solutions"
    under a "Download brochure" heading is both — and forcing a single label here loses
    one of them."""
    blob = "%s %s" % (href or "", text or "")
    if href and href.lower().split("?")[0].endswith(".pdf"):
        return ["brochure"]
    return [need for need, rx in NEED_RX.items() if rx.search(blob)]


LINK = re.compile(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def links_for_needs(html, base):
    """{need: [url, …]} from a page's own link graph."""
    out = {}
    seen = set()
    host = host_of(base)
    for m in LINK.finditer(html or ""):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", " ", m.group(2) or "")
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urllib.parse.urljoin(base, href)
        if SKIP.search(url.split("?")[0]):
            continue
        # a PDF may legitimately live on a CDN; an HTML page must stay on the maker's own
        # host, or "partners" walks onto the partner's website and reports their facts
        is_pdf = url.lower().split("?")[0].endswith(".pdf")
        if not is_pdf and host_of(url) != host:
            continue
        if url in seen:
            continue
        seen.add(url)
        for need in classify(href, text):
            out.setdefault(need, [])
            if url not in out[need]:
                out[need].append(url)
    return out


def plan_for(company, html=None):
    """[(priority, need, url, how)] for one company."""
    site = company["site"]
    tasks = []
    if not site:
        tasks.append((0, "site", "", "discover"))
        return tasks
    tasks.append((0, "home", site, "seed"))
    found = links_for_needs(html, site) if html else {}
    for need, (prio, _) in sorted(NEEDS.items(), key=lambda kv: kv[1][0]):
        urls = found.get(need) or []
        if urls:
            for u in urls[:4]:
                tasks.append((prio, need, u, "link"))
        else:
            for path in GUESS.get(need, ())[:3]:
                tasks.append((prio, need, urllib.parse.urljoin(site, path), "guess"))
    return tasks


DDL = """
create schema if not exists harvest;
create table if not exists harvest.task (
  task_id    bigserial primary key,
  cid        text not null,
  company    text not null,
  need       text not null,
  url        text not null,
  how        text not null,
  priority   int  not null,
  state      text not null default 'pending',   -- pending|running|done|failed|blocked
  worker     text,
  via        text,
  status     int,
  chars      int,
  reason     text,
  started_at timestamptz,
  ended_at   timestamptz,
  unique (cid, need, url)
);
create index if not exists task_state_idx on harvest.task (state, priority, task_id);

create table if not exists harvest.page (
  page_id    bigserial primary key,
  task_id    bigint references harvest.task(task_id),
  cid        text not null,
  need       text not null,
  url        text not null,
  final_url  text,
  via        text,
  status     int,
  text       text,
  fetched_at timestamptz not null default now()
);
create index if not exists page_cid_idx on harvest.page (cid, need);

create table if not exists harvest.fact (
  fact_id    bigserial primary key,
  cid        text not null,
  company    text not null,
  field      text not null,          -- leadership|facility|product|sales|partner|presence
  value      text not null,
  detail     text,
  url        text not null,          -- where it was read
  line       text not null,          -- the VERBATIM line it was read from
  confidence text not null default 'sourced',
  created_at timestamptz not null default now(),
  unique (cid, field, value)
);
create index if not exists fact_cid_idx on harvest.fact (cid, field);
"""


def build(limit_companies=None):
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx:
        with cx.cursor() as cur:
            cur.execute(DDL)
        cx.commit()
        rows = companies()
        if limit_companies:
            rows = rows[:limit_companies]
        n = 0
        with cx.cursor() as cur:
            for c in rows:
                # SEEDS ONLY. plan_for() with no HTML falls back to guessed paths for
                # every need, which is 28 speculative fetches per company and ~980 for
                # the fleet. The worker expands a `home` task from the site's OWN link
                # graph instead, and guesses only for the needs that graph did not cover.
                for prio, need, url, how in plan_for(c):
                    if need not in ("home", "site"):
                        continue
                    if not url:
                        continue
                    cur.execute(
                        "insert into harvest.task (cid, company, need, url, how, priority) "
                        "values (%s,%s,%s,%s,%s,%s) on conflict do nothing",
                        (c["cid"], c["name"], need, url, how, prio))
                    n += 1
        cx.commit()
        with cx.cursor() as cur:
            cur.execute("select count(*), count(distinct cid) from harvest.task")
            tot, ncid = cur.fetchone()
    print("queued %d task rows -> harvest.task now holds %d tasks over %d companies"
          % (n, tot, ncid))


def demo():
    html = ('<a href="/products/artillery">Our Products</a>'
            '<a href="/about/leadership">Leadership Team</a>'
            '<a href="https://cdn.example.com/x/Brochure.pdf">Download brochure</a>'
            '<a href="https://othersite.com/partners">Partner site</a>'
            '<a href="/news/2026/x">Newsroom</a>'
            '<a href="/style.css">css</a>')
    got = links_for_needs(html, "https://maker.example.com/")
    assert "https://maker.example.com/products/artillery" in got["products"], got
    assert "https://maker.example.com/about/leadership" in got["leadership"], got
    # a PDF is allowed off-host (CDN); an HTML page is not
    assert got["brochure"] == ["https://cdn.example.com/x/Brochure.pdf"], got
    assert all("othersite.com" not in u for us in got.values() for u in us), got
    assert "css" not in json.dumps(got)
    # a link can serve two needs at once
    both = classify("/about/company-profile", "About the company")
    assert "about" in both
    # a company with no site produces a discovery task, not silence
    assert plan_for({"site": ""})[0][1] == "site"
    # guesses only appear where the link graph was silent
    tasks = plan_for({"site": "https://maker.example.com/"}, html)
    prods = [t for t in tasks if t[1] == "products"]
    assert all(t[3] == "link" for t in prods), prods
    facs = [t for t in tasks if t[1] == "facilities"]
    assert facs and all(t[3] == "guess" for t in facs), facs
    print("targets demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.build:
        build(a.limit)
    else:
        cs = companies()
        print("%d companies, %d with a site, %d without"
              % (len(cs), sum(1 for c in cs if c["site"]),
                 sum(1 for c in cs if not c["site"])))
        for c in cs[:a.limit or 8]:
            t = plan_for(c)
            print("  %-32s %-38s %d seed tasks" % (c["name"][:32], c["site"][:38], len(t)))
