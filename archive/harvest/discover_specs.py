"""Find a rival product's data sheet, then read its specification.

    python discover_specs.py --plan            # the target list and where each will be sought
    python discover_specs.py --run             # discover, fetch, extract
    python discover_specs.py --run --apply     # ...and write into harvest.fact
    python discover_specs.py --demo

WHY THIS EXISTS
---------------
Positioning publishes a spec row only when both products can show their number, and that
currently holds for 63 fields across 48 matchups. The limit is entirely the rival side:
the harvest reached each maker's home and category pages, which NAME products and specify
none of them. Hanwha's landing page says "K9 Self-Propelled Howitzer" and gives not one
figure.

Guessing product URLs does not work — direct attempts at BAE/M777, Elbit/ATMOS,
Hanwha/K9 and KNDS/CAESAR returned 404s and landing pages. A data sheet has to be
FOUND, not predicted.

THREE WAYS IN, CHEAPEST FIRST
-----------------------------
1. `sitemap.xml`  — the maker's own index of its pages. This is the highest-signal source
   there is: no crawling, no guessing, and the URL slugs carry product names. Only Elbit,
   KNDS and AWEIL actually publish one; BAE answers with an Incapsula interstitial, and
   Hanwha, Denel and Yugoimport answer 200 with their homepage.
2. A shallow crawl of the site's product sections, matching the product name in the page's
   own TEXT rather than in its URL — "K9 Thunder" is almost never in a path.
3. The PDF a product page links to. Makers put the actual numbers in a datasheet PDF far
   more often than in HTML.

Fetching goes through the C1/C3/C4 ladder, so a Cloudflare-fronted maker is reachable.

WHAT IS WRITTEN
---------------
Nothing that cannot show its line. A spec is kept only when its label names a field, its
value is a measurement, and it sits within a few lines of the product's own name on the
page — the same rule `rival_specs.specs_near` applies, because a page about the M777 also
mentions three other guns.
"""
import argparse
import os
import re
import statistics
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import fetch as F                                    # noqa: E402
import fetch_brochures as FB                         # noqa: E402
from rival_specs import specs_near, variants         # noqa: E402
from targets import DSN                              # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The artillery competitors to KSSL's flagship line — ATAGS, MArG 39-BR/45/52, the
# Mounted Gun System, Bharat ULH and Garuda 105 — because that is where KSSL actually
# competes and where its own catalogue gives us a full KSSL side to compare against.
TARGETS = [
    ("BAE Systems", "M777", "https://www.baesystems.com"),
    ("BAE Systems Bofors", "Archer", "https://www.baesystems.com"),
    ("Elbit Systems", "ATMOS 2000", "https://elbitsystems.com"),
    ("Elbit Systems", "ATHOS 2052", "https://elbitsystems.com"),
    ("Hanwha Aerospace", "K9 Thunder", "https://www.hanwhaaerospace.com"),
    ("Denel", "G5", "https://www.denel.co.za"),
    ("Denel", "T5-52", "https://www.denel.co.za"),
    ("KNDS", "CAESAR", "https://www.knds.com"),
    ("KNDS", "PzH 2000", "https://www.knds.com"),
    ("KNDS", "RCH-155", "https://www.knds.com"),
    ("Yugoimport SDPR", "Nora B-52", "https://www.yugoimport.com"),
    ("Advanced Weapons and Equipment India Limited", "Dhanush", "https://www.aweil.in"),
]

# URL segments that are worth opening when hunting a data sheet, and ones that never are.
GOOD_SEG = re.compile(r"product|solution|capabilit|platform|system|artillery|howitzer|"
                      r"gun|weapon|land|defence|defense|portfolio|equipment", re.I)
BAD_SEG = re.compile(r"/news|/press|/blog|/career|/job|/investor|/privacy|/cookie|"
                     r"/contact|/search|/login|/sitemap|/tag/|/category/|/author/|"
                     r"\.(jpg|jpeg|png|gif|svg|css|js|zip|mp4|webp)$", re.I)

# A page about a trainer, a simulator or a firing bench for a gun is not the gun. KNDS
# publishes four such pages per product and they scored identically to the weapon itself,
# so the hunt opened the CAESAR dashboard trainer first and read its prose.
ACCESSORY = re.compile(r"train|simulat|bench|dashboard|e-?learn|spare|"
                       r"support-equipment|mock-?up", re.I)

LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
HREF_PDF = re.compile(r"""href\s*=\s*["']([^"']+\.pdf[^"']*)["']""", re.I)
# A PDF URL does not have to be in an href — see pdf_links.
ANY_PDF = re.compile(r"""["'(]\s*((?:https?://|/)[^"'()<>\s]+\.pdf)""", re.I)

for _rx in (GOOD_SEG, BAD_SEG, ACCESSORY, LOC, HREF_PDF, ANY_PDF):
    assert not any(ord(c) < 32 for c in _rx.pattern), _rx.pattern[:40]


def sitemap_urls(site, depth=0, seen=None):
    """Every page URL a maker's sitemap declares, following sitemap indexes once."""
    seen = seen if seen is not None else set()
    out = []
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
        url = site.rstrip("/") + path
        if url in seen:
            continue
        seen.add(url)
        # The solver is allowed here. BAE answers /sitemap.xml with an Incapsula
        # interstitial at the cheap tier, and refusing to escalate for the one request
        # that indexes the entire site costs us every product behind it.
        p = F.get(url)
        body = p.get("html") or p.get("text") or ""
        locs = LOC.findall(body)
        if not locs:
            # A 200 is not a sitemap. Hanwha, Denel and Yugoimport all answer this path
            # with their homepage — an <html> with no <loc> anywhere in it. "This site
            # publishes no sitemap" and "we were blocked" are different problems with
            # different fixes, and must not be reported as the same zero.
            continue
        # a sitemap INDEX points at more sitemaps; follow those once, not forever
        subs = [u for u in locs if u.lower().endswith(".xml")]
        pages = [u for u in locs if not u.lower().endswith(".xml")]
        out.extend(pages)
        if depth < 1:
            for s in subs[:12]:
                if s in seen:
                    continue
                seen.add(s)
                q = F.get(s, allow_solver=False)
                b = q.get("html") or q.get("text") or ""
                out.extend([u for u in LOC.findall(b) if not u.lower().endswith(".xml")])
        if out:
            break
    return out


def head_token(product):
    """The part of a name a maker actually puts in a URL.

    Makers drop the model year. Elbit's own page for "ATMOS 2000" is
    /land/weapons-systems-and-munitions/howitzer-systems/atmos, and requiring the full
    designation scored that page zero — as it did the five news stories about it — so the
    company reported "candidates=0" with its data sheet sitting in the sitemap.
    """
    parts = [x for x in re.split(r"[^A-Za-z0-9-]+", product or "") if x]
    return parts[0].lower() if parts else ""


def segments(url):
    """The URL's path split the way a slug is written, for whole-token matching.

    Substring matching on a short designation is dangerous — "g5" appears inside plenty
    of ordinary words — so a bare family name has to match a whole segment or nothing.
    """
    path = re.sub(r"^[a-z]+://[^/]+", "", (url or "").lower())
    return [x for x in re.split(r"[^a-z0-9]+", path) if x]


def score(url, product):
    """How likely this URL is to be the product's own page. Higher is better, 0 = skip."""
    if BAD_SEG.search(url):
        return 0
    u = url.lower()
    s = 0
    for v in variants(product):
        v = v.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", v).strip("-")
        if slug and slug in re.sub(r"[^a-z0-9]+", "-", u):
            s += 10 + len(slug)          # the product's full name is in the path
        elif v.replace(" ", "") in u.replace("-", "").replace("_", ""):
            s += 6
    if not s:
        # the family name alone, as a WHOLE segment: /howitzer-systems/atmos
        h = head_token(product)
        if len(h) >= 2 and h in segments(url):
            s += 8
    if s and GOOD_SEG.search(u):
        s += 3
    if u.endswith(".pdf"):
        s += 4                            # a datasheet PDF beats a marketing page
    if s and ACCESSORY.search(u):
        s -= 12                           # a trainer for the gun is not the gun
    return max(s, 0)


def candidates(site, product, cap=6):
    """The URLs worth opening for this product, best first."""
    urls = sitemap_urls(site)
    scored = [(score(u, product), u) for u in urls]
    scored = [(s, u) for s, u in scored if s > 0]
    scored.sort(reverse=True)
    return [u for _, u in scored[:cap]], len(urls)


