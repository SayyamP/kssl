"""Checks for the source policy: Wikipedia and its mirrors are never evidence."""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from source_policy import filter_sources, is_blocked, sole_source_blocked  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("  %s %-54s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


# --- blocked -------------------------------------------------------------
for u in ("https://en.wikipedia.org/wiki/M1_Abrams",
          "http://EN.WIKIPEDIA.ORG/wiki/M1_Abrams",
          "https://simple.wikipedia.org/wiki/Tank",
          "https://m.wikipedia.org/wiki/Tank",
          "https://de.wikipedia.org/wiki/Leopard_2",
          "https://www.wikipedia.org/",
          "https://wikipedia.org/wiki/X",
          "https://commons.wikimedia.org/wiki/File:X.jpg",
          "https://www.wikidata.org/wiki/Q1",
          "https://www.wikiwand.com/en/M1_Abrams",
          "https://dbpedia.org/page/M1_Abrams"):
    check("blocked: %s" % u[:44], is_blocked(u), True)

# --- allowed -------------------------------------------------------------
for u in ("https://www.army-technology.com/projects/g6/",
          "https://asdnews.com/news/defense/2026/07/13/x",
          "https://www.janes.com/osint-insights/defence-news/x",
          "https://www.ashokleyland.com/in/defence/x/specification",
          # a real host that merely CONTAINS the word
          "https://wikipedia-mirror-review.example.com/a",
          "https://notwikipedia.org/a",
          "https://mywikipedia.org.uk/a"):
    check("allowed: %s" % u[:44], is_blocked(u), False)

check("empty url", is_blocked(""), False)
check("None url", is_blocked(None), False)
check("not a url", is_blocked("just some text"), False)
# userinfo must not be able to smuggle a host past the check
check("userinfo trick", is_blocked("https://en.wikipedia.org@evil.example.com/x"), False)
check("port is ignored", is_blocked("https://en.wikipedia.org:443/wiki/X"), True)

# --- filtering -----------------------------------------------------------
check("filter drops blocked, keeps order",
      filter_sources(["https://en.wikipedia.org/wiki/A",
                      "https://www.army-technology.com/b",
                      "https://en.wikipedia.org/wiki/C",
                      "https://janes.com/d"]),
      ["https://www.army-technology.com/b", "https://janes.com/d"])
check("filter de-duplicates",
      filter_sources(["https://janes.com/d", "https://janes.com/d"]),
      ["https://janes.com/d"])
check("filter on empty", filter_sources([]), [])
check("filter on None", filter_sources(None), [])

# --- the rule that matters: drop the VALUE, not just the link ------------
check("sole source blocked -> value must be dropped",
      sole_source_blocked(["https://en.wikipedia.org/wiki/M1_Abrams"]), True)
check("mixed sources -> value survives",
      sole_source_blocked(["https://en.wikipedia.org/wiki/M1_Abrams",
                           "https://www.army-technology.com/x"]), False)
check("no sources at all -> not a blocked-source case",
      sole_source_blocked([]), False)

print()
print("all source-policy checks passed" if not fails else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
