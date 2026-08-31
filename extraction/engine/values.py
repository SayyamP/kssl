"""Deterministic value spans: money, measurement, date, percent, count, duration, identifiers.

These are the spans an LLM is worst at and a regex is best at, and they are a large share of what a
defence article actually asserts. On the external benchmark the regex generator alone covered 75% of
measurements (the LLM pass covered 0), 78% of dates and 61% of all value spans, with exact offsets.

Three bugs are baked into the patterns because each one silently destroyed a whole category:

1. **`\\b` after a non-word unit character.** `㎜` (U+339C) is Unicode category So, not a word
   character, so `250㎜\\b` fails whenever the next character is also non-word. That dropped EVERY
   CJK-unit measurement. The guard is `(?![A-Za-zÀ-ÿ])`, never `\\b`.
2. **A 4-digit year inside a designation.** `VPAM VR9/BRV2009` was typed `date` because the year
   pattern matched `2009` inside an alphanumeric token. Every numeric pattern starts
   `(?<![A-Za-z0-9])`.
3. **Currency words TRAIL the magnitude in most languages.** `27,3 milliards d'euros`,
   `216 000 millones de dólares`, `2.5 миллиардов долларов`, `3 milioni di euro` were all typed
   `count` because the pattern assumed a leading symbol. Spanish `millones` never matched
   `million[es]?` either. Money went 62% -> 92% when both directions were handled.
"""
import re
import sys

# Bounded on purpose: an unbounded thousands-group star plus \d+ are O(n) per start; with ~8
# unit-tailed patterns sharing this token a long separator-joined digit run is O(n^2) (80KB->267s,
# one core pinned). Real quantities never exceed ~6 groups / ~18 digits; the bounds make it O(1).
_NUM = r"(?<![A-Za-z0-9])\d{1,3}(?:[  ,. ']\d{3}){0,6}(?:[.,]\d+)?|(?<![A-Za-z0-9])\d{1,18}(?:[.,]\d+)?"

# Magnitude words, all languages we see. Spanish "millones" and Russian "миллиардов" do not match
# an English-shaped pattern, which is exactly how they became Counts.
_MAG = (r"(?:mill[oó]n(?:es)?|"          # es: "millones" never matched an English-shaped pattern
        r"million(?:s|es)?|milliard(?:s)?|billion(?:s|es)?|trillion(?:s)?|"
        r"milione|milioni|miliardo|miliardi|mil|mln|mrd|bn|m|k|"
        r"миллион(?:а|ов)?|миллиард(?:а|ов)?|тысяч(?:и|а)?|"
        r"Millionen|Milliarden|Tausend|mille|mila|lakh|crore)")
_CUR_SYM = r"[$€£¥₹₽¢]"
_CUR_WORD = (r"(?:USD|EUR|GBP|INR|RUB|JPY|CHF|CAD|AUD|SEK|NOK|DKK|PLN|CZK|"
             r"dollars?|dólares|dollari|Dollar|euros?|euro|Euro|евро|долларов|доллара|"
             r"pounds?|sterling|rupees?|rupias|roubles?|rubles?|рублей|рубля|"
             r"francs?|Franken|kroner|kronor|złotych|yen|yuan)")