def pdf_links(html, base):
    """Every PDF this page points at, however the page points at it.

    KNDS renders "Download the data sheet" as a React <button>: the URL is not in an href
    at all, it sits in the component's serialised props in escaped form. Looking only at
    href found ZERO PDF links on a page whose entire specification lives in one.
    """
    html = html or ""
    flat = html.replace("\\/", "/").replace('\\"', '"')
    out, seen = [], set()
    for rx in (HREF_PDF, ANY_PDF):
        for m in rx.finditer(flat):
            u = urllib.parse.urljoin(base, m.group(1))
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def mentions(text, product):
    """True when this page is actually about the product, not merely near it."""
    low = (text or "").lower()
    names = [v.lower() for v in variants(product)]
    h = head_token(product)
    if len(h) >= 3:
        names.append(h)
    for name in names:
        # Whole word only. A plain substring test let "caesarean section" count as a
        # page about the CAESAR howitzer -- and a designation like "G5" is a substring
        # of far more ordinary text than that.
        if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low):
            return True
    return False


COLON_PAIR = re.compile(r"^(.{2,40}?)\s*:\s*(.{1,60})$")
JUNK_LABEL = re.compile(r"www[.]|https?:|^[-•*]", re.I)


def clean_pairs(pairs):
    """Drop the pairs a two-column split gets wrong on a THREE-block data sheet.

    KNDS's CAESAR sheet is not two columns, it is several blocks side by side, and each
    block already reads "Label: value". The splitter then pairs one block's complete
    entry with the NEXT block's value: "Height: 3.6m" = "1min40s" -- the into-action
    time published as the height.

    The tell is in the label. A label that already contains its own colon is a complete
    pair that has been mis-paired, so it is re-read on its own and the foreign value
    dropped; a value that ENDS in a colon is the next block's label, not a value.
    """
    out = []
    for label, value, line in pairs:
        label, value = label.strip(), value.strip()
        if JUNK_LABEL.search(label):
            continue
        if value.endswith(":"):
            # the "value" is the next block's field NAME, and its real value is elsewhere
            continue
        m = COLON_PAIR.match(label)
        if m:
            # a complete pair wrongly married to a neighbouring block's value
            label, value = m.group(1).strip(), m.group(2).strip()
            line = label + ": " + value
        if not re.search(r"[0-9]", value):
            # A comparison needs a measurement. "Mission: fully automatic laying" is
            # true and unusable -- it cannot be set against a KSSL figure.
            continue
        if not label or len(label.split()) > 6:
            continue
        out.append((label, value, line))
    return out


def line_pairs(lines):
    """Split each line at its own widest gap, for data sheets with narrow columns.

    fetch_brochures votes a single label/value boundary for the whole page and needs a
    12pt gap to believe in one. Elbit's ATMOS sheet sets its table with ~9pt between
    label and value, so no line cleared the floor and the vote went instead to the
    vertical sidebar lettering -- boundary 156, which cut "Firing Rate 6-7" in half. The
    page held eight perfectly formed specs and produced none.

    Splitting per line needs no page-wide agreement. What keeps prose out is that the
    gap must be clearly the widest on its line, and that the PAGE must yield several
    clean pairs before any of them count.
    """
    out = []
    for ws in lines:
        if len(ws) < 3:
            continue
        gaps = [(b["x0"] - a["x1"], i) for i, (a, b) in enumerate(zip(ws, ws[1:]))]
        best, bi = max(gaps)
        others = [g for g, _ in gaps if g != best] or [0]
        med = statistics.median(others)
        # distinctive, not merely present: a word space is ~2pt and every line has many
        if best < 4.0 or best < max(med * 2.2, 3.0):
            continue
        label = " ".join(w["text"] for w in ws[:bi + 1])
        value = " ".join(w["text"] for w in ws[bi + 1:])
        out.append((label, value, label + " " + value))
    return out


# A page has to look like a table before any of its rows are believed. Elbit's "key
# features" spread yields two rows that survive every per-row gate ("Tailored
# configuration A" = "Compatible with any 6x6 or") purely because "6x6" has a digit in
# it. Its spec page yields six. The difference is the only reliable signal on the page.
MIN_ROWS_PER_PAGE = 4


