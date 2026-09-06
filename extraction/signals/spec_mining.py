# -*- coding: utf-8 -*-
"""Competitor specifications, read out of the corpus instead of left blank.

    python spec_mining.py --demo              # hermetic: the guards, no DB, no model
    python spec_mining.py --probe "CAESAR"    # what the corpus states, with quotes
    python spec_mining.py --dump cand.json --products "CAESAR=CAESAR|Caesar Mk II"
                                              # collect candidates where the corpus is
    python spec_mining.py --from-json cand.json   # read them where the GPU is

READS ONLY. There is no --apply, and a bare invocation is a usage error, not a run.
This module reports what the corpus states; putting a value into serving.matchup is a
separate, deliberate step. Nothing here writes to the serving layer.

WHY THIS EXISTS. The Positioning tab prints "not sourced" against a rival's maximum
range, weight and rate of fire, and then reports, correctly, that nothing is
comparable on both sides. The corpus is not silent about any of it:

    CAESAR       max range 40 km      stated in 34 places across 8 domains
                 rate of fire 6/min   21 places, 4 domains
                 weight 18 t          7 places, 2 domains
    Archer       max range 40 km      10 places, 5 domains
    K9 Thunder   weight 47 t          "the 47 tonne SPH", Janes

revive_matchups.ground_value only VERIFIES a number the archive already claims. If
the archive is silent for that field, nothing is looked for, and 162 documents
mentioning CAESAR cannot help. This module DISCOVERS the value.

WHAT IT READS. extracted.proposition, not raw text -- 894,640 subject/predicate/object
triples the extraction layer already produced, each with the quote it came from. The
subject is what makes this safe. A window over raw text puts

    "the Dana type 77 weighs about 29 tons, which is 12 tons more than Caesar"

within 60 characters of "Caesar", and a proximity rule reads 29 tonnes as CAESAR's
weight. It is Dana's, and the proposition says so: its subject is "The self-propelled
howitzer Dana type 77". Attribution is a decision the extraction layer already made,
in whatever language the document was written in.

THE FIVE WAYS A NAIVE READ GETS THIS WRONG, all of them observed in this corpus
while probing it, and each answered by a check below:

  1. SPEED IS NOT RANGE. "the Archer can reach a road speed of 70 km/h with a range of
     up to 500" -- 70 km/h and 40 km are both lengths per the digits and different
     quantities per the unit. unit_at() reads the unit the SOURCE wrote and BASE says
     km/h is speed; a field that wants a length refuses it.
  2. THE NUMBER BELONGS TO ANOTHER PRODUCT. The Dana sentence above; and "D'une masse
     de près de 30 tonnes" sitting in a K9 document about the CAESAR 8x8. Answered by
     the subject, and by refusing a subject that names two tracked products.
  3. THE MEASUREMENT IS A DIFFERENT MEASUREMENT UNDER SIMILAR WORDS. The M777's "towed
     by vehicles weighing over 2.5 tonnes" is the TOWING VEHICLE. Answered by
     requiring the model to name the field and then checking that the number it named
     is the one the quote attaches to that field.
  4. THE FIGURE IS CONDITIONAL. CAESAR is 40 km with conventional shells, 42 with
     ERFB, over 50 with rocket assistance; the M777 is 24.7 km unassisted and 40 km
     with Excalibur. All true, none comparable with each other. The qualifier is
     captured and stored, and a comparison that cannot match qualifiers is not made.
  5. ONE SOURCE IS NOT A FACT. Consensus is required across independent domains, by
     the same publishability rule the rest of this pipeline uses.

WHY A MODEL READS THE FIELD. Deciding that "portée de 4 à 42 km" and "na odległość do
35 km" and "jarak serangan melebihi 40 kilometer" are all maximum ranges is exactly
the judgement a surface list cannot make: 25% of the number-bearing propositions for
these ten products are not in English (es 34, fr 29, pl 19, ms 18, de 4, tr 4, ru 3,
uk 3, he 1 against en 350). A regex vocabulary here would be a language detector for
the fourth time in this repo.

The model is not trusted. It proposes a field, a number, a unit and a qualifier, and
every one of those is then checked against the quote deterministically -- the number
must be in the text, the unit must be the one written beside it, the quantity must be
the one the field measures, the qualifier must appear. A model answer that survives
all four is a reading of the source, not an assertion about the world.
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

DSN = (os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
       or os.environ.get("KSSL_SERVING_DSN") or os.environ.get("DSN") or "")
OLLAMA = os.environ.get("SPEC_MINING_LLM", "http://127.0.0.1:11434")
MODEL = os.environ.get("SPEC_MINING_MODEL", "qwen2.5:7b-instruct")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# what a field IS -- the quantity it measures, not the words that name it
# --------------------------------------------------------------------------
# The unit decides the quantity; the quantity decides whether a number can be that
# field at all. This is the whole answer to "speed is not range": both are written
# with "km", and only "km/h" is a speed.
QUANTITY = {
    "mm": "length", "cm": "length", "m": "length", "km": "length",
    "kg": "mass", "t": "mass", "tonne": "mass", "tonnes": "mass", "lb": "mass",
    "km/h": "speed", "kph": "speed", "mph": "speed",
    "hp": "power", "kw": "power",
    "rds/min": "rate", "rpm": "rate",
    "": "count",
}

# The client's own artillery vocabulary. A field the client does not publish cannot be
# compared against anything, so mining it would produce a row with one side.
FIELDS = {
    "Calibre": dict(quantity="length", units=("mm",), hi=None),
    "Max range": dict(quantity="length", units=("km",), hi=True),
    "Weight": dict(quantity="mass", units=("t", "kg"), hi=False),
    "Rate of fire": dict(quantity="rate", units=("rds/min",), hi=True),
    "Crew": dict(quantity="count", units=("",), hi=False),
}

_NUM = re.compile(r"\d[\d.,]*")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def numbers(s):
    """Every number in a string, as written."""
    return [m.group(0).rstrip(".,") for m in _NUM.finditer(str(s or ""))]


# Every spelling a source or a model uses, and the one form the checks compare. Not a
# language list: these are unit symbols, fixed by the SI and by convention, and a
# missing spelling can only cost a reading -- it can never invent one.
UNIT_SURFACES = (
    ("km/h", "km/h"), ("kph", "km/h"), ("km / h", "km/h"),
    ("kilometres per hour", "km/h"), ("kilometers per hour", "km/h"), ("mph", "mph"),
    ("rounds per minute", "rds/min"), ("rounds/minute", "rds/min"),
    ("rounds/min", "rds/min"), ("rounds a minute", "rds/min"),
    ("rds/min", "rds/min"), ("rds per min", "rds/min"), ("rpm", "rds/min"),
    ("coups par minute", "rds/min"), ("rounds", "rds/min"),
    ("mm", "mm"), ("millimet", "mm"),
    ("kilomet", "km"), ("km", "km"),
    ("tonnes", "t"), ("tonne", "t"), ("tons", "t"), ("ton", "t"), ("t", "t"),
    ("kg", "kg"), ("kilogram", "kg"), ("lb", "lb"), ("pounds", "lb"),
    ("hp", "hp"), ("kw", "kw"),
    ("cm", "cm"), ("m", "m"),
)


def normalise_unit(u):
    """"rounds per minute" -> "rds/min", "tons" -> "t". One form, so two spellings of
    one unit are not read as two different units."""
    u = str(u or "").strip().lower().lstrip(" -")
    if not u:
        return ""
    for surface, unit in UNIT_SURFACES:
        if re.match(re.escape(surface) + r"(?![a-z])", u):
            return unit
    return u


def unit_written(text, value):
    """The unit the SOURCE wrote immediately after this number, normalised.

    Reads the text, never the caller's claim. "70 km/h" gives km/h and not km, which
    is the difference between the Archer's road speed and its firing range.
    """
    i = str(text or "").find(str(value))
    if i < 0:
        return None
    tail = str(text)[i + len(str(value)): i + len(str(value)) + 18].lower()
    tail = tail.lstrip("  -")
    for surface, unit in UNIT_SURFACES:
        # A UNIT ENDS WHERE THE WORD ENDS. Without the boundary "40 targets" begins
        # with "t" and reads as 40 tonnes, "5 metres" as 5 m is fine but "5 members"
        # is not, and every one-letter unit becomes a wildcard over the language.
        if re.match(re.escape(surface) + r"(?![a-z])", tail):
            return unit
    return ""


def refuse(field, value, unit, qualifier, object_text):
    """-> reason the model's reading must not be believed, or None.

    Every check is against the QUOTE. The model proposes; the text disposes.
    """
    spec = FIELDS.get(field)
    if not spec:
        return "not a field the client publishes"

    # 1. THE NUMBER MUST BE IN THE TEXT. A value the quote does not contain was
    #    invented, however plausible it looks.
    if not value or str(value) not in str(object_text or ""):
        return "the value is not in the quote"

    # 1b. AND IT MUST BE A NUMBER AND NOTHING ELSE. "over 40 km" and "30 to 40 km"
    #     both came back
    #     from the corpus. Neither parses, so both collapse to the same consensus key
    #     as every other unparseable reading and the first one wins; and neither can
    #     be set beside a KSSL figure without asserting a comparison the source did
    #     not make. The client-side recipes refuse hedged values for the same reason.
    if to_base(value, "") is None or _NUM.fullmatch(str(value).strip()) is None:
        return "not a single figure: a range or a hedge cannot be compared"

    # 2. THE UNIT MUST BE THE ONE WRITTEN. Not the one the model reports and not the
    #    one the field expects -- the one beside the number in the source.
    written = unit_written(object_text, value)
    if written is None:
        return "the value is not in the quote"
    if spec["quantity"] == "count":
        if written not in ("", None):
            return "a count with a unit is a measurement of something else"
    else:
        if not written:
            return "no unit is written beside the number"
        if QUANTITY.get(written) != spec["quantity"]:
            return ("the source writes %s, which measures %s, not %s"
                    % (written, QUANTITY.get(written, "?"), spec["quantity"]))
        if written not in spec["units"]:
            return "unit %s is the right quantity but not this field's unit" % written
        # BOTH SIDES NORMALISED. unit_written already folds "rounds per minute" onto
        # "rds/min"; holding the model's raw spelling against that folded form refused
        # six rates of fire and three weights over nothing but wording.
        if unit and normalise_unit(unit) != written:
            return ("the model read %s where the source writes %s"
                    % (normalise_unit(unit), written))

    # 3. A QUALIFIER IS PART OF THE CLAIM, so it has to be in the claim.
    if qualifier and norm(qualifier) not in norm(object_text):
        return "the qualifier is not in the quote"

    return None


# --------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------
def subject_names(subject, surfaces, other_surfaces=()):
    """Does this proposition's subject name OUR product, and only ours?

    "The self-propelled howitzer Dana type 77" is not CAESAR even in a sentence that
    ends "...12 tons more than Caesar", and a subject naming two tracked products
    ("CAESAR and Archer both...") attributes to neither.
    """
    s = norm(subject)
    if not s:
        return False
    if not any(norm(x) and norm(x) in s for x in surfaces):
        return False
    for other in other_surfaces:
        n = norm(other)
        if n and n in s and not any(n in norm(x) for x in surfaces):
            return False
    return True


CAND_SQL = """
select p.document_id, p.subject, p.predicate, p.object,
       coalesce(p.ev_quote, p.object) as quote, d.url, d.language
  from extracted.proposition p
  join extracted.document d using (document_id)
 where p.object ~ '[0-9]'
   and p.polarity is distinct from 'negative'
   and lower(p.subject) like any(%s)
 limit %s
