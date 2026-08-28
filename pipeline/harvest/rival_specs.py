"""Specifications for the rival products KSSL is actually compared against.

    python rival_specs.py --targets      # which rival products we need, and why
    python rival_specs.py --report
    python rival_specs.py --apply
    python rival_specs.py --demo

Positioning can only publish a comparison where BOTH sides carry sourced numbers, and the
audit put that at 9 rows of 204. KSSL's side is now read from its own export catalogue.
This is the other side.

WHAT IT DOES NOT DO
-------------------
It does not compare KSSL against whatever catalogue happened to be harvested. Nammo's
handbook, for instance, yielded 17 real products — and not one of them is comparable to
anything KSSL makes: Nammo sells ammunition and shoulder-fired weapons, KSSL sells guns,
vehicles and EMPTY shell bodies. Pairing them would be the same category error the
like-for-like gate exists to stop, just with better sourcing behind it.

So the target list is derived from the matchups themselves: the rival products already
paired with a KSSL product whose specifications we hold. That is a bounded list of real
competitors — M777, CAESAR, ATMOS 2000, K9 Thunder, PzH 2000, AK-203, Dhanush — rather
than whatever a crawl happened to reach.

WHERE THE NUMBERS COME FROM
---------------------------
The pages the harvest already brought back. A maker that publishes a product page
publishes its specification on that page, usually as `Label: value` or as a short
label followed by a measurement. Both shapes are read here, and a value is kept only when
it sits within a few lines of the product's own name — a page about the M777 also
mentions three other guns, and "39 calibre" three paragraphs below the M777 heading is
not necessarily the M777's.
"""
import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from targets import DSN                             # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A measurement: the thing that makes a line a specification rather than a sentence.
MEASURE = re.compile(
    r"^[<>~≤≥]?\s*[\d][\d\s.,/x×-]*\s*"
    r"(mm|cm|m|km|kg|t|tons?|tonnes?|km/h|kmph|mph|rpm|rds?|rounds?|hp|kw|ps|"
    r"cal|calibre|caliber|°|deg|%|litres?|l|sec|s|min|h|nm|kts?)?\b", re.I)
SPEC_WORD = re.compile(
    r"calibr|caliber|weight|length|width|height|range|rate of fire|barrel|magazine|"
    r"crew|speed|power|engine|protection|elevation|traverse|ammunition|payload|"
    r"endurance|operation|rifling|firing|mode|cartridge|armou?r|gradient|capacity|"
    r"suspension|transmission|wheelbase|gvw|mass|muzzle|velocity|charge|zone|"
    r"emplacement|deployment|towing|gross|kerb|combat", re.I)

COLON = re.compile(r"^(.{2,44}?)\s*[:–-]\s*(.{1,60})$")
PAIR = re.compile(r"^(.{2,44}?)\s{2,}(.{1,60})$")
NEAR_LINES = 14          # how far from the product's name a spec may sit


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def variants(product):
    """The ways a page might write this product's name.

    "G5 / G6 / T5-52" is three products in one matchup label; "155mm HE ERFB-BT" carries
    a calibre a page may write as "155 mm". Matching only the literal string finds
    almost nothing.
    """
    p = norm(product)
    out = {p}
    for part in re.split(r"\s*/\s*", p):
        part = part.strip()
        # "G5" and "G6" are real designations; two characters is allowed only when one
        # of them is a digit, so a stray "of" or "in" can never become a product name.
        if len(part) >= 3 or (len(part) == 2 and re.search(r"\d", part)):
            out.add(part)
    out.add(re.sub(r"(\d)\s*mm", r"\1 mm", p))
    out.add(re.sub(r"(\d)\s+mm", r"\1mm", p))
    # a bare designation: "M777" out of "M777 (India)"
    m = re.match(r"^([A-Za-z]*-?\d+[A-Za-z0-9-]*)", p)
    if m:
        out.add(m.group(1))
    return sorted({v for v in out
                   if len(v) >= 3 or (len(v) == 2 and re.search(r"\d", v))},
                  key=len, reverse=True)


