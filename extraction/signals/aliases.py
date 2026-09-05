"""One shared company-identity layer for the KSSL pipeline.

    python aliases.py --demo

The corpus spells one company many ways -- 'Bharat Forge' / 'Bharat Forge Limited' /
'Kalyani group'; 'Rafael' with Defence and Defense; 'HAL' and 'Hindustan Aeronautics'.
Every place that compared names grew its own rule (serving_fill._CLIENT substrings,
enrich_serving.merge_candidates containment, slug equality), so the same firm split
into parallel profiles, escaped dedupe, or ordered wrongly. This module is the single
answer both serving_fill.py and enrich_serving.py import:

  * fold(name)       -- casefold + accent-strip + punctuation-collapse + legal-suffix strip
  * canonical(name)  -- one display name per identity (explicit alias map, then folding)
  * is_client(name)  -- Kalyani / KSSL / Bharat Forge are ONE identity: the CLIENT GROUP.
                        Never a rival, never a 'threat', never in the competitor roster.
  * is_force(name)   -- a country / government / ministry / armed force is NOT a company.
                        The competitor roster and the partnership sides both refuse one.
  * is_one_org(name) -- 'X and Y' in a single-organization field is TWO orgs, refused.
  * same(a, b)       -- identity equality under canonical()
  * merge(names)     -- spellings -> {canonical: set(spellings)}, canonical first, then
                        word-boundary containment ('Saab' absorbs 'Saab Bofors Dynamics')

Kept deliberately small: the alias map holds only identities the corpus/reference data
actually confuses -- it is not a gazetteer.
"""
import html as _html
import re
import unicodedata

CLIENT_CANON = "Kalyani Strategic Systems"

# Any of these appearing in a name marks the CLIENT GROUP (substring on folded text --
# 'Kalyani group', 'Bharat Forge Ltd', 'KSSL (Kalyani Strategic Systems)' all hit).
_CLIENT_MARKS = ("kalyani", "kssl", "bharat forge")
# Public alias. `is_client` answers "is this NAME the client", which is the right
# question about one field and the wrong one about a sentence -- enrich_serving needs
# to ask whether a STATEMENT mentions the client at all, and was one copy-paste away
# from growing a fourth private list of the same three strings.
CLIENT_MARKS = _CLIENT_MARKS

# Trailing legal/corporate suffix tokens stripped by fold(); repeated so
# 'Ltd.' after 'Pvt' also goes. Identity-bearing words (Industries, Group,
# Aerospace, Dynamics...) are NOT here -- stripping those would merge
# different firms.
_SUFFIX = {"limited", "ltd", "pvt", "private", "plc", "inc", "incorporated",
           "corp", "corporation", "co", "company", "ag", "gmbh", "sa", "ab",
           "asa", "oyj", "bv", "nv", "spa", "llc", "llp"}

# folded form -> canonical display name. Only pairs the corpus or the reference
# dataset actually produces.
ALIASES = {
    "kalyani strategic systems": CLIENT_CANON,        # client group: one identity
    "rafael": "Rafael Advanced Defense Systems",
    "rafael advanced defence systems": "Rafael Advanced Defense Systems",
    "rafael advanced defense systems": "Rafael Advanced Defense Systems",
    "hal": "Hindustan Aeronautics",
    "hindustan aeronautics": "Hindustan Aeronautics",
    "iai": "Israel Aerospace Industries",
    "israel aerospace industries": "Israel Aerospace Industries",
    "l and t": "Larsen & Toubro",
    "lt": "Larsen & Toubro",
    "larsen and toubro": "Larsen & Toubro",
    "tasl": "Tata Advanced Systems",
    "tata advanced systems": "Tata Advanced Systems",
    "bel": "Bharat Electronics",
    "bharat electronics": "Bharat Electronics",
    "bdl": "Bharat Dynamics",
    "bharat dynamics": "Bharat Dynamics",
    "brahmos": "BrahMos Aerospace",
    "brahmos aerospace": "BrahMos Aerospace",
    "gdls": "General Dynamics Land Systems",
    "general dynamics land systems": "General Dynamics Land Systems",
    "mahindra defence": "Mahindra Defence",
    "mahindra defense": "Mahindra Defence",
    "hanwha defense": "Hanwha Aerospace",       # merged into Hanwha Aerospace (2022)
    "hanwha defence": "Hanwha Aerospace",
    "hanwha": "Hanwha Aerospace",
    # The roster served HII and Huntington Ingalls Industries as two rival profiles.
    # Neither identity rule in this repo caught it: canonical() has no entry, and the
    # frontend's sameCompany does catch it, which is the point -- two rules, each with
    # a gap the other covers. This is the map's job.
    "hii": "Huntington Ingalls Industries",
    "huntington ingalls industries": "Huntington Ingalls Industries",
    # The Indian ordnance-factory successors file under their legal names and are
    # rostered under their initials. Nothing folded "Advanced Weapons and Equipment
    # India Limited" onto "AWEIL", so 19 published matchups looked as though their
    # maker was off the roster.
    "advanced weapons and equipment india": "AWEIL",
    "aweil": "AWEIL",
    "munitions india": "Munitions India",
    "mil": "Munitions India",
}


