"""Read a manufacturer's OWN product catalogue — including the PDF nobody was reading.

    python fetch_brochures.py --site https://www.kssl.co.in/ --company "Kalyani Strategic Systems"
    python fetch_brochures.py --all          # every company in serving.competitors with a site
    python fetch_brochures.py --demo         # self-check, fetches nothing

WHY THIS EXISTS
---------------
check_official.py recorded the finding that started this: 98 official manufacturer pages
were fetched and NOT ONE returned a specification value. The conclusion drawn at the time
was that maker pages are marketing copy. That conclusion was wrong, and the cost of it was
that Positioning fell back on an archive whose numbers nobody could source.

kssl.co.in is the proof. The whole site is 11.5 KB — one splash page, no product pages at
all. Every product KSSL sells, with a full specification table for each, is in a single
linked PDF (`brochure/Export.pdf`, 48 pages). An HTML-only fetcher sees a company with no
products; the actual catalogue was one link away the entire time.

So this fetcher follows the PDFs, and reads their spec tables the way they are actually
laid out: not as ruled tables — pdfplumber's table finder returns nothing on these — but
as two text columns, labels left, values right, which is what a data sheet almost always
is. The column boundary is MEASURED per page from the words' own x-positions rather than
assumed, because it moves between pages and between makers.

WHAT IT GUARANTEES
------------------
Every spec value carries the URL, the page number and the VERBATIM line it was read from.
A value that cannot show its line is not written. That is the whole point: the numbers
this replaces could not, and several of them turned out to belong to a different weapon.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
OUT_DIR = HERE / "products"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_PDF = 60 * 1024 * 1024
PDF_HINT = re.compile(r"brochure|catalog|catalogue|datasheet|data-sheet|product|export|"
                      r"specification|spec[-_ ]?sheet|profile|portfolio", re.I)

# A page is a SPEC page when its lines split into two columns. These are the words that
# say so in a heading, used only to raise confidence, never as the sole test — plenty of
# real spec tables carry no heading at all.
SPEC_HDR = re.compile(r"specification|general specification|technical data|main features", re.I)

# Label-side vocabulary. Used to REJECT a two-column block that is actually a bulleted
# marketing spread (which also splits into two columns) rather than a data sheet.
SPEC_LABEL = re.compile(
    # English
    r"calibr|caliber|weight|length|width|height|range|rate of fire|barrel|magazine|"
    r"crew|speed|power|engine|protection|elevation|traverse|ammunition|payload|"
    r"endurance|operation|rifling|grooves|firing|mode|safety|cartridge|armour|armor|"
    r"gradient|capacity|suspension|transmission|wheelbase|gvw|mass|"
    # German / French / Spanish / Italian
    r"gewicht|länge|breite|höhe|reichweite|kaliber|besatzung|geschwindigkeit|"
    r"leistung|motor|schutz|munition|"
    r"poids|longueur|largeur|hauteur|portée|calibre|équipage|vitesse|puissance|"
    r"blindage|cadence|"
    r"peso|longitud|altura|alcance|tripulación|velocidad|potencia|"
    r"lunghezza|altezza|gittata|equipaggio|velocità|potenza|"
    # Nordic / Dutch / Polish / Turkish
    r"vikt|längd|räckvidd|hastighet|besattning|"
    r"gewicht|lengte|snelheid|"
    r"masa|długość|zasięg|prędkość|załoga|"
    r"ağırlık|uzunluk|menzil|hız|mürettebat|"
    # Cyrillic
    r"масса|длина|ширина|"
    r"высота|дальность|"
    r"калибр|экипаж|"
    r"скорость|боекомплект", re.I)

# STRUCTURE, not vocabulary. A data sheet's real signature is that its right-hand column
# is mostly numbers-with-units - which is true in every language. The vocabulary gate
# above is an accelerator; this is the fallback that stops the reader from being an
# English detector, which is what zeroed every non-English catalogue silently.
NUMERIC_VALUE = re.compile(
    r"^[<>~≤≥]?\s*[\d.,]+\s*"
    r"(mm|cm|m|km|kg|t|kn|kw|hp|ps|rpm|rd|s|h|km/h|mph|°|%|l|mt|"
    r"мм|см|кг|км)?\b", re.I)


def norm(s):
    """Fix the mojibake a PDF text layer produces, and collapse whitespace.

    The KSSL brochure encodes its bullet as U+F0B7 (a private-use glyph from Symbol) and
    its degree sign as a raw 0xB0 that pdfplumber hands back as a lone replacement char.
    Left as-is these end up in a spec VALUE — "Elevation : -5?to75?" — and then nothing
    downstream can compare them.
    """
    s = (s or "")
    s = s.replace("", "•").replace("�", "°")
    s = s.replace("–", "-").replace("—", "-")
    return " ".join(s.split()).strip()


# ── fetching ──────────────────────────────────────────────────────────────────
def http_get(url, timeout=45, binary=False):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(MAX_PDF + 1)
        if len(raw) > MAX_PDF:
            raise ValueError("over %d bytes" % MAX_PDF)
        if binary:
            return raw, r.headers.get("Content-Type", "")
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", r.headers.get("Content-Type", ""), re.I)
        if m:
            enc = m.group(1)
        return raw.decode(enc, "replace"), r.headers.get("Content-Type", "")


def links_on(html, base):
    out = []
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', html or "", re.I):
        href = m.group(1).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        out.append(urllib.parse.urljoin(base, href))
    return out


def discover(site, max_pages=25):
    """Same-host walk, breadth first, collecting HTML pages and every PDF they link to.

    Deliberately shallow. This is not a crawl of the web, it is a read of ONE catalogue:
    the PDF is nearly always linked from the homepage or one click in, and going deeper
    buys news articles and career pages.
    """
    host = urllib.parse.urlsplit(site).netloc.lower().lstrip("www.")
    seen, queue, pdfs, pages = set(), [site], [], []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            body, ctype = http_get(url)
        except Exception as e:
            print("    skip %s (%s)" % (url[:80], e))
            continue
        pages.append(url)
        for nxt in links_on(body, url):
            nl = nxt.lower().split("?")[0]
            nhost = urllib.parse.urlsplit(nxt).netloc.lower().lstrip("www.")
            if nl.endswith(".pdf"):
                # An off-host PDF is still the maker's own document when the LINK came
                # from the maker's page — brochures are routinely served from a CDN.
                if nxt not in pdfs:
                    pdfs.append(nxt)
            elif nhost == host and nxt not in seen and len(seen) < max_pages * 3:
                if not re.search(r"\.(jpg|jpeg|png|gif|svg|css|js|zip|mp4|webp)$", nl):
                    queue.append(nxt)
    # a brochure-shaped name first; an unhinted PDF is still tried, just later
    pdfs.sort(key=lambda u: (0 if PDF_HINT.search(u) else 1, len(u)))
    return pages, pdfs


# ── PDF spec-table reading ────────────────────────────────────────────────────
def page_lines(page):
    """Words grouped into visual lines, each line's words left-to-right."""
    try:
        words = page.extract_words(use_text_flow=False, extra_attrs=["size"])
    except Exception:
        return []
    rows = {}
    for w in words:
        rows.setdefault(round(w["top"] / 3.0), []).append(w)
    out = []
    for k in sorted(rows):
        out.append(sorted(rows[k], key=lambda w: w["x0"]))
    return out