def pdf_specs(page, product):
    """Specs from a datasheet PDF, read as COLUMNS rather than as flowed text.

    pdfplumber's extract_text flows a two-column data sheet into single lines, and the
    result is not merely noisy, it is WRONG. KNDS's CAESAR sheet produced
    "Road speed: More than" = "3.7m" — the HEIGHT value labelled as road speed — and
    "Height: 3.1m - Min: 4,5km", which is two unrelated fields in one row. Four of
    eleven rows were wrong, and they would have been published as the rival's side of a
    comparison against KSSL's own catalogue figures.

    fetch_brochures already measures the column boundary from word geometry and refuses
    a multi-variant comparison table, so this uses that reader rather than a second one
    that would have to learn the same lessons again.
    """
    import io as _io
    try:
        import pdfplumber
    except ImportError:
        return []
    out = []
    try:
        with pdfplumber.open(_io.BytesIO(page["bytes"])) as pdf:
            pages = pdf.pages[:30]
            # A DATA SHEET NAMES ITS PRODUCT ON THE COVER, NOT ON EVERY PAGE. Elbit's
            # ATMOS sheet says ATMOS on pages 1, 2 and 6 and never on page 5 -- which is
            # the page with the specifications on it. Gating page by page threw away the
            # only page worth having. So: if the front of the document is about this
            # product, the document is about this product.
            front = " ".join((pg.extract_text() or "") for pg in pages[:2])
            doc_about = mentions(front, product)
            for pg in pages:
                lines = FB.page_lines(pg)
                _title, pairs = FB.specs_on_page(pg)
                rows = clean_pairs(pairs)
                if len(rows) < MIN_ROWS_PER_PAGE:
                    # the page-wide boundary vote found nothing usable; try per line
                    rows = clean_pairs(line_pairs(lines))
                if len(rows) < MIN_ROWS_PER_PAGE:
                    continue
                if not doc_about and not mentions(pg.extract_text() or "", product):
                    continue
                out.extend(rows)
    except Exception:
        return []
    return out


def specs_from(page, product):
    """Specs from whatever this fetch returned — a PDF by geometry, HTML by proximity."""
    if page.get("bytes"):
        return pdf_specs(page, product)
    return specs_near(text_of(page), product)


def text_of(page):
    """Page text, reading a PDF as a PDF."""
    if page.get("bytes"):
        try:
            import io as _io
            import pdfplumber
            with pdfplumber.open(_io.BytesIO(page["bytes"])) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages[:30])
        except Exception:
            return ""
    return page.get("text") or ""


def hunt(maker, product, site, verbose=True):
    """[(label, value, line, url)] for one rival product."""
    urls, n_sitemap = candidates(site, product)
    if verbose:
        print("  %-28s %-14s sitemap=%-5d candidates=%d"
              % (maker[:28], product[:14], n_sitemap, len(urls)))
    found, seen_fields = [], set()
    for u in urls:
        p = F.get(u)
        hits = specs_from(p, product)
        # a product page that specifies nothing usually LINKS to the sheet that does
        if not hits and p.get("html"):
            # This page has ALREADY been identified as the product's own. Demanding the
            # product's name in the PDF's FILENAME as well threw away the exact document
            # we came for whenever a maker names its sheet by part code.
            for pdf in pdf_links(p["html"], u)[:3]:
                if ACCESSORY.search(pdf):
                    continue
                q = F.get(pdf)
                hits = specs_from(q, product)
                if hits:
                    u = pdf
                    break
        for label, value, line in hits:
            k = label.lower()
            if k in seen_fields:
                continue
            seen_fields.add(k)
            found.append((label, value, line, u))
        if len(found) >= 8:
            break
    if verbose and found:
        print("       -> %d specs: %s" % (len(found), ", ".join(f[0][:18] for f in found[:5])))
    return found