PATTERNS = [
    # money -- symbol leads, or currency word trails (with optional magnitude between)
    ("money", rf"{_CUR_SYM}\s?(?:{_NUM})(?:\s?{_MAG})?(?:\s?{_CUR_WORD})?(?![A-Za-zÀ-ÿ])"),
    ("money", rf"(?:{_NUM})\s?(?:{_MAG}\s?)?(?:d[’']|de\s|di\s|of\s)?{_CUR_WORD}(?![A-Za-zÀ-ÿ])"),
    ("money", rf"{_CUR_WORD}\s?(?:{_NUM})(?:\s?{_MAG})?(?![A-Za-zÀ-ÿ])"),
    # percent
    ("percent", rf"(?:{_NUM})\s?(?:%|percent|per\s?cent|Prozent|pour\s?cent|por\s?ciento|процент\w*)"
                r"(?![A-Za-zÀ-ÿ])"),
    # measurement -- the unit list is deliberately long; the (?!letter) guard is the load-bearing part
    ("measurement", rf"(?:{_NUM})\s?(?:mm|cm|dm|m|km|ft|yd|mi|nmi|"
                    r"mg|g|kg|t|lb|lbs|oz|tonnes?|tons?|Tonnen|тонн\w*|"
                    r"ml|l|L|gal|m²|m2|m³|m3|km²|km2|ha|"
                    r"kg/m|km/h|kmh|mph|kt|kts|knots?|m/s|rpm|RPM|"
                    r"W|kW|MW|GW|kWh|MWh|V|kV|A|mA|Hz|kHz|MHz|GHz|"
                    r"°|°C|°F|K|bar|psi|Pa|kPa|MPa|N|kN|Nm|hp|HP|PS|CV|ch|"
                    r"㎜|㎝|㎞|㎏|㌧|㎡|㎥|dB|cal|kcal|"
                    r"rounds?/min|rds/min|shots?/min)(?![A-Za-zÀ-ÿ])"),
    # calibre / designation-shaped measurements: 5.56x45mm, 155mm/52, 9x19
    ("measurement", r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?\s?[x×]\s?\d+(?:[.,]\d+)?\s?"
                    r"(?:mm|cm|in)?(?![A-Za-zÀ-ÿ])"),
    ("measurement", r"(?<![A-Za-z0-9])\d+\s?mm\s?/\s?\d+(?![A-Za-zÀ-ÿ])"),
    # dates -- ISO, D Month Y, Month D Y, and bare years
    ("date", r"(?<![A-Za-z0-9])\d{4}-\d{2}-\d{2}(?![A-Za-z0-9])"),
    ("date", r"(?<![A-Za-z0-9])\d{1,2}[./]\d{1,2}[./]\d{2,4}(?![A-Za-z0-9])"),
    ("date", r"(?<![A-Za-z0-9])\d{1,2}(?:st|nd|rd|th|er|ème|\.)?\s+"
             r"(?:January|February|March|April|May|June|July|August|September|October|November|"
             r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
             r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|"
             r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|"
             r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|"
             r"novembre|dicembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
             r"octubre|noviembre|diciembre|январ\w+|феврал\w+|март\w*|апрел\w+|мая|июн\w+|июл\w+|"
             r"август\w*|сентябр\w+|октябр\w+|ноябр\w+|декабр\w+)"
             r"(?:\s+\d{4})?(?![A-Za-zÀ-ÿ])"),
    ("date", r"(?:January|February|March|April|May|June|July|August|September|October|November|"
             r"December|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|"
             r"novembre|décembre|Januar|Februar|März|Mai|Juni|Juli|Oktober|Dezember)"
             r"\s+\d{1,2},?\s+\d{4}(?![A-Za-z0-9])"),
    ("date", r"(?<![A-Za-z0-9/-])(?:19|20)\d{2}(?![A-Za-z0-9/-])"),
    # `in` is BOTH a unit and the commonest English preposition. Inside the shared unit list it
    # matched "2019 in Utrecht" and "DSEI 2025 in London", typing a year as 2019 INCHES -- and
    # because measurement outranks date there, the year was then suppressed as an overlap. So it
    # gets its own pattern, capped at three digits so no year can reach it, placed AFTER the date
    # patterns so a date always wins the overlap.
    ("measurement", r"(?<![A-Za-z0-9])\d{1,3}(?:[.,]\d+)?\s?in(?![A-Za-z\u00c0-\u00ff])"),
    ("duration", rf"(?:{_NUM})\s?(?:years?|months?|weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|"
                 r"secs?|Jahre?n?|Monate?n?|Tage?n?|Stunden?|ans?|années?|mois|jours?|heures?|"
                 r"anni|mesi|giorni|ore|лет|года?|месяц\w*|дн\w+|час\w*)(?![A-Za-zÀ-ÿ])"),
    # identifiers -- part numbers, designations, standards. These are almost never found by an LLM.
    ("identifier", r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[-\s]?\d{1,5}[A-Z]?|[A-Z]\d{2,}[A-Z]?)"
                   r"(?:/[A-Z0-9-]+)*(?![a-z])"),
    ("identifier", r"\b(?:ISO|EN|DIN|MIL-STD|MIL|STANAG|NATO|CE|IP|VPAM|BRV|NIJ)[\s-]?"
                   r"[0-9]{2,}(?:[-:][0-9A-Za-z]+)*"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    ("url", r"https?://[^\s<>\"')]+|www\.[^\s<>\"')]+"),
    ("phone", r"(?<![\d-])\+\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,5}\d{2,4}(?![\d-])"),
    # counts -- LAST, so anything typed above wins. A bare number is still a fact worth storing.
    ("count", rf"(?:{_NUM})(?:\s?{_MAG})?(?![A-Za-zÀ-ÿ])"),
]
_COMPILED = [(t, re.compile(p)) for t, p in PATTERNS]