def split_columns(lines):
    """Find the x where a data sheet's label column ends and its value column begins.

    Measured, not assumed. For every line, take the largest gap between consecutive
    words; the boundary is the most COMMON such gap position across the page. A real
    two-column table agrees with itself on many lines; a paragraph does not, and falls
    below the support floor below.
    """
    votes = {}
    for ws in lines:
        if len(ws) < 2:
            continue
        best, bx = 0, None
        for a, b in zip(ws, ws[1:]):
            gap = b["x0"] - a["x1"]
            if gap > best:
                best, bx = gap, b["x0"]
        if best >= 12 and bx is not None:
            votes[round(bx / 6.0) * 6] = votes.get(round(bx / 6.0) * 6, 0) + 1
    if not votes:
        return None
    bx, n = max(votes.items(), key=lambda kv: (kv[1], -kv[0]))
    # four agreeing lines is the floor: three can be a coincidence of a bulleted list
    return bx if n >= 4 else None


def variant_table(lines, bx):
    """True when the page is a multi-variant comparison, not a single data sheet."""
    if bx is None:
        return False
    multi = 0
    for ws in lines:
        right = [w for w in ws if w["x0"] >= bx]
        if len(right) < 2:
            continue
        gaps = sum(1 for a, b in zip(right, right[1:]) if b["x0"] - a["x1"] >= 14)
        if gaps >= 1:
            multi += 1
    return multi >= 4


