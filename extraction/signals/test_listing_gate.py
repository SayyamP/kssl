"""Checks for the listing gate: is_listing + is_index_title.

    python extraction/signals/test_listing_gate.py

A FALSE POSITIVE here is the expensive direction. A listing that slips through
produces one bad card; a rejected publisher produces silence, and the gate runs
before the model so nothing is logged per document. The audit found 528
article-shaped pages being rejected because `\\bnewsroom\\b` matched anywhere in
the title -- HII titles every press release "... | HII Newsroom", so the entire
source was invisible.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Load just the two gate functions: serving_fill pulls in httpx and psycopg2.
src = (HERE / "serving_fill.py").read_text(encoding="utf-8")
ns = {"re": re}
for start, end in (("def is_listing(url):", "\n\n\n"),
                   ("_INDEX_PHRASE = re.compile", "\n\n\n"),
                   ("def is_index_title(title):", "\n\n\n")):
    i = src.index(start)
    j = src.index(end, i)
    exec(compile(src[i:j], "serving_fill.py", "exec"), ns)            # noqa: S102
is_listing, is_index_title = ns["is_listing"], ns["is_index_title"]

fails = []


def check(name, got, want):
    ok = got == want
    print("  %s %-58s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


# --- must be REJECTED (real listings from the corpus) --------------------
for u in ("https://asdnews.com/company/104104/hanwha-aerospace-europe",
          "http://www.asdnews.com/company/104128/thales-alenia-space",
          "https://asdnews.com/company/51955/general-dynamics-land-systems-(gdls)",
          "https://defence-industry.eu/tag/rheinmetall",
          "https://example.com/category/defence",
          "https://example.com/news",
          "https://roketsan.com.tr/urunler",
          "https://example.fr/actualites",
          "https://example.de/nachrichten",
          "https://example.com/news.aspx",
          "https://example.com/archive",
          "https://example.com/listing?page=4",
          "https://example.com/x?p=4",
          "https://brahmos.com/brahmos-in-media?page=3"):
    check("listing: %s" % u[:48], is_listing(u), True)

# --- must be KEPT (real articles the gate was wrongly eating) ------------
for u in ("https://saab.com/newsroom/press-releases/2026/saab-receives-order",
          "https://www.armyrecognition.com/archives/archives-land-defense/"
          "land-defense-2012/syria-army-security-forces-operation",
          "https://www.pixxel.space/blogs/the-hyperspectral-advantage?9446d79a_page=11",
          "https://asdnews.com/news/defense/2026/07/13/ai-battle-lab",
          "https://www.analisidifesa.it/2023/01/thales-alenia-space-contratto",
          "https://breakingdefense.com/2026/06/rheinmetall-vantor-plan-joint-isr/"):
    check("article: %s" % u[:48], is_listing(u), False)

# --- is_index_title ------------------------------------------------------
# The phrase IS the title (or its leading segment) -> a listing.
for t in ("Hanwha Aerospace Europe News & Press Releases | ASDNews",
          "News &amp; Press Releases | ASDNews",
          "Newsroom",
          "Newsroom | MBDA",
          "Latest News | SSTL",
          "Media Centre - Rohde & Schwarz",
          "Press Room | Example"):
    check("index title: %s" % t[:46], is_index_title(t), True)

# The phrase is a SUFFIX naming the site -> a real article. Each of these is a
# document in the corpus that was being silently dropped.
for t in ("HII is Awarded Contracts for Construction of Block VI Virginia-class "
          "Submarines | HII Newsroom",
          "The Government of Canada orders 4 new Airbus aircraft | Airbus Newsroom",
          "Renato Magalhaes joins SSTL | Latest News | SSTL",
          "Saab Receives Order for GlobalEye | Newsroom | Saab",
          "New radar unveiled - Media Center - Rohde & Schwarz",
          "Rheinmetall wins Bundeswehr contract for Elefant 2 transporters"):
    check("article title: %s" % t[:46], is_index_title(t), False)

check("empty title", is_index_title(""), False)
check("None title", is_index_title(None), False)

print()
print("all listing-gate checks passed" if not fails else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
