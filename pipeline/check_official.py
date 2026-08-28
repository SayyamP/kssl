"""Did the official manufacturer pages actually land any specifications?

    python check_official.py

Positioning is meant to prefer the maker's own page as a source, and after
fetching 98 of them not one spec value came back official-tier. Either the pages
are marketing copy with no numbers, or the product is named differently there
than in our matchups. This says which.
"""
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from source_tiers import tier                      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CAL = re.compile(r"\b(15[25]|120|105|76|30|12\.7)\s?mm", re.I)
SPECWORD = re.compile(r"calibre|caliber|range|weight|crew|rate of fire|payload|"
                      r"elevation|traverse|horsepower|kw\b", re.I)


def main():
    docs = []
    for p in (Path(__file__).parent / "corpus").glob("doc_*.json"):
        try:
            docs.append(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    off = [d for d in docs if tier(d.get("url", "")) == "official"]
    print("staged documents      : %d" % len(docs))
    print("on an official domain : %d" % len(off))

    with_cal = [d for d in off if CAL.search(d.get("text", ""))]
    with_word = [d for d in off if SPECWORD.search(d.get("text", ""))]
    print("  ...carrying a calibre figure     : %d" % len(with_cal))
    print("  ...carrying any spec vocabulary  : %d" % len(with_word))
    print("  median length                    : %d chars"
          % sorted(len(d.get("text", "")) for d in off)[len(off) // 2] if off else 0)

    print("\nofficial pages that DO carry a calibre:")
    for d in with_cal[:12]:
        m = CAL.search(d["text"])
        ctx = " ".join(d["text"][max(0, m.start() - 60):m.start() + 40].split())
        print("  %-22s %-42s ...%s..." % (d["source_id"][:22], (d["title"] or "")[:42], ctx))

    print("\nofficial pages with NO spec vocabulary at all (marketing only):")
    for d in [x for x in off if not SPECWORD.search(x.get("text", ""))][:8]:
        print("  %-22s %-46s %d chars"
              % (d["source_id"][:22], (d["title"] or "")[:46], len(d.get("text", ""))))


if __name__ == "__main__":
    main()