"""


def candidates(cur, surfaces, other_surfaces=(), limit=4000):
    like = ["%%%s%%" % s.lower() for s in surfaces]
    cur.execute(CAND_SQL, (like, limit))
    out = []
    for did, subj, pred, obj, quote, url, lang in cur.fetchall():
        if not subject_names(subj, surfaces, other_surfaces):
            continue
        out.append(dict(document_id=did, subject=subj, predicate=pred, object=obj,
                        quote=quote, url=url, language=lang))
    return out


# --------------------------------------------------------------------------
# the model reads the field; nothing here believes it
# --------------------------------------------------------------------------
PROMPT = """You read statements about weapon systems and say which measurement each \
one states, if any.

The measurements that matter, and nothing else counts:
- Calibre       the bore of the gun, in mm
- Max range     the furthest the gun can fire a projectile, in km
- Weight        the mass of the system, in tonnes or kg
- Rate of fire  rounds fired per minute
- Crew          how many people operate it

Rules:
- A road speed, a cruising range of the vehicle, a transport or towing weight, a \
production quantity, a price, a year, an order size or a number of units is NOT one \
of the five. Answer null for it.
- Copy the number and the unit from the statement. Do not convert, round or infer.
- If the figure depends on a condition -- a shell type, a configuration, a variant -- \
copy that condition into qualifier.
- If the statement is not in English, still answer with the number and unit as they \
appear in it.