def find(text):
    """-> [{start, end, text, type, source}] with earlier patterns winning any overlap.

    Order is the priority: money before percent before measurement before date before count, so
    "$4.5 million" is one money span and not a count plus a magnitude word.
    """
    taken, out = [], []
    for typ, rx in _COMPILED:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            if not m.group(0).strip():
                continue
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            out.append({"start": s, "end": e, "text": text[s:e], "type": typ, "source": "regex"})
    return sorted(out, key=lambda x: x["start"])


def _demo():
    def types(t):
        return {(d["text"], d["type"]) for d in find(t)}

    # money in four languages -- all of these were emitted as Count before the trailing-word fix
    assert ("$4.5 million", "money") in types("a deal worth $4.5 million today")
    assert any(x[1] == "money" and "27,3" in x[0] for x in types("27,3 milliards d'euros")), \
        types("27,3 milliards d'euros")
    assert any(x[1] == "money" for x in types("216 000 millones de dólares"))
    assert any(x[1] == "money" for x in types("2.5 миллиардов долларов"))
    assert any(x[1] == "money" for x in types("3 milioni di euro"))
    assert any(x[1] == "money" for x in types("€1.2 billion"))
    # the CJK-unit bug: a `\b` guard drops this entirely
    assert ("250㎜", "measurement") in types("bore of 250㎜, confirmed")
    assert ("155mm", "measurement") in types("a 155mm howitzer")
    assert any(x[1] == "measurement" for x in types("5.56x45mm cartridge"))
    assert any(x[1] == "measurement" for x in types("140 km/h burst speed"))
    # the year-inside-a-designation bug
    assert ("2009", "date") not in types("VPAM VR9/BRV2009 rating")
    assert ("2026", "date") in types("signed in 2026 by both")
    assert any(x[1] == "date" for x in types("on 12 March 2026 the deal closed"))
    assert any(x[1] == "date" for x in types("am 3. Februar 2025 unterzeichnet"))
    # percent / duration / contact
    assert ("50%", "percent") in types("50% of the fleet")
    assert any(x[1] == "duration" for x in types("over 7 years of service"))
    assert any(x[1] == "email" for x in types("write to bids@example.com now"))
    assert any(x[1] == "url" for x in types("see https://example.com/x for detail"))
    # a bare number still becomes a count rather than vanishing
    assert any(x[1] == "count" for x in types("delivered 307 units"))
    # offsets must be exact -- the dashboard highlights by substring
    t = "The 155mm gun cost $4.5 million in 2026."
    for d in find(t):
        assert t[d["start"]:d["end"]] == d["text"], d
    # overlaps must not double-count: "$4.5 million" is ONE span, not money + count
    ms = [d for d in find("worth $4.5 million") if d["type"] in ("money", "count")]
    assert len(ms) == 1 and ms[0]["type"] == "money", ms
    print("ok")


if __name__ == "__main__":
    _demo() if "--demo" in sys.argv else _demo()