COLON = re.compile(r"^(.{2,40}?)\s*[:]\s*(.{1,90})$")


def colon_specs(lines, already):
    """The OTHER way a brochure states a spec: "Elevation : -5deg to 75deg".

    The two-column reader finds a data sheet. It does not find the artillery pages, which
    are a bulleted marketing column on the left and colon-separated pairs on the right -
    and those pages are ATAGS, MArG, Bharat ULH, i.e. most of what KSSL is actually
    compared on. Without this, 190 of 219 matchups had no catalogue entry to correct them
    and kept their archived numbers.

    A colon line is only taken when the left side reads like a LABEL: short, and not a
    sentence. "The order is placed within a framework: see annexe" must not become a spec.
    """
    out = []
    for ws in lines:
        text = norm(" ".join(w["text"] for w in ws))
        if not text or text in already:
            continue
        m = COLON.match(text)
        if not m:
            continue
        label, value = norm(m.group(1)), norm(m.group(2))
        if not label or not value or len(label.split()) > 5:
            continue
        if label.startswith(("•", "-")) or value.endswith((".", "!")):
            continue
        out.append((label, value, text))
    return out


def specs_on_page(page):
    """(product_title, [(label, value, verbatim_line)]) for one PDF page."""
    lines = page_lines(page)
    if not lines:
        return None, []
    bx = split_columns(lines)
    pairs = []
    for ws in (lines if bx is not None else []):
        left = [w for w in ws if w["x0"] < bx]
        right = [w for w in ws if w["x0"] >= bx]
        if not left or not right:
            continue
        # The line must actually CROSS the boundary with a gap - some word ending before
        # bx and the next starting at or after it, with real space between. Without this
        # a line whose text merely runs through bx gets cut mid-phrase: "Engine 4 Stroke,
        # Water Cooled, 4" | "Cylinder" was published as an engine value of "Cylinder".
        if left[-1]["x1"] > bx - 2 or right[0]["x0"] - left[-1]["x1"] < 10:
            continue
        label = norm(" ".join(w["text"] for w in left))
        value = norm(" ".join(w["text"] for w in right))
        # A spec VALUE is a measurement or a short phrase, never a sentence. Nammo's
        # 2023 handbook is a two-column PROSE layout, and without this the splitter read
        # 748 "specs" out of it that were sentence fragments paired with other sentence
        # fragments ("and production capabilities." = "increased over the last 20
        # years."). 102 page numbers became 102 product names.
        if not label or not value or len(label) > 70 or len(value) > 60:
            continue
        if len(value.split()) > 6:
            continue
        # a label that ends a sentence is prose, not a field name
        if label.endswith((".", "!", "?")) and not re.search(r"\b[A-Z]\.$", label):
            continue
        # A label is a NAME, not a sentence. This is what keeps a two-column marketing
        # spread ("• Shoot and scoot capability | • Max speed 80kmph") out of the table.
        # A data-sheet label is a NAME. Five words is generous; beyond that the "label"
        # is the earlier columns of a variant table ("Protection Level STANAG III
        # STANAG II STANAG"), whose "value" is then the last fragment - "I".
        if len(label.split()) > 5:
            continue
        pairs.append((label, value, norm(label + " " + value)))
    if variant_table(lines, bx):
        # A three-column VARIANT table ("Kerb Weight | 14.5 Tons | 11 Tons | 10 Tons")
        # has no single value to read. Split as label/value it produces a label of
        # "Kerb Weight 14.5 Tons 11 Tons" and a value of "10 Tons" - the third variant's
        # figure published as the product's. Refuse the page rather than pick a column.
        return None, []
    pairs += colon_specs(lines, [p[2] for p in pairs])
    if len(pairs) < 3:
        return None, []
    # A data sheet has to look like one. Two ways to qualify, because only one of them
    # works outside English: named fields, OR a right-hand column that is mostly measured
    # values. A German or Korean datasheet has no English labels and every bit as many
    # numbers.
    named = sum(1 for p in pairs if SPEC_LABEL.search(p[0]))
    numeric = sum(1 for p in pairs if NUMERIC_VALUE.match(p[1]))
    # A DATA SHEET IS MOSTLY NUMBERS. The vocabulary test alone is not enough: prose
    # about "operational facilities" and "production capabilities" contains the words
    # `operation` and `production`, so a magazine spread passed the named gate and was
    # published as a spec table. Requiring a real share of measured values is what
    # separates a data sheet from a page that merely talks about equipment - and it does
    # so in any language, unlike the vocabulary.
    if numeric < max(3, int(len(pairs) * 0.35)):
        return None, []
    if named < 2 and numeric < max(4, len(pairs) // 2):
        return None, []

    # Product name: the largest text on the page. On a data sheet that is USUALLY the
    # product - but on a catalogue that prints a big page number, or a contents page, it
    # is not, and 44 Nammo data sheets came back named "116", "125", "136". So the
    # largest-font answer is CHECKED, and a bad one falls back to reading the top of the
    # page the way a person does: skip the section banner, take the next line or two.
    title = None
    try:
        words = page.extract_words(use_text_flow=False, extra_attrs=["size"])
        if words:
            top = max(w.get("size", 0) for w in words)
            big = [w for w in words if w.get("size", 0) >= top - 0.5]
            big.sort(key=lambda w: (round(w["top"] / 3.0), w["x0"]))
            title = norm(" ".join(w["text"] for w in big))[:80]
    except Exception:
        pass
    if not good_title(title):
        title = title_from_top(page) or title
    return title, pairs


GENERIC_TITLE = re.compile(r"^(contents?|index|introduction|overview|about|foreword|"
                           r"table of contents|appendix|glossary|notes?)$", re.I)


def good_title(t):
    """Is this a product name, or the furniture around one?"""
    t = (t or "").strip()
    if len(t) < 3 or len(t) > 70:
        return False
    if re.fullmatch(r"[\d\s.,:/-]+", t):        # a page number
        return False
    if GENERIC_TITLE.match(t):
        return False
    # The section banner is not a product. It may not START with the section word -
    # Nammo's reads "LARGE CALIBER AMMUNITION" - so this looks anywhere in an all-caps
    # line rather than only at the front.
    if section_of(t):
        return False
    if t.upper() == t and re.search(r"\b(%s)\b" % "|".join(SECTIONS), t, re.I):
        return False
    return bool(re.search(r"[A-Za-zÀ-ɏ]", t))


def title_from_top(page):
    """The name as a reader takes it: the first line or two under the section banner.

    Nammo's sheets read "LARGE CALIBER AMMUNITION / 120 mm / KE-TP" - the banner, the
    calibre, the designation. Joining the two lines after the banner gives "120 mm KE-TP",
    which is what the product is called.
    """
    raw = (page.extract_text() or "")
    lines = [norm(x) for x in raw.splitlines()]
    out = []
    for ln in lines[:6]:
        if not ln or section_of(ln) or re.fullmatch(r"[\d\s.,:/-]+", ln):
            continue
        if len(ln) > 60 or GENERIC_TITLE.match(ln):
            continue
        out.append(ln)
        if len(" ".join(out)) > 24 or len(out) == 2:
            break
    t = " ".join(out).strip()
    return t if good_title(t) else ""


SECTIONS = ("ARTILLERY", "PROTECTED VEHICLES", "COMBAT VEHICLES", "AMMUNITION",
            "SMALL ARMS", "UNMANNED", "MARINE", "ARMOURED VEHICLES", "ARMAMENTS",
            "NAVAL", "AEROSPACE")
SECTION = re.compile(r"^(%s)\b" % "|".join(SECTIONS), re.I)


def section_of(flat):
    """The catalogue section this page belongs to - including the ones set SIDEWAYS.

    A brochure prints its section tab rotated 90 degrees up the edge of the page, and a
    PDF text layer hands that back CHARACTER-REVERSED: page 30 of the KSSL catalogue
    reads "NOITINUMMA", page 32 reads "SMRA LLAMS". Read straight, neither matches
    anything, so every page from AMMUNITION onward inherited the last section that
    happened to be printed horizontally - which is how a 5.56 mm carbine came to be
    filed under Protected Vehicles, and would then have been paired against armoured
    cars.

    So each token is also tested reversed, and the token ORDER reversed with it
    ("SMRA LLAMS" -> "ARMS SMALL" -> "SMALL ARMS").
    """
    if not flat:
        return ""
    m = SECTION.match(flat)
    if m and len(flat) < 60:
        return m.group(1).upper()
    toks = [t for t in re.findall(r"[A-Za-z]{3,}", flat) if t.isupper()]
    if not toks:
        return ""
    rev = [t[::-1] for t in toks]
    for cand in (" ".join(rev), " ".join(reversed(rev))):
        m = SECTION.match(cand)
        if m:
            return m.group(1).upper()
    return ""


def read_pdf(raw, url):
    """Every product a catalogue documents, with the page and line behind each number."""
    import pdfplumber
    recs, section = [], ""
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, page in enumerate(pdf.pages):
            flat = norm(page.extract_text() or "")
            sec = section_of(flat)
            if sec:
                section = sec
            # a divider page is nothing BUT the section name; no product sits on it
            if sec and len(flat) <= 30:
                continue
            title, pairs = specs_on_page(page)
            if not pairs:
                continue
            recs.append({
                "product": title or "",
                "category": section,
                "specs": [{"label": l, "value": v, "line": q} for l, v, q in pairs],
                "source_url": url,
                "page": i + 1,
                "has_spec_header": bool(SPEC_HDR.search(flat)),
            })
    return merge_spreads(recs)


def merge_spreads(recs):
    """One product, one record.

    A catalogue gives a product a two-page spread: "Kalyani M4 / Additional Features" on
    the left, "Kalyani M4 / GENERAL SPECIFICATIONS" on the right. Both pages split into
    two columns, so both are read, and the product then appears twice carrying half its
    data sheet each - and a like-for-like comparison downstream would take whichever came
    first and silently drop the other half.
    """
    out, by = [], {}
    for r in recs:
        key = re.sub(r"[^a-z0-9]+", "", (r["product"] or "").lower())[:24]
        r["pages"] = [r["page"]]
        if key and key in by:
            tgt = by[key]
            seen = {(x["label"].lower(), x["value"].lower()) for x in tgt["specs"]}
            for x in r["specs"]:
                if (x["label"].lower(), x["value"].lower()) not in seen:
                    tgt["specs"].append(x)
            tgt["pages"] = sorted(set(tgt["pages"] + [r["page"]]))
            tgt["has_spec_header"] = tgt["has_spec_header"] or r["has_spec_header"]
            continue
        if key:
            by[key] = r
        out.append(r)
    return out


def company_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def run_site(site, company):
    print("== %s == %s" % (company, site))
    pages, pdfs = discover(site)
    print("   %d html pages, %d pdfs" % (len(pages), len(pdfs)))
    recs = []
    for u in pdfs[:6]:
        try:
            raw, ctype = http_get(u, timeout=120, binary=True)
        except Exception as e:
            print("   pdf skip %s (%s)" % (u[:80], e))
            continue
        if not raw.startswith(b"%PDF"):
            continue
        try:
            got = read_pdf(raw, u)
        except Exception as e:
            print("   pdf unreadable %s (%s)" % (u[:80], e))
            continue
        print("   %-58s %2d products" % (u.split("/")[-1][:58], len(got)))
        recs.extend(got)
    return {"company": company, "site": site, "html_pages": len(pages),
            "pdfs": pdfs[:6], "products": recs}


def demo():
    """Self-check with no network: the column splitter is the part that can silently
    turn a marketing spread into a spec table, so that is what is asserted."""
    class W(dict):
        pass

    def line(pairs):
        return [W({"text": t, "x0": x, "x1": x + len(t) * 5, "top": 0, "size": 9})
                for t, x in pairs]

    table = [line([("Calibre,", 77), ("mm", 107), ("5.56", 241)]),
             line([("Weight,", 77), ("kg", 110), ("3.3", 241)]),
             line([("Barrel", 77), ("Length,", 102), ("300", 241)]),
             line([("Range,", 77), ("m", 110), ("200-300", 241)]),
             line([("Rifling", 77), ("1", 241), ("in", 250)])]
    assert split_columns(table) == 240, split_columns(table)

    prose = [line([("The", 77), ("order", 95), ("is", 130), ("placed", 145)]),
             line([("within", 77), ("a", 110), ("framework", 120)])]
    assert split_columns(prose) is None, "prose must not read as two columns"

    # A regex written through a shell heredoc has had its \b turn into a literal 0x08
    # byte in this repo before: the pattern still COMPILES and simply never matches, and
    # every page then inherits the wrong section in silence. Cheap to assert, invisible
    # without the assert.
    for rx in (SECTION, SPEC_LABEL, SPEC_HDR, PDF_HINT, NUMERIC_VALUE, COLON):
        assert not any(ord(c) < 32 for c in rx.pattern), "control char in %r" % rx.pattern
    assert section_of("ARTILLERY") == "ARTILLERY"
    assert section_of("Medium & Large Caliber* NOITINUMMA Shells") == "AMMUNITION",         "rotated section tab must be read reversed"
    assert section_of("CQB Carbine ... SMRA LLAMS") == "SMALL ARMS"
    assert variant_table([[{"text": "Weight", "x0": 10, "x1": 40},
                           {"text": "14.5", "x0": 100, "x1": 120},
                           {"text": "11", "x0": 160, "x1": 175},
                           {"text": "10", "x0": 220, "x1": 235}]] * 4, 90)
    assert not variant_table([[{"text": "Weight", "x0": 10, "x1": 40},
                               {"text": "< 3.3 kg", "x0": 100, "x1": 140}]] * 4, 90)

    cs = colon_specs([[{"text": "Elevation", "x0": 10, "x1": 40},
                       {"text": ":", "x0": 42, "x1": 44},
                       {"text": "-5 to 75", "x0": 46, "x1": 90}]], [])
    assert cs and cs[0][0] == "Elevation" and cs[0][1] == "-5 to 75", cs
    assert not colon_specs([[{"text": w, "x0": i * 20, "x1": i * 20 + 15}
                             for i, w in enumerate(
                                 "The order is placed within this framework : see the annexe.".split())]], [])

    assert norm("Elevation -5�to75�") == "Elevation• -5°to75°"
    # the reader must not be an English detector: a German sheet has no English labels
    de = [("Gewicht", "23,5 t", "Gewicht 23,5 t"),
          ("Reichweite", "40 km", "Reichweite 40 km"),
          ("Kaliber", "155 mm", "Kaliber 155 mm")]
    assert sum(1 for p in de if SPEC_LABEL.search(p[0])) >= 2, "German labels must match"
    ko = [("구경", "155 mm", "x"), ("중량", "47 t", "y"),
          ("사거리", "40 km", "z"), ("속도", "67 km/h", "w")]
    assert sum(1 for p in ko if NUMERIC_VALUE.match(p[1])) >= 3,         "a Korean sheet must qualify on STRUCTURE when no label word matches"
    # a two-column PROSE page must never read as a data sheet
    prose_pairs = [("and production capabilities.", "increased over the last 20 years.", "x"),
                   ("operational facilities at", "sites ensure the highest standards of", "y"),
                   ("demilitarization experience with", "ammunition and explosive items. Our", "z"),
                   ("Nammo Sweden AB in Vingaker,", "safety and environmental consideration", "w")]
    assert sum(1 for p in prose_pairs if NUMERIC_VALUE.match(p[1])) == 0,         "prose values carry no measurements - that is the whole signal"
    assert not good_title("116") and not good_title("CONTENTS")
    assert not good_title("LARGE CALIBER AMMUNITION"), "the section banner is not a product"
    assert good_title("CQB Carbine") and good_title("120 mm KE-TP")
    print("demo ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site")
    ap.add_argument("--company")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        return demo()
    OUT_DIR.mkdir(exist_ok=True)
    targets = []
    if a.site:
        targets.append((a.company or urllib.parse.urlsplit(a.site).netloc, a.site))
    if a.all:
        import psycopg2 as pg
        dsn = os.environ.get("KSSL_DSN",
                             "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
        with pg.connect(dsn, connect_timeout=10) as cx, cx.cursor() as cur:
            cur.execute("select name, site from serving.competitors "
                        "where site is not null and site <> '' order by ord")
            targets.extend([(n, s) for n, s in cur.fetchall()])
    if not targets:
        print("nothing to do: pass --site or --all")
        return
    for company, site in targets:
        try:
            out = run_site(site, company)
        except Exception as e:
            print("!! %s failed: %s" % (company, e))
            continue
        p = OUT_DIR / ("%s.json" % company_slug(company))
        # NEVER replace a good catalogue with an empty one. A day when the site 403s
        # everywhere returns zero products, and an unconditional write then erases a
        # catalogue that was harvested successfully last week - the "partial run clobbers
        # full run" failure that once took a shared file from 10,548 rows to 0.
        if p.exists() and not out["products"]:
            try:
                prev = json.load(io.open(p, encoding="utf-8"))
            except Exception:
                prev = {}
            if prev.get("products"):
                print("   -> KEPT existing %s (%d products); this run read 0"
                      % (p.name, len(prev["products"])))
                continue
        json.dump(out, io.open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   -> %s (%d products)" % (p.name, len(out["products"])))


if __name__ == "__main__":
    main()