STATEMENTS
{items}

Answer with a JSON array only, one object per statement, each carrying the statement's \
number:
[{{"i": 1, "field": "<one of the five, or null>", "value": "<the number exactly as \
written>", "unit": "<the unit exactly as written>", "qualifier": "<the condition, \
copied from the statement, or null>"}}]
"""

# One call is 38 seconds on this CPU box, of which 30 is model load and prompt eval --
# the cost is per CALL, not per statement, so eight statements in one call is eight
# times the work for barely more time.
#
# A batch can misalign: the model can answer about statement 3 under index 5. Nothing
# special is needed to catch it. Every answer is checked against the object text of the
# index it claims, and a value from a different statement is not in that text, so a
# misaligned answer fails "the value is not in the quote" exactly like an invented one.
BATCH = int(os.environ.get("SPEC_MINING_BATCH", "8"))


def read_batch(rows, ask):
    """-> {index in rows: {field, value, unit, qualifier}} as the model proposes."""
    items = "\n".join(
        "%d. %s %s %s" % (i + 1, r["subject"], r["predicate"] or "", r["object"])
        for i, r in enumerate(rows))
    raw = ask(PROMPT.format(items=items))
    if not raw:
        return {}
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return {}
    out = {}
    for d in arr if isinstance(arr, list) else []:
        if not isinstance(d, dict) or not d.get("field"):
            continue
        try:
            i = int(d.get("i", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(rows)):
            continue
        out[i] = {"field": str(d.get("field") or "").strip(),
                  "value": str(d.get("value") or "").strip(),
                  "unit": str(d.get("unit") or "").strip(),
                  "qualifier": (str(d.get("qualifier")).strip()
                                if d.get("qualifier") not in (None, "", "null") else "")}
    return out


def ollama_asker(url=None, model=None, timeout=90):
    import urllib.request
    url = (url or OLLAMA).rstrip("/")
    model = model or MODEL

    def ask(prompt):
        body = json.dumps({
            "model": model, "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r).get("message", {}).get("content", "")
        except Exception as e:
            print("   model call failed: %s" % type(e).__name__, file=sys.stderr)
            return ""
    return ask


# --------------------------------------------------------------------------
# consensus
# --------------------------------------------------------------------------
def domain(url):
    m = re.match(r"https?://([^/]+)", str(url or ""), re.I)
    return (m.group(1).lower().replace("www.", "") if m else "").strip()


def to_base(value, unit):
    """One number in the field's own unit, so two readings can be compared."""
    try:
        v = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return {"t": v, "kg": v / 1000.0, "km": v, "mm": v, "rds/min": v, "": v}.get(unit, v)


