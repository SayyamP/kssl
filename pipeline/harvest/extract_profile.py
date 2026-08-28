"""Leadership, facilities and sales — the three Profile sections the corpus never had.

    python extract_profile.py --demo
    python extract_profile.py --report      # what would be extracted, with the line
    python extract_profile.py --apply       # write into harvest.fact

Profile currently prints "not collected" under Leadership, Facilities and Sales, which is
honest but is not the answer. These three read them out of the pages the harvester
brought back, under the same rule everything else here follows: a value is written only
with the URL and the VERBATIM line it came from.

EVERY FIELD GETS ITS OWN GATE
-----------------------------
This codebase's standing lesson is that the unchecked field is where the hallucination
lives, so there is no shared "looks about right" path. A person is not validated the way
a plant is, and neither is validated the way a revenue figure is:

  leadership  a NAME must sit beside a ROLE, and must not be a company name. The failure
              this prevents is "Board Of Directors" and "Tata Advanced Systems" being
              filed as people, which is what any name-shaped-token rule does on a
              corporate site.
  facilities  a PLACE must sit beside a FACILITY NOUN. "Our customers in Germany" is not
              a plant in Germany; the noun is what distinguishes a site from a market.
  sales       a CURRENCY AMOUNT must sit beside a REVENUE ANCHOR, and a fiscal year is
              kept only when the line states one. An amount near the word "crore" on an
              investor page is as likely to be a contract as a revenue.

All three refuse rather than guess. A page that yields nothing leaves the section reading
"not collected", which is the correct output when nothing was collected.
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

# ── leadership ────────────────────────────────────────────────────────────────
ROLE = re.compile(
    r"\b(chief executive officer|managing director|chairman|chairperson|chairwoman|"
    r"chief financial officer|chief operating officer|chief technology officer|"
    r"chief technical officer|executive director|managing partner|"
    r"president(?: & ceo| and ceo)?|vice president|senior vice president|"
    r"director general|joint managing director|whole[- ]time director|"
    r"independent director|non[- ]executive director|company secretary|"
    r"head of [a-z ]{3,28}|general manager|group ceo|ceo|cfo|coo|cto|cmd|md)\b", re.I)

# 2–4 capitalised words. Deliberately NOT a name database: this has to work for Indian,
# Korean, Israeli, French and Nordic names alike, and a closed list of first names is the
# same "closed keyword list is a language detector" fault in another costume.
NAME = re.compile(r"\b((?:(?:Dr|Mr|Ms|Mrs|Shri|Smt|Lt|Col|Gen|Maj|Capt|Adm|Air)\.?\s+)?"
                  r"[A-Z][a-zA-Z'’.-]{1,20}(?:\s+[A-Z][a-zA-Z'’.-]{1,20}){1,3})\b")

# A name-shaped token that is not a person. Without this, "Board Of Directors",
# "Annual Report", "Defence Systems" and the company's own name all become officers.
NOT_A_PERSON = re.compile(
    r"\b(board|director[s]?$|committee|report|limited|ltd|pvt|private|inc|corp|"
    r"company|group|systems?|technolog|industr|defence|defense|aerospace|solutions?|"
    r"holdings?|enterprise|division|department|management|leadership|team|profile|"
    r"policy|statement|overview|home|contact|careers?|investor|news|media|about|"
    r"privacy|cookie|terms|copyright|all rights|read more|learn more|view|click|"
    r"chairman|director|officer|president|manager|secretary)\b", re.I)

# ── facilities ────────────────────────────────────────────────────────────────
FACILITY = re.compile(
    r"\b(plant|factory|facility|facilities|manufacturing (?:unit|site|facility|centre|center)|"
    r"production (?:unit|facility|line|centre|center)|works|workshop|foundry|forge|"
    r"shipyard|assembly line|test (?:range|track|facility|centre|center)|"
    r"r&d (?:centre|center|facility)|campus|integration centre|integration center)\b", re.I)
PLACE = re.compile(r"\b(?:at|in|near|located (?:at|in)|based (?:at|in))\s+"
                   r"([A-Z][a-zA-Z'’.-]{2,20}(?:\s+[A-Z][a-zA-Z'’.-]{2,20}){0,2})")
# Two shapes, because makers write it both ways and catching only one loses half:
#   "a forging plant at Baramati"   -> preposition, then place
#   "Bhandara Plant, Maharashtra"   -> place, then the facility noun
PLACE_BEFORE = re.compile(r"\b([A-Z][a-zA-Z'’.-]{3,20})\s+(?=(?:Plant|Factory|Works|"
                          r"Facility|Unit|Foundry|Forge|Shipyard|Campus)\b)")

# ── sales ─────────────────────────────────────────────────────────────────────
REVENUE = re.compile(
    r"\b(revenue|turnover|order book|order backlog|net sales|total income|"
    r"gross sales|sales of|profit after tax|ebitda|topline)\b", re.I)
MONEY = re.compile(
    r"(?:(?:INR|Rs\.?|₹|US\$|USD|\$|€|EUR|£)\s*[\d,]+(?:\.\d+)?\s*"
    r"(?:crore|cr\b|lakh|million|billion|bn\b|mn\b)?"
    r"|[\d,]+(?:\.\d+)?\s*(?:crore|lakh|million|billion|bn\b|mn\b)\s*"
    r"(?:INR|Rs\.?|₹|USD|US\$|\$|€|EUR|£|rupees|dollars|euros)?)", re.I)
FY = re.compile(r"\b(?:FY\s?-?\s?(\d{2,4})(?:\s?-\s?(\d{2,4}))?|"
                r"(?:financial|fiscal) year\s+(\d{4})(?:\s?-\s?(\d{2,4}))?|"
                r"\b(20\d\d)\s?-\s?(\d{2}))\b", re.I)


# A site's NAME is a proper noun. "Arms", "Boxes", "Engine" and bare countries all
# arrived as places from real pages ("Small Arms Factory", "Engine Factory Avadi",
# "assembly line in India") - the first two are the product, the last is a market.
GENERIC_PLACE = re.compile(
    r"^(arms?|boxes?|engine|vehicle|shell|gun|rifle|ordnance|small|heavy|light|"
    r"india|usa|uk|europe|asia|africa|america|russia|the|our|new|main|central|"
    r"read|more|home|about|test|junior|senior|brazing|assembly|integration|"
    r"machine|paint|final|quality|training|sugar|cement|steel|paper|power|chemical|boiler|nuclear|space|aerospace|defence|marine)$", re.I)


def lines_of(text):
    """Text as short blocks. A corporate page is a wall of nav plus cards, so the unit
    that actually pairs a name with a role is a LINE, not a sentence."""
    out = []
    for raw in re.split(r"[\n\r]+|(?<=[.;])\s{2,}", text or ""):
        s = re.sub(r"[ \t]+", " ", raw).strip(" \t|·•-")
        if 4 <= len(s) <= 400:
            out.append(s)
    return out


MONTHS = re.compile(r"^(january|february|march|april|may|june|july|august|september|"
                    r"october|november|december|new year|annual|quarterly)\b", re.I)
# A capitalised run that is a heading, an id, or the start of a sentence - not a person.
NOT_NAME = re.compile(
    r"\b(advertisement|notice|result|post|ref|circular|tender|during|after|before|"
    r"since|under|with|from|this|these|he|she|they|his|her|dpsu\w*|ddg|complex|"
    r"ammunition|unit|units|head|heads|member|members|sbu|state|police|housing|"
    r"corporation|ministry|govt|government|award|awards|factory|plant|works|planning|"
    r"limited|india|bharat|electronics|defence|systems|charge|meeting|committee|"
    r"parliament|assumed|held|key|positions|serving|technology|research)\b", re.I)

HONORIFIC = re.compile(r"^(?:Dr|Mr|Ms|Mrs|Shri|Smt|Lt|Col|Gen|Maj|Capt|Adm|Air)\.?\s+", re.I)


def looks_like_person(name):
    """A person's name, or a capitalised phrase off a corporate page?

    Every rejection here comes from a real false positive on a harvested page:
    "Unit Head", "SBU Heads", "Member Mrs Meera Mohanty", "BEL's Kotdwar Unit",
    "Gujarat State Police Housing", "Technology Planning". All of them sat next to a
    genuine role word, so adjacency alone could not tell them from "Mr Manoj Jain".

    Two or three ordinary capitalised words after any courtesy title, and not one of
    them a structural word. Beyond three words it is a phrase, not a name.
    """
    core = HONORIFIC.sub("", name or "").strip()
    words = core.split()
    if not (2 <= len(words) <= 3):
        return False
    if NOT_NAME.search(core) or NOT_A_PERSON.search(core):
        return False
    return all(re.fullmatch(r"[A-Z][a-z'’.-]{1,19}\.?", w) for w in words)


def leadership(text):
    """[(name, role, line)] — a person only when a name sits ADJACENT to a role.

    Adjacency is the whole gate. Allowing any name anywhere in the line produced, from
    real harvested pages: "Adani Ammunition Complex" (a plant, from "Chairman Shri Gautam
    Adani at Adani Ammunition Complex"), "NEW YEAR" (from "NEW YEAR 2026 MESSAGE FROM
    CMD"), "Advertisement No. AWEIL" and "During March". Every one of those had a real
    role word somewhere on the same line.

    A person and their title are written next to each other - "Gautam Adani, Chairman" or
    "Chairman: Gautam Adani" - separated by punctuation and at most a courtesy title. So
    only the NEAREST name is considered, and only if it is within a few characters.
    """
    out, seen = [], set()
    for ln in lines_of(text):
        for rm in ROLE.finditer(ln):
            role = rm.group(0).strip()
            best = None
            for nm in NAME.finditer(ln):
                name = nm.group(1).strip(" .,")
                if not (nm.end() <= rm.start() or nm.start() >= rm.end()):
                    continue
                # THE NAME MUST COME FIRST. Auditing 38 extracted rows by hand, this one
                # rule separated every correct row from every wrong one:
                #   "Micael Johansson, President & CEO"   name then role -> a person
                #   "President, Electric Boat"            role then name -> a DIVISION
                #   "Chairman, Jindal Steel"              role then name -> a COMPANY
                #   "Vice President-International Sales"  role then name -> a DEPARTMENT
                # Twenty of the twenty-two false positives were the second shape, and no
                # correct row was. English writes a person before their title and a scope
                # after it, and that ordering is the whole signal.
                if nm.start() >= rm.end():
                    continue
                gap = rm.start() - nm.end()
                # only what sits between them: punctuation, "is/of/the", a courtesy title
                between = ln[min(nm.end(), rm.end()):max(nm.start(), rm.start())]
                if gap > 24 or not re.fullmatch(r"[\s,;:()–—/|.-]*"
                                                r"(?:is|was|the|of|our|a|an|as|shri|smt|mr|ms|dr)?"
                                                r"[\s,;:()–—/|.-]*", between, re.I):
                    continue
                if best is None or gap < best[0]:
                    best = (gap, name)
            if not best:
                continue
            name = best[1]
            if MONTHS.match(name) or not looks_like_person(name):
                continue
            # "Mr Vladimir Putin, President of Russia" and "Olivier Cauquil, Head of
            # Procurement - Aerostructures, Airbus" are real people holding real roles
            # at OTHER organisations. A role qualified by "of <Proper Noun>" belongs to
            # whatever follows it, and that is not necessarily the company whose page
            # this is.
            after = ln[rm.end():rm.end() + 40]
            # A role qualified by another organisation belongs to that organisation:
            #   "President of Russia"
            #   "Head of Procurement - Aerostructures, Airbus"
            #   "Chairman, Tata Sons"
            # All three are real people with real titles, and none of them is an officer
            # of the company whose page we are reading.
            if re.match(r"\s*(?:of|at)\s+[A-Z]", after) or re.match(r"\s*[-,–]\s+[A-Z][a-z]", after):
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append((name, role, ln))
    return out


def facilities(text):
    """[(place, kind, line)] — a site only when a place sits beside a facility noun."""
    out, seen = [], set()
    for ln in lines_of(text):
        fm = FACILITY.search(ln)
        if not fm:
            continue
        kind = fm.group(0).strip()
        # PLACE_BEFORE ("Bhandara Plant") is only trusted when a REGION follows the
        # facility noun. Without that, the pattern happily reads the process word in
        # front of the noun as a place: "Welding Facility", "Testing Facility", "Power
        # Plant", "Fabrication Facility" were all filed as sites. A real site names
        # where it is - "Bhandara Plant, Maharashtra" - and a process step does not.
        befores = [m for m in PLACE_BEFORE.finditer(ln)
                   if re.match(r"\s*(?:Plant|Factory|Works|Facility|Unit|Foundry|Forge|"
                               r"Shipyard|Campus)\s*,\s*[A-Z][a-z]", ln[m.end():m.end() + 40])]
        for pm in list(PLACE.finditer(ln)) + befores:
            place = pm.group(1).strip(" .")
            # "March", "MRO" and "India" all arrived as places from real pages. A month
            # is a date, an acronym is not a location, and a bare country is a market
            # unless the facility noun is right beside it.
            # sentence bleed: "Pune. This" came from "...in Pune. This plant..."
            if re.search(r"[.!?]\s", place):
                continue
            # "Our Manufacturing Facility" is a heading; "South Asia" is a region a
            # company sells into, not a site it operates.
            if re.match(r"^(our|the|its|a|an)\b", place, re.I):
                continue
            if re.match(r"^(south|north|east|west|central)\s+(asia|america|africa|europe)$",
                        place, re.I):
                continue
            if (NOT_A_PERSON.search(place) or GENERIC_PLACE.match(place)
                    or MONTHS.match(place) or place.isupper()
                    or len(place) < 4):
                continue
            if abs(pm.start() - fm.start()) > 60:
                continue
            key = place.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((place, kind, ln))
    return out


def sales(text):
    """[(amount, period, line)] — a figure only when money sits beside a revenue word."""
    out, seen = [], set()
    for ln in lines_of(text):
        rm = REVENUE.search(ln)
        if not rm:
            continue
        for mm in MONEY.finditer(ln):
            amount = re.sub(r"\s+", " ", mm.group(0)).strip()
            if not re.search(r"\d", amount):
                continue
            # a bare number with no scale or currency is not a revenue figure
            if not re.search(r"(crore|lakh|million|billion|bn|mn|INR|Rs|₹|\$|€|£|USD|EUR)",
                             amount, re.I):
                continue
            fm = FY.search(ln)
            period = re.sub(r"\s+", " ", fm.group(0)).strip() if fm else ""
            key = (amount.lower(), period.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((amount, period, ln))
    return out


FIELDS = {"leadership": leadership, "facilities": facilities, "sales": sales}
# which harvested `need` pages each field is allowed to read. Reading a revenue figure
# off a products page, or an officer off a news page, is how a field drifts.
SOURCES = {
    "leadership": ("leadership", "about", "home"),
    "facilities": ("facilities", "about", "products", "home"),
    "sales": ("sales", "about"),
}


def rows():
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        cur.execute("""select p.cid, t.company, p.need, p.url, p.text
                       from harvest.page p join harvest.task t on t.task_id=p.task_id
                       where length(p.text) > 200""")
        return cur.fetchall()


def run(apply_it=False, limit=None):
    import psycopg2 as pg
    found = {}
    for cid, company, need, url, text in rows():
        for field, fn in FIELDS.items():
            if need not in SOURCES[field]:
                continue
            for value, detail, line in fn(text):
                found.setdefault((cid, company, field, value), (detail, url, line))

    per = {}
    for (cid, company, field, value), (detail, url, line) in sorted(found.items()):
        per.setdefault(field, []).append((company, value, detail, url, line))
    for field in FIELDS:
        got = per.get(field, [])
        print("== %s == %d values over %d companies"
              % (field, len(got), len({g[0] for g in got})))
        for company, value, detail, url, line in got[:limit or 10]:
            print("   %-26s %-30s %s" % (company[:26], value[:30], detail[:26]))
            print("        %s" % line[:130])
        print()

    if not apply_it:
        print("DRY RUN — nothing written. Re-run with --apply")
        return
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        n = 0
        for (cid, company, field, value), (detail, url, line) in found.items():
            cur.execute("""insert into harvest.fact
                (cid, company, field, value, detail, url, line)
                values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""",
                        (cid, company, field, value, detail, url, line[:1000]))
            n += cur.rowcount
        cx.commit()
    print("wrote %d new facts" % n)


def demo():
    # A regex written through a shell heredoc has had its \b collapse into a literal
    # 0x08 byte three times in this codebase now. The pattern still COMPILES and simply
    # never matches, so the field goes quietly empty and looks like a thin source.
    for rx in (ROLE, NAME, NOT_A_PERSON, FACILITY, PLACE, PLACE_BEFORE, REVENUE,
               MONEY, FY, MONTHS, NOT_NAME):
        assert not any(ord(c) < 32 for c in rx.pattern),             "control char in %r" % rx.pattern[:60]

    # leadership: a name beside a role is a person
    got = leadership("Mr. Rajesh Kumar Sharma, Managing Director & CEO")
    assert got and got[0][0].endswith("Rajesh Kumar Sharma"), got
    # the role words themselves must not become a person
    assert not leadership("Board of Directors"), leadership("Board of Directors")
    assert not leadership("Chief Executive Officer"), "a bare role is not a person"
    # a company name beside a role must not become a person
    assert not leadership("Tata Advanced Systems Limited, Managing Director")
    # a name with no role nearby is not published
    assert not leadership("Rajesh Kumar visited the plant last week")

    # facilities: a place beside a facility noun
    got = facilities("The forging plant at Baramati produces 155mm shell bodies.")
    assert got and got[0][0] == "Baramati" and "plant" in got[0][1], got
    # a market is not a site
    assert not facilities("We serve customers in Germany and France.")

    # sales: money beside a revenue word, with the period when stated
    got = sales("Revenue for FY 2024-25 stood at Rs. 1,250 crore.")
    assert got and "1,250 crore" in got[0][0] and "2024-25" in got[0][1], got
    # a contract value on an investor page is not revenue
    assert not sales("The company won an order at Baramati for new tooling.")
    # a bare number is not a figure
    assert not sales("Revenue grew by 12 in the period."), sales("Revenue grew by 12 in the period.")
    # the real false positives that this gate exists to stop
    assert not leadership("Chairman Shri Gautam Adani at Adani Ammunition Complex, Kanpur")         or leadership("Chairman Shri Gautam Adani at Adani Ammunition Complex, Kanpur")[0][0]         == "Gautam Adani", leadership("Chairman Shri Gautam Adani at Adani Ammunition Complex, Kanpur")
    assert not leadership("NEW YEAR 2026 MESSAGE FROM CMD/AVNL")
    # role-then-org is never a person - the dominant false positive in the first audit
    assert not leadership("President, Electric Boat")
    assert not leadership("Chairman, Jindal Steel")
    assert not leadership("Vice President-International Sales")
    assert not leadership("Managing Director, Nammo Finland")
    # ...and someone else's officer is not this company's
    assert not leadership("Mr Vladimir Putin, President of Russia")
    assert not leadership("Olivier Cauquil, Head of Procurement - Aerostructures, Airbus")
    assert not leadership("Mr. N. Chandrasekaran, Chairman, Tata Sons")
    # name-then-role still works
    got = leadership("Micael Johansson, President & CEO")
    assert got and got[0][0] == "Micael Johansson", got
    assert not leadership("Result for the post of Company Secretary - Advertisement No. AWEIL/01/2025")
    assert not leadership("During March 2022 to October 2023, he was DDG of New Defence "
                          "Companies Division. As Executive Director he later joined.")
    got = facilities("Ashok Leyland's Bhandara Plant, Maharashtra was inaugurated")
    assert got and got[0][0] == "Bhandara", got
    # a process step in front of the noun is not a place
    assert not facilities("The Welding Facility uses robotic cells")
    assert not facilities("Testing Facility for electronic assemblies")
    assert not facilities("Our Power Plant supplies the campus")
    assert not facilities("a new line in Pune. This plant will build engines")
    print("extract_profile demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        run(a.apply, a.limit)