def run(apply_it):
    import psycopg2 as pg
    total = 0
    results = {}
    for maker, product, site in TARGETS:
        try:
            got = hunt(maker, product, site)
        except Exception as e:
            print("  %-28s %-14s FAILED %s" % (maker[:28], product[:14], type(e).__name__))
            continue
        if got:
            results[(maker, product)] = got
            total += len(got)
    print("\nrival products specified: %d of %d   (%d spec values)"
          % (len(results), len(TARGETS), total))
    if not apply_it:
        print("REPORT ONLY — nothing written. Re-run with --apply")
        return results
    with pg.connect(DSN, connect_timeout=15) as cx, cx.cursor() as cur:
        n = 0
        for (maker, product), rows in results.items():
            for label, value, line, url in rows:
                cur.execute("""insert into harvest.fact
                    (cid, company, field, value, detail, url, line)
                    values (%s,%s,'rival_spec',%s,%s,%s,%s) on conflict do nothing""",
                            (re.sub(r"[^A-Za-z0-9]+", "", maker)[:24], maker,
                             "%s :: %s" % (product, label), value, url, line))
                n += cur.rowcount
        cx.commit()
    print("wrote %d rival spec values" % n)
    return results


def demo():
    # the product's own name in the path is the strongest signal there is
    assert score("https://x.com/products/m777-howitzer", "M777") > \
           score("https://x.com/products/artillery", "M777")
    # news and press pages are never a data sheet
    assert score("https://x.com/news/2024/m777-order", "M777") == 0
    # a datasheet PDF outranks the equivalent HTML page
    assert score("https://x.com/products/m777.pdf", "M777") > \
           score("https://x.com/products/m777", "M777")
    # a page with nothing to do with the product scores nothing
    assert score("https://x.com/about/leadership", "M777") == 0

    # the family name alone, as a whole segment, is how makers actually write it
    assert score("https://elbitsystems.com/land/howitzer-systems/atmos", "ATMOS 2000") > 0
    # ...but only as a WHOLE segment, never as a substring of a longer word
    assert score("https://x.com/products/stratosphere", "ATMOS 2000") == 0
    # a trainer FOR the gun ranks below the gun
    assert score("https://knds.com/en/products/systems/caesar-6x6", "CAESAR") > \
           score("https://knds.com/en/products/training-and-simulation/CAESAR-firing-bench",
                 "CAESAR")

    assert pdf_links('<a href="/docs/m777.pdf">sheet</a>', "https://x.com") == \
        ["https://x.com/docs/m777.pdf"]
    # a URL escaped inside serialised component props is still a URL
    props = r'{\"text\":\"Download the data sheet\",\"url\":\"https:\/\/knds.com\/media\/CAESAR_6X6.pdf\"}'
    assert "https://knds.com/media/CAESAR_6X6.pdf" in pdf_links(props, "https://knds.com")
    # a page must NAME the product, not merely sit in the same brochure
    assert mentions("The CAESAR 6x6 fires 155mm", "CAESAR")
    assert mentions("ATMOS is a truck-mounted howitzer", "ATMOS 2000")
    assert not mentions("The PULS rocket launcher", "CAESAR")
    # ...and a family name must be a whole word, never a fragment of another
    assert not mentions("caesarean section", "CAESAR")

    # a complete pair married to a neighbour block's value is re-read, not published
    assert clean_pairs([("Height: 3.6m", "1min40s", "x")]) ==         [("Height", "3.6m", "Height: 3.6m")]
    # a "value" that is really the next block's field name is dropped
    assert clean_pairs([("Features", "Slope:", "x")]) == []
    # a value with no measurement in it cannot be compared against anything
    assert clean_pairs([("Mission", "Fully automatic laying", "x")]) == []
    # a URL is not a field name
    assert clean_pairs([("www.knds.com Air transport", "A400M", "x")]) == []
    # a clean pair survives untouched
    assert clean_pairs([("Rate of fire", "6 rounds per minute", "L")]) ==         [("Rate of fire", "6 rounds per minute", "L")]

    # a line splits at its own widest gap, and a word space is not a gap
    ws = lambda *xs: [{"text": t, "x0": a, "x1": b} for t, a, b in xs]
    assert line_pairs([ws(("Firing", 0, 30), ("Rate", 32, 60), ("6-7", 150, 175),
                          ("rounds", 177, 210))]) ==         [("Firing Rate", "6-7 rounds", "Firing Rate 6-7 rounds")]
    # an evenly spaced line is prose, not a row
    assert line_pairs([ws(("the", 0, 20), ("gun", 22, 42), ("was", 44, 64),
                          ("fired", 66, 90))]) == []

    print("discover_specs demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.plan:
        for maker, product, site in TARGETS:
            print("%-44s %-14s %s" % (maker[:44], product[:14], site))
    else:
        run(a.apply)