def consensus(readings, min_domains=2):
    """-> [{field, value, unit, qualifier, domains, sources, spread}]

    One source is a claim; two independent ones are a fact. That is the same bar the
    rest of this pipeline applies, and it is what stops a single blog's "55 km" being
    published as the CAESAR's range beside a KSSL figure measured differently.
    """
    by = collections.defaultdict(list)
    for r in readings:
        key = (r["field"], to_base(r["value"], r["unit"]), r["unit"])
        by[key].append(r)
    out = []
    for (field, base, unit), rows in by.items():
        doms = {domain(r["url"]) for r in rows if domain(r["url"])}
        if len(doms) < min_domains:
            continue
        quals = collections.Counter(r["qualifier"] for r in rows if r["qualifier"])
        out.append({
            "field": field, "value": rows[0]["value"], "unit": unit, "base": base,
            "qualifier": quals.most_common(1)[0][0] if quals else "",
            "domains": sorted(doms), "n": len(rows),
            "sources": sorted({r["url"] for r in rows})[:6],
            "quote": rows[0]["quote"][:300],
        })
    # Same field stated at several values: report every one, ordered by how many
    # independent sources back it. Choosing silently is how a rocket-assisted range
    # comes to be compared against a conventional one.
    out.sort(key=lambda r: (r["field"], -len(r["domains"]), -r["n"]))
    return out