# Words that carry no capital inside a real name, so their case says nothing about
# whether the string is a name or a phrase.
_NAME_JOINERS = {"and", "of", "the", "for", "de", "di", "du", "da", "von", "van",
                 "der", "den", "el", "al", "y", "e"}


def unescape(name):
    """'Larsen &amp; Toubro' -> 'Larsen & Toubro'.

    serving.competitors stores that name HTML-escaped, and every identity decision
    in this module reads the raw string. Escaped, it folds to 'larsen amp toubro',
    which stopped matching 'L&T' -- and worse, is_description() saw the lowercase
    'amp' as sentence case and reported a real company as a phrase. A merge run on
    that verdict would have deleted Larsen & Toubro, its signal card and its news.
    Entities are markup, not part of a name, so they come off first.
    """
    return _html.unescape(str(name or ""))


def fold(name):
    """'Bharat Forge Ltd.' -> 'bharat forge'; 'Kalyani Straté-gic' loses accents.
    '&' survives as 'and' so 'L&T' and 'L and T' fold together."""
    s = unicodedata.normalize("NFKD", unescape(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ").replace(".", "")   # 'S.A.' -> 'sa'
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    toks = s.split()
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return " ".join(toks)


def is_client(name):
    """The client group is ONE identity across all its spellings."""
    return any(m in fold(name) for m in _CLIENT_MARKS)


def client_led(text):
    """Is the CLIENT the actor in this headline, whoever the story is filed under?

    `is_client` reads one company field, and that missed the joint announcements:
    two cards titled "Kalyani and Paramount unveil Simha 4x4" were filed under
    "Paramount" and "Paramount Group" and reached the technology feed as rival
    intelligence. The client group is checked in the FIRST HALF of the headline --
    naming the actor -- so a genuine rival move that merely mentions the client
    ("Rheinmetall beats KSSL to a Polish order") is still rival intelligence.
    """
    f = fold(text)
    if not f:
        return False
    head = f[: max(12, len(f) // 2)]
    return any(m in head for m in _CLIENT_MARKS)


# A DIVISION IS NOT A DIFFERENT COMPANY.
#
# The corpus files stories under "American Rheinmetall", "KNDS France", "BAE Systems
# Bofors" and "Hanwha Defense USA"; the roster holds the parent. Strict equality after
# folding sends all of that nowhere, which is most of why 15 of 44 competitors showed
# no news while their divisions' articles sat in the feed.
#
# Containment without a guard is the opposite fault: "Elbit" would absorb Elbit
# Imaging, a real and unrelated company. So the shorter name must appear as a WHOLE
# WORD SEQUENCE in the longer one, and both must be long enough to be distinctive --
# a three-letter fold matches only exactly.
_MIN_CONTAIN = 4


def _via_alias(name):
    """Canonical form, reached through an alias key the name CONTAINS.

    "Hanwha Defense USA" is not a key in ALIASES; "hanwha defense" is, and it is the
    identity-bearing part of the name. A division name is an alias plus a qualifier,
    so the longest alias key sitting whole inside the name decides -- longest first,
    or "rafael" would answer for "rafael advanced defense systems".
    """
    f = fold(name)
    if not f or f in ALIASES:
        return canonical(name)
    for key in sorted(ALIASES, key=len, reverse=True):
        if len(key) >= _MIN_CONTAIN and re.search(
                r"(?:^| )%s(?:$| )" % re.escape(key), f):
            return ALIASES[key]
    return canonical(name)


def same_org(a, b):
    """Are these two spellings the same company, its divisions included?"""
    fa, fb = fold(_via_alias(a) or a), fold(_via_alias(b) or b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    short, long_ = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
    if len(short) < _MIN_CONTAIN:
        return False
    return re.search(r"(?:^| )%s(?:$| )" % re.escape(short), long_) is not None


def canonical(name):
    """One display name per identity. Unknown names keep their own spelling,
    minus the legal suffix (original casing preserved token-wise)."""
    if is_client(name):
        return CLIENT_CANON
    f = fold(name)
    if f in ALIASES:
        return ALIASES[f]
    # keep the caller's casing for the surviving tokens
    kept = [t for t in str(name or "").split()
            if t.lower().strip(".,()").replace(".", "") not in _SUFFIX]
    return " ".join(kept) or str(name or "").strip()


# A country, a government, a ministry or an armed force is not a company. The profile
# prompt already says to reply NONE for one, but a prompt is not a gate: 'US Navy' came
# back as a profiled 'competitor'. Multilingual, because the corpus is (the Swedish
# 'den brasilianska regeringen' was accepted as a named partner organization).
_FORCE_RX = re.compile(
    r"(?<!\w)("
    r"navy|army|air ?force|armed forces|coast ?guard|marine corps|"
    # SINGULAR TOO. "Australian Defence Force" is the ADF -- a buyer -- and only the
    # plural was listed, so it passed every gate and was stored as a supply PARTNER of
    # Rheinmetall MAN. Found by probing the live model against the real corpus, not by
    # any unit test.
    r"defence forces?|defense forces?|self.?defen[cs]e force|"
    r"national guard|national police|gendarmerie|pentagon|"
    r"ministry|ministries|ministere|ministero|ministerio|ministerstvo|"
    r"minist[eè]re|departments? of|department for|"
    r"government|governments|gouvernement|regierung|regering|regeringen|regeringens|"
    r"gobierno|governo|hallitus|vlada|rzad|kormany|kormanya|pravitelstvo"
    r")(?!\w)|"
    r"\w*minister(?:ium|iet|iat)(?:s|e|en)?(?!\w)", re.I)   # German/Nordic compounds


def is_force(name):
    """A country/government/ministry/armed force -- never a company profile, never a
    named partner organization. Folded first, so accents and legal suffixes cannot
    hide the word ('den brasilianska regeringen', 'Ministerstvo obrany')."""
    f = fold(name)
    if not f:
        return False
    return bool(_FORCE_RX.search(f))


def is_one_org(name):
    """False when a single-organization field holds two ('Kalyani and Paramount',
    'Arquus and Daimler Truck'). Only the conjunction splits it -- '&' does not,
    because 'L&T' and 'Kongsberg Defence & Aerospace' are ONE org each."""
    s = str(name or "").strip()
    if not s:
        return False
    return not re.search(r"\s+(and|und|et|y|e|och|ja|oraz|i)\s+", s, re.I)


def has_proper_name(name):
    """A named organization carries at least one capitalised token (or an
    alphanumeric designator). 'den brasilianska regeringen' has neither; it is a
    noun phrase, and the prompt asks for a NAMED organization."""
    for tok in re.findall(r"[^\W_]+", str(name or ""), re.UNICODE):
        if tok[:1].isupper() or any(c.isdigit() for c in tok):
            return True
    return False


def is_description(name):
    """A description lifted from prose, not the name of a company.

    'Israeli robotics' was served as a rival, with one product ('autonomous systems')
    and an assessment reading "The Israeli robotics company is supplying...". The
    source article never names the firm -- it says "an Israeli robotics company" --
    and the extractor turned that indefinite noun phrase into a roster row.

    has_proper_name() cannot catch it: 'Israeli' is capitalised, so the string does
    carry a capitalised token. The tell is the SHAPE of the capitalisation. A named
    organization capitalises its whole name -- Quantum Systems, Shield AI, Elbit
    Systems, Zone 5 Technologies. A phrase carried out of a sentence keeps sentence
    case, capital on the first word and lower case after it.

    So the rule is that asymmetry, and only that: capitalised first token, lowercase
    later one. A brand that is deliberately lowercase ('thyssenkrupp Marine Systems')
    starts lowercase and is not touched -- which is why the rule reads the FIRST token
    rather than counting how many are capitalised.

    Measured over the 156-company roster: one hit, and it is the row this exists for.
    """
    toks = [t for t in re.findall(r"[^\W_]+", unescape(name), re.UNICODE)
            if t.lower() not in _NAME_JOINERS]
    if len(toks) < 2 or not toks[0][:1].isupper():
        return False
    return any(t[:1].islower() for t in toks[1:])


def same(a, b):
    return fold(canonical(a)) == fold(canonical(b)) and bool(fold(a))


def _contains_word(short, long_):
    """word-boundary containment on folded text: 'saab' in 'saab bofors dynamics'
    but never 'mil' in 'military'."""
    return re.search(r"(?<!\w)" + re.escape(short) + r"(?!\w)", long_) is not None


def merge(names):
    """spellings -> {canonical: set(original spellings)}. First by canonical(),
    then a containment pass folds 'Saab Bofors Dynamics' into 'Saab' when the
    short form (>=4 chars) is a whole-word prefix set of the longer."""
    by_canon = {}
    for n in names:
        if not str(n or "").strip():
            continue
        by_canon.setdefault(canonical(n), set()).add(n)
    out = {}
    for canon in sorted(by_canon, key=lambda c: (len(fold(c)), c)):
        fc = fold(canon)
        home = None
        for existing in out:
            fe = fold(existing)
            if len(fe) >= 4 and fe != fc and _contains_word(fe, fc):
                home = existing
                break
        if home:
            out[home] |= by_canon[canon]
        else:
            out[canon] = set(by_canon[canon])
    return out


def _demo():
    assert fold("Bharat Forge Limited") == "bharat forge"
    assert fold("Saab AB") == "saab" and fold("Rafael  Advanced Defence Systems") \
        == "rafael advanced defence systems"
    assert fold("L&T") == "l and t"
    assert fold("Nexter S.A.") == "nexter"
    assert is_client("Bharat Forge Ltd") and is_client("KSSL") \
        and is_client("Kalyani Group") and is_client("kalyani strategic systems limited")
    assert not is_client("Saab") and not is_client("Bharat Electronics")
    # the client as ACTOR, whatever the company column says
    assert client_led("Kalyani and Paramount unveil Simha 4x4 multi-purpose platform")
    assert client_led("KSSL and Paramount unveil Simha 4x4 armoured vehicle")
    assert client_led("Bharat Forge Develops Advanced Indigenous FICVs")
    assert not client_led("Rheinmetall Demonstrates FV-014 LM from CML")
    # ...but a rival's move that merely mentions the client is still rival news
    assert not client_led("Rheinmetall wins the Polish order that KSSL also bid for")
    assert not client_led("") and not client_led(None)
    assert canonical("Bharat Forge Limited") == CLIENT_CANON
    assert canonical("Kalyani") == CLIENT_CANON
    assert canonical("Rafael Advanced Defence Systems") \
        == "Rafael Advanced Defense Systems", "Defence/Defense spellings unify"
    assert canonical("HAL") == "Hindustan Aeronautics"
    assert canonical("Saab AB") == "Saab", "unknown names lose only the legal suffix"
    assert canonical("Unheard-of Corp") == "Unheard-of"
    assert same("Bharat Forge", "Kalyani Strategic Systems Limited")
    assert same("Saab", "Saab AB") and not same("Saab", "Thales")
    assert not same("", "")
    m = merge({"Bharat Forge", "Bharat Forge Limited", "Kalyani", "Saab",
               "Saab Bofors Dynamics", "Munitions India"})
    assert m[CLIENT_CANON] == {"Bharat Forge", "Bharat Forge Limited", "Kalyani"}
    assert m["Saab"] == {"Saab", "Saab Bofors Dynamics"}, "containment folds"
    assert "Munitions India" in m
    assert canonical("Hanwha Defense") == canonical("Hanwha Aerospace"),         "the corpus splits Hanwha two ways"
    # a country / government / ministry / armed force is not a company (audit M9/M10)
    assert is_force("US Navy") and is_force("Indian Army") and is_force("U.S. Air Force")
    assert is_force("Ministry of Defence") and is_force("Ministerstvo obrany")
    assert is_force("US Department of State") and is_force("Department for Transport")
    assert is_force("Gendarmerie Nationale") and is_force("the Pentagon")         and is_force("National Police"), "gendarmerie/pentagon/national police are forces too"
    assert is_force("den brasilianska regeringen"), "the Swedish 'the Brazilian government'"
    assert is_force("Bundesministerium der Verteidigung"), "German compounds fold in too"
    assert not is_force("Saab") and not is_force("Bharat Forge")         and not is_force("Northrop Grumman"), "real companies must survive the check"
    assert not is_force("Armscor"), "'arm' must not match inside a word"
    # one field, one organization
    assert not is_one_org("Kalyani and Paramount") and not is_one_org("Arquus and Daimler Truck")
    assert not is_one_org("Rheinmetall och Leonardo"), "the conjunction is multilingual too"
    assert is_one_org("Kongsberg Defence & Aerospace"), "'&' is one org, not two"
    assert is_one_org("Larsen & Toubro") and is_one_org("Saab") and not is_one_org("")
    assert has_proper_name("Aalto-yliopisto") and has_proper_name("BrahMos")
    assert has_proper_name("155mm barrels"), "an alphanumeric designator names a thing"
    assert not has_proper_name("den brasilianska regeringen")
    assert not has_proper_name("circuit cards") and not has_proper_name("logistics trucks")

    # --- is_description: a phrase carried out of a sentence, not a company ---------
    # The roster row this exists for. The article says "an Israeli robotics company"
    # and never names the firm; has_proper_name passes it, because 'Israeli' is
    # capitalised, so the tell has to be the shape of the capitalisation.
    assert is_description("Israeli robotics")
    assert is_description("Turkish shipyard") and is_description("European defence firm")
    # real names capitalise all the way through, including the awkward ones
    for real in ("Quantum Systems", "Shield AI", "Elbit Systems", "Zone 5 Technologies",
                 "Bharat Electronics", "Larsen & Toubro", "Huntington Ingalls Industries",
                 "Indo-Russian Rifles", "X-Bow Systems", "Fairbanks Morse Defense"):
        assert not is_description(real), real
    # a deliberately lowercase brand starts lowercase, so the rule never reads it as
    # sentence case -- this is why the first token is checked rather than a count
    assert not is_description("thyssenkrupp Marine Systems")
    # joiners carry no capital in a real name and must not trip it
    assert not is_description("Ministry of Defence".replace("Ministry", "Kongsberg"))
    assert not is_description("Bank of the West".replace("Bank", "Rolls"))
    # too short to have a shape
    assert not is_description("Saab") and not is_description("") and not is_description(None)

    # --- the two rows the roster served twice --------------------------------------
    # serving.competitors stores this name escaped, and every rule here must see
    # through that -- the merge dry run reported Larsen & Toubro as "a phrase, not a
    # company" and would have deleted it
    assert not is_description("Larsen &amp; Toubro")
    assert same("L&T", "Larsen &amp; Toubro")
    assert fold("Larsen &amp; Toubro") == fold("Larsen & Toubro")
    assert canonical("Larsen &amp; Toubro") == "Larsen & Toubro"

    assert same("HII", "Huntington Ingalls Industries")
    assert same("BEL", "Bharat Electronics")
    assert same("L&T", "Larsen & Toubro")
    # and the ones that only LOOK like duplicates
    assert not same("Bharat Dynamics", "Bharat Electronics")
    assert not same("Elbit America", "Elbit Systems")
    assert not same("Indra Land Vehicles", "Indra Group")
    m2 = merge({"MIL", "Military Vehicles Corp"})
    assert len(m2) == 2, "short forms never absorb by substring, whole word only"
    assert _contains_word("saab", "saab bofors") and not _contains_word("mil", "military")
    print("ok")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.parse_args()
    _demo()