def specs_near(text, product):
    """[(label, value, line)] stated within a few lines of this product's name."""
    lines = [norm(x) for x in (text or "").splitlines()]
    lines = [x for x in lines if x]
    hits = []
    names = variants(product)
    anchor_ix = [i for i, ln in enumerate(lines)
                 if any(v.lower() in ln.lower() for v in names)]
    if not anchor_ix:
        return []
    keep = set()
    for i in anchor_ix:
        keep.update(range(max(0, i - 2), min(len(lines), i + NEAR_LINES)))
    seen = set()
    for i in sorted(keep):
        ln = lines[i]
        m = COLON.match(ln) or PAIR.match(ln)
        if not m:
            continue
        label, value = norm(m.group(1)), norm(m.group(2))
        if not label or not value or len(label.split()) > 6:
            continue
        # BOTH halves have to behave: the label must name a field, and the value must be
        # a measurement. Either alone lets prose through - a sentence with a colon in it
        # is not a specification.
        if not SPEC_WORD.search(label):
            continue
        if not MEASURE.match(value):
            continue
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        hits.append((label, value, ln))
    return hits


def targets(cur):
    """[(cid, company, product, ksslProduct)] — rivals paired with a KSSL product we can
    already source. Anything else is not worth fetching: a comparison needs both sides."""
    cur.execute("""
        with ks as (select distinct split_part(value,' :: ',1) p from harvest.fact
                    where field='product_spec' and company='Kalyani Strategic Systems')
        select distinct m."compBy",
               split_part(m.comp,' · ',2) as rival_product,
               split_part(m.bf,' · ',2)  as kssl_product
        from serving.matchup m
        where m.origin='pipeline'
          and exists (select 1 from ks
                      where lower(replace(ks.p,' ','')) like '%%'||lower(replace(split_part(m.bf,' · ',2),' ',''))||'%%'
                         or lower(replace(split_part(m.bf,' · ',2),' ','')) like '%%'||lower(replace(ks.p,' ',''))||'%%')
        order by 1,2""")
    return cur.fetchall()


def fetch_product_pages(limit=None):
    """Go and get the data sheet for each needed rival product.

    The harvest brought back each maker's home page and its top-level category pages,
    which name products but do not specify them - Hanwha's landing page lists "K9
    Self-Propelled Howitzer" and gives not one number. A specification lives on the
    product's OWN page, one click further in, and nothing reaches it unless it is asked
    for by name.

    So: read the maker's stored pages for links whose href or anchor text carries the
    product's name, and fetch those. This is a targeted fetch of a known list, not a
    deeper crawl - 75 products, not another 10,000 URLs.
    """
    import psycopg2 as pg
    sys.path.insert(0, str(HERE))
    import fetch as F
    import targets as T

    with pg.connect(DSN, connect_timeout=15) as cx, cx.cursor() as cur:
        tg = targets(cur)
        cur.execute("""select p.cid, t.company, p.url, p.text, p.final_url
                       from harvest.page p join harvest.task t on t.task_id = p.task_id""")
        pages = cur.fetchall()

        # which maker each stored page belongs to
        by_maker = {}
        for cid, company, url, text, final in pages:
            by_maker.setdefault(re.sub(r"[^a-z0-9]+", "", (company or "").lower()), []).append(
                (cid, url, text))

        todo, seen_urls = [], set()
        for maker, product, kssl_product in tg:
            mk = re.sub(r"[^a-z0-9]+", "", maker.lower())
            owned = [v for k, v in by_maker.items()
                     if k and (k[:12] in mk or mk[:12] in k)]
            if not owned:
                continue
            names = [v.lower() for v in variants(product)]
            # the stored text has been stripped of markup, so re-fetch the maker page
            # and read ITS links - cheap, one page per maker, cached by the ladder
            for cid, url, _text in owned[0][:2]:
                pg_ = F.get(url)
                for link in _links(pg_.get("html") or "", pg_.get("final_url") or url):
                    if any(n in link.lower() for n in names) and link not in seen_urls:
                        seen_urls.add(link)
                        todo.append((cid, maker, product, kssl_product, link))
        if limit:
            todo = todo[:limit]
        print("product pages to fetch: %d" % len(todo))

        n = 0
        for cid, maker, product, kssl_product, link in todo:
            p_ = F.get(link)
            text = p_.get("text") or ""
            if p_.get("bytes"):
                try:
                    import io as _io
                    import pdfplumber
                    with pdfplumber.open(_io.BytesIO(p_["bytes"])) as pdf:
                        parts = [(pg2.extract_text() or "") for pg2 in pdf.pages[:40]]
                        text = chr(10).join(parts)
                except Exception:
                    text = ""
            hits = specs_near(text, product)
            for label, value, line in hits:
                cur.execute("""insert into harvest.fact
                    (cid, company, field, value, detail, url, line)
                    values (%s,%s,'rival_spec',%s,%s,%s,%s) on conflict do nothing""",
                            (cid, maker, "%s :: %s" % (product, label), value, link, line))
                n += cur.rowcount
            cx.commit()
            if hits:
                print("  %-26s %-24s %2d specs  %s" % (maker[:26], product[:24], len(hits), link[:50]))
        print("wrote %d rival spec values" % n)


_HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)


def _links(html, base):
    import urllib.parse
    out = []
    for m in _HREF.finditer(html or ""):
        h = m.group(1).strip()
        if h.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        out.append(urllib.parse.urljoin(base, h))
    return out


def run(apply_it):
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=15) as cx, cx.cursor() as cur:
        tg = targets(cur)
        print("rival products needed: %d (each already paired with a KSSL product we can source)"
              % len(tg))
        cur.execute("""select p.cid, t.company, p.need, p.url, p.text
                       from harvest.page p join harvest.task t on t.task_id = p.task_id""")
        pages = cur.fetchall()
        print("pages to search: %d" % len(pages))

        found = {}
        for maker, product, kssl_product in tg:
            mk = re.sub(r"[^a-z0-9]+", "", maker.lower())[:14]
            for cid, company, need, url, text in pages:
                if not company:
                    continue
                cm = re.sub(r"[^a-z0-9]+", "", company.lower())[:14]
                # only the maker's OWN pages: a rival's spec read off a third party's
                # blog is not the maker's published figure
                if not (mk and cm and (mk in cm or cm in mk)):
                    continue
                for label, value, line in specs_near(text, product):
                    found.setdefault((cid, maker, product), {}).setdefault(
                        label.lower(), (label, value, url, line, kssl_product))

        tot = sum(len(v) for v in found.values())
        print("\nrival products with sourced specs: %d   (%d spec values)"
              % (len(found), tot))
        for (cid, maker, product), fields in sorted(found.items()):
            print("  %-30s %-26s %d fields: %s"
                  % (maker[:30], product[:26], len(fields),
                     ", ".join(list(fields)[:5])))

        if not apply_it:
            print("\nREPORT ONLY — nothing written. Re-run with --apply")
            return found
        n = 0
        for (cid, maker, product), fields in found.items():
            for _, (label, value, url, line, _k) in fields.items():
                cur.execute("""insert into harvest.fact
                    (cid, company, field, value, detail, url, line)
                    values (%s,%s,'rival_spec',%s,%s,%s,%s) on conflict do nothing""",
                            (cid, maker, "%s :: %s" % (product, label), value, url, line))
                n += cur.rowcount
        cx.commit()
        print("\nwrote %d rival spec values" % n)
        return found


def demo():
    for rx in (MEASURE, SPEC_WORD, COLON, PAIR):
        assert not any(ord(c) < 32 for c in rx.pattern), rx.pattern[:50]

    assert "M777" in variants("M777 (India)")
    assert "G5" in variants("G5 / G6 / T5-52")
    assert "155 mm" in variants("155mm")

    page = ("The M777 lightweight howitzer\n"
            "Calibre: 155 mm\n"
            "Barrel length: 39 calibre\n"
            "Weight: 4 200 kg\n"
            "Maximum range: 24.7 km\n"
            "The gun is used by several armies and has seen service worldwide.\n")
    got = specs_near(page, "M777")
    d = {l.lower(): v for l, v, _ in got}
    assert d.get("calibre") == "155 mm", got
    assert d.get("weight") == "4 200 kg", got
    assert len(got) == 4, got

    # prose with a colon is not a specification
    assert not specs_near("The M777 story\nOur view: this gun changed artillery\n", "M777")
    # a spec far from the product's name does not belong to it
    far = "The M777 howitzer\n" + ("filler\n" * 30) + "Calibre: 105 mm\n"
    assert not specs_near(far, "M777"), specs_near(far, "M777")
    # a page that never names the product yields nothing
    assert not specs_near("Calibre: 155 mm\nWeight: 4200 kg\n", "M777")
    print("rival_specs demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--targets", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.fetch:
        fetch_product_pages(a.limit)
    elif a.targets:
        import psycopg2 as pg
        with pg.connect(DSN) as cx, cx.cursor() as cur:
            for maker, product, kssl in targets(cur):
                print("%-42s %-28s  vs KSSL %s" % (maker[:42], product[:28], kssl))
    else:
        run(a.apply)