# --------------------------------------------------------------------------
def demo():
    fails = []

    def ck(name, ok, d=""):
        print("  %-68s %s%s" % (name, "PASS" if ok else "FAIL", "  " + str(d) if d else ""))
        if not ok:
            fails.append(name)

    # 1. SPEED IS NOT RANGE -- the Archer sentence, verbatim from the corpus.
    q = "the Archer can reach a road speed of 70 km/h with a range of up to 500"
    r = refuse("Max range", "70", "km", "", q)
    ck("a road speed in km/h is refused as a maximum range",
       r and "measures speed" in r, r)
    ck("... and the unit read is the one the source wrote",
       unit_written(q, "70") == "km/h", unit_written(q, "70"))

    # 2. THE SUBJECT DECIDES WHOSE NUMBER IT IS -- the Dana sentence, verbatim.
    ck("a number stated about another product is not ours",
       not subject_names("The self-propelled howitzer Dana type 77",
                         ["caesar"], ["dana"]))
    ck("... and our own product still resolves",
       subject_names("The CAESAR MkII", ["caesar"], ["dana", "archer"]))
    ck("a subject naming two tracked products attributes to neither",
       not subject_names("CAESAR and Archer", ["caesar"], ["archer"]))

    # 3. AN INVENTED NUMBER CANNOT SURVIVE THE QUOTE.
    ck("a hedged figure is refused",
       refuse("Max range", "over 40", "km", "", "reaches over 40 km")
       == "not a single figure: a range or a hedge cannot be compared")
    ck("a span is refused too",
       refuse("Max range", "30 to 40", "km", "", "a range of 30 to 40 km")
       == "not a single figure: a range or a hedge cannot be compared")
    ck("a decimal figure is still one figure",
       refuse("Max range", "24.7", "km", "", "a maximum range of 24.7 km") is None)

    ck("a value absent from the quote is refused",
       refuse("Max range", "42", "km", "",
              "has a firing range of 40 km") == "the value is not in the quote")

    # 4. THE QUALIFIER IS PART OF THE CLAIM.
    ok_q = "has a firing range of approximately 42 km using an Extended Range Full Bore shell"
    ck("a real conditional figure survives with its condition",
       refuse("Max range", "42", "km", "Extended Range Full Bore", ok_q) is None,
       refuse("Max range", "42", "km", "Extended Range Full Bore", ok_q))
    ck("a qualifier the quote does not contain is refused",
       refuse("Max range", "42", "km", "rocket assisted", ok_q)
       == "the qualifier is not in the quote")

    # 5. UNITS.
    ck("a mass in tonnes is a weight",
       refuse("Weight", "47", "t", "", "the 47 tonne SPH is capable of firing") is None)
    ck("a bare crew count takes no unit",
       refuse("Crew", "5", "", "", "Operated by a five-man crew of 5 soldiers") is None)
    ck("a number with no unit is not a range",
       refuse("Max range", "40", "", "", "reaches 40 targets")
       == "no unit is written beside the number")
    ck("an unknown field is refused",
       refuse("Muzzle velocity", "945", "m/s", "", "945 m/s")
       == "not a field the client publishes")
    ck("one unit spelled two ways is one unit",
       normalise_unit("rounds per minute") == "rds/min"
       and normalise_unit("rds/min") == "rds/min"
       and normalise_unit("tons") == "t" and normalise_unit("tonnes") == "t")
    ck("a rate of fire the model spells out is NOT refused for its spelling",
       refuse("Rate of fire", "6", "rounds per minute", "",
              "has a rate of fire of 6 rounds per minute") is None,
       refuse("Rate of fire", "6", "rounds per minute", "",
              "has a rate of fire of 6 rounds per minute"))
    ck("nor is a weight the model spells 'tons'",
       refuse("Weight", "47", "tons", "", "the 47 tonne SPH") is None)

    ck("the model disagreeing with the source is refused",
       "the model read" in (refuse("Weight", "47", "km",
                                   "", "the 47 tonne SPH") or ""),
       refuse("Weight", "47", "km", "", "the 47 tonne SPH"))

    # 6. A MISALIGNED BATCH ANSWER IS CAUGHT BY THE QUOTE, not by trusting the index.
    rows_b = [{"subject": "CAESAR", "predicate": "has a range of", "object": "40 km"},
              {"subject": "Archer", "predicate": "has a weight of", "object": "30 tonnes"}]
    swapped = read_batch(rows_b, lambda _p: json.dumps(
        [{"i": 1, "field": "Weight", "value": "30", "unit": "tonnes", "qualifier": None},
         {"i": 2, "field": "Max range", "value": "40", "unit": "km", "qualifier": None}]))
    ck("a batch answer applied to the wrong statement is refused",
       refuse(swapped[0]["field"], swapped[0]["value"], swapped[0]["unit"],
              swapped[0]["qualifier"], rows_b[0]["object"])
       == "the value is not in the quote")
    aligned = read_batch(rows_b, lambda _p: json.dumps(
        [{"i": 1, "field": "Max range", "value": "40", "unit": "km", "qualifier": None},
         {"i": 2, "field": "Weight", "value": "30", "unit": "tonnes", "qualifier": None}]))
    ck("... and the aligned one is not",
       refuse(aligned[0]["field"], aligned[0]["value"], aligned[0]["unit"],
              aligned[0]["qualifier"], rows_b[0]["object"]) is None)
    ck("an index outside the batch is dropped",
       read_batch(rows_b, lambda _p: '[{"i": 9, "field": "Weight", "value": "1"}]') == {})

    # 7. CONSENSUS -- one domain is not a fact.
    one = [dict(field="Max range", value="55", unit="km", qualifier="",
                url="https://blog.example/x", quote="q")]
    ck("a single domain does not make a fact", consensus(one) == [])
    two = one + [dict(field="Max range", value="55", unit="km", qualifier="",
                      url="https://army-technology.com/y", quote="q")]
    ck("two independent domains do", len(consensus(two)) == 1)
    ck("... and the reading carries its sources",
       consensus(two)[0]["domains"] == ["army-technology.com", "blog.example"])

    # 8. TWO DIFFERENT FIGURES FOR ONE FIELD ARE BOTH REPORTED, NOT SILENTLY PICKED.
    mixed = two + [dict(field="Max range", value="40", unit="km", qualifier="conventional",
                        url="https://a.com/1", quote="q"),
                   dict(field="Max range", value="40", unit="km", qualifier="conventional",
                        url="https://b.com/2", quote="q"),
                   dict(field="Max range", value="40", unit="km", qualifier="conventional",
                        url="https://c.com/3", quote="q")]
    c = consensus(mixed)
    ck("two conditional figures for one field are both kept", len(c) == 2, len(c))
    ck("... and the one more independent sources state leads",
       c[0]["value"] == "40" and len(c[0]["domains"]) == 3, c[0]["value"])
    ck("... but the other is not deleted: a conditional figure is still a figure",
       c[1]["value"] == "55")

    print("\n%s" % ("all checks passed" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--probe", default="", help="one product name")
    ap.add_argument("--surfaces", default="", help="comma-separated surfaces for --probe")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--min-domains", type=int, default=2)
    # THE CORPUS AND THE GPU ARE ON DIFFERENT MACHINES. The VPS holds the corpus and
    # has 8 cores at load 8, where one model call takes 38 seconds. --dump collects
    # candidates where the data is; --from-json reads them where the compute is. The
    # checks run on the reading either way, so neither half trusts the other.
    ap.add_argument("--dump", default="", help="write candidates to this file and stop")
    ap.add_argument("--from-json", default="", help="read candidates from this file")
    ap.add_argument("--products", default="",
                    help="for --dump:  name=surface|surface;name=surface")
    a = ap.parse_args()
    if a.demo:
        return demo()

    if a.dump:
        import psycopg2
        cur = psycopg2.connect(DSN).cursor()
        cur.execute("select distinct comp from serving.matchup where comp is not null")
        allprod = [(c or "").split("·")[-1].strip() for (c,) in cur.fetchall()]
        out = {}
        for spec in a.products.split(";"):
            if not spec.strip():
                continue
            name, _, surfs = spec.partition("=")
            surfaces = [x.strip() for x in (surfs or name).split("|") if x.strip()]
            others = [q for q in allprod
                      if q and not any(norm(q) == norm(x) for x in surfaces)]
            rows = candidates(cur, surfaces, others, limit=a.limit)
            out[name.strip()] = rows
            print("  %-14s %d candidate(s)" % (name.strip(), len(rows)))
        json.dump(out, io.open(a.dump, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)
        print("wrote %s" % a.dump)
        return 0

    if a.from_json:
        blob = json.load(io.open(a.from_json, encoding="utf-8"))
        ask = ollama_asker()
        rc = 0
        for name, rows in blob.items():
            print("\n" + "=" * 72)
            rc |= report(name, rows, ask, a.min_domains)
        return rc

    if not a.probe:
        raise SystemExit("--probe NAME, --dump, --from-json or --demo")

    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    surfaces = [s.strip() for s in (a.surfaces or a.probe).split(",") if s.strip()]
    cur.execute("select distinct comp from serving.matchup where comp is not null")
    others = []
    for (comp,) in cur.fetchall():
        p = (comp or "").split("·")[-1].strip()
        if p and not any(norm(p) == norm(s) for s in surfaces):
            others.append(p)

    rows = candidates(cur, surfaces, others, limit=a.limit)
    return report(a.probe, rows, ollama_asker(), a.min_domains)


def report(name, rows, ask, min_domains):
    print("%s: %d proposition(s) whose subject is this product" % (name, len(rows)))
    if not rows:
        return 0
    langs = collections.Counter(r.get("language") or "?" for r in rows)
    print("   languages: %s" % ", ".join("%s %d" % kv for kv in langs.most_common()))

    readings, refused = [], collections.Counter()
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        got = read_batch(chunk, ask)
        for i, r in enumerate(chunk):
            g = got.get(i)
            if not g:
                refused["the model named no measurement"] += 1
                continue
            why = refuse(g["field"], g["value"], g["unit"], g["qualifier"], r["object"])
            if why:
                refused[why] += 1
                continue
            g.update(url=r["url"], quote=r["object"], subject=r["subject"])
            readings.append(g)
        print("   %d/%d read, %d survived"
              % (min(start + BATCH, len(rows)), len(rows), len(readings)), flush=True)

    print("\n%d reading(s) survived the checks, %d refused"
          % (len(readings), sum(refused.values())))
    for why, n in refused.most_common():
        print("   %4d  %s" % (n, why))

    print("\n--- what the corpus states, %d+ independent domains ---" % min_domains)
    for c in consensus(readings, min_domains):
        print("\n  %-14s %s %s%s" % (c["field"], c["value"], c["unit"],
                                     ("  [%s]" % c["qualifier"]) if c["qualifier"] else ""))
        print("       %d mention(s), %d domain(s): %s"
              % (c["n"], len(c["domains"]), ", ".join(c["domains"][:5])))
        print("       %s" % re.sub(r"\s+", " ", c["quote"])[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
