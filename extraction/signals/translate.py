"""One place that turns source-language text into English, for the serving layer.

    from translate import translate_to_english, translate_lines
    translate_to_english("sette veicoli sono forniti", "it")   -> "seven vehicles are supplied"
    translate_to_english("Leonardo signed a contract")         -> unchanged, no model call

WHAT IS AND IS NOT THE PUBLISHER'S WORDS. `extracted.proposition.ev_quote` is located
in the article by offset (comprehend.locate; ev_start/ev_end are NOT NULL in the
schema) -- it is provably the publisher's sentence, and translating it would put words
inside quotation marks that nobody wrote. subject/predicate/object are NOT located:
comprehend asks for "a SHORT phrase, max 6 words", caps them at 160/80/160 characters
and never anchors them. They are the extraction model's own paraphrase. Translating a
paraphrase invents nothing, so the lead-in is translated and the quote never is.

The defect this exists for is not "foreign documents produce foreign text". The
extraction prompt tells the model to write gloss and in_article in English and to copy
text and evidence verbatim, and says NOTHING about subject/predicate/object -- so the
model picks per triple, and often per WORD. Measured on staging:

    "sette veicoli ruotati 8x8 Centauro II are forniti"
    "Il Centauro II is a evoluzione piu avanzata di questo modello di veicolo blindato"

An English verb welded to an Italian subject and object. A document-language gate
cannot see this: the document is `it`, but a document labelled `en` can carry the same
thing, and 34% of propositions on non-English documents are already fully English. So
the gate is on the STRING, not the document, and it is enrich_serving.is_english() --
the one already used for exactly this judgement -- not a second detector library.

REFUSAL IS ALWAYS AN OPTION AND ALWAYS RETURNS THE ORIGINAL. A translation is dropped
when it comes back non-English, when it loses a number the input stated, when it loses
a designator, or when it was answered by anything but the farm. The worst case is
what the tab shows today.
"""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import llmapi                                                           # noqa: E402
# NOTHING ELSE FROM THIS PACKAGE IS IMPORTED HERE, ON PURPOSE. serving_fill imports
# this module, and enrich_serving imports serving_fill, so reaching back for
# enrich_serving.is_english() closed a cycle that broke seven test files and the CI
# gate. It would have been the wrong function anyway -- see looks_translated().

# THE SERVING MODEL, NOT THE 7B. llmapi ignores the caller's `model=` and asks whatever
# C_MODEL aliases on the farm; when the farm is down it answers from a 7b on a CPU box
# and says so in meta["via"]. serving_fill.ask() throws that field away, so the standing
# rule -- serving tables are written by the 14B -- is enforced by nothing in code. Here
# it is enforced: an answer that did not come from the farm is refused, not stored.
FARM_ONLY = os.environ.get("KSSL_TRANSLATE_FARM_ONLY", "1") != "0"
MAX_CHARS = int(os.environ.get("KSSL_TRANSLATE_MAX_CHARS") or 4000)
PROMPT_VERSION = "t1"

# A digit group, and a designator: "155mm", "8x8", "Su-30MKI", "K9", "MkII", "AS565 MBe".
# Both must survive the round trip or the translation is refused.
NUM_RX = re.compile(r"\d[\d.,]*")
DESIG_RX = re.compile(r"\b(?:[A-Z]{1,4}[- ]?\d{1,4}[A-Za-z]{0,4}|\d{1,4}\s?[xX×]\s?\d{1,4}|"
                      r"Mk\s?[IVX0-9]+)\b")

_PROMPT = """Translate each numbered line into English.

RULES
- Output exactly one line per input line, numbered the same way. Nothing else.
- A line already in English is copied out unchanged.
- Keep every number, date, quantity, calibre, unit and designator exactly as written.
- Keep proper nouns as written: companies, agencies, people, places, programmes.
- KEEP THESE EXACTLY AS WRITTEN, they are product names even where they are also
  ordinary words in their own language: %s
- Translate only. Do not summarise, explain, correct, expand or add anything.
- A line that mixes languages is still translated: put ALL of it into English.
- An abbreviation written in another alphabet becomes its English equivalent, or a
  transliteration when it has no English form: MЗС України -> Ukraine's MFA,
  OOH -> UN, MKЧX -> ICRC.
- If you cannot translate a line, copy it out unchanged.

LINES
%s"""

# Names that are ordinary words in their own language, which is how a translator turns
# a vehicle into an animal. Polish AFVs are animals almost as a rule; so are German and
# Hebrew ones. This list is the floor -- the caller passes the document's own
# Product/WeaponSystem/Platform spans, which is where the real coverage comes from.
KEEP_ALWAYS = ("Rosomak", "Borsuk", "Krab", "Rak", "Kryl", "Piorun", "Grot", "Bor",
               "Kaplan", "Kirpi", "Pars", "Altay", "Akinci", "Bayraktar",
               "Namer", "Merkava", "Eitan", "Barak", "Iron Dome", "David's Sling",
               "Fuchs", "Wiesel", "Marder", "Luchs", "Puma", "Boxer", "Leopard",
               "Centauro", "Freccia", "Lince", "Ariete", "Dardo",
               "Griffon", "Jaguar", "Serval", "Caesar", "Rafale", "Mirage",
               "Piranha", "Eagle", "Cougar", "Panther", "Tiger", "Gepard")


def _keep_list(extra=()):
    seen, out = set(), []
    for n in list(extra) + list(KEEP_ALWAYS):
        n = (n or "").strip()
        if n and len(n) > 2 and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:60]                       # a prompt, not a dictionary


def _kept(text):
    """The tokens a faithful translation must still contain."""
    return set(NUM_RX.findall(text or "")) | set(DESIG_RX.findall(text or ""))


# Function words that are never English. An output still carrying these is an echo of
# the source, not a translation. This is the OPPOSITE test from is_english(): it looks
# for evidence of a foreign language rather than evidence of English, which is the only
# test that works on a three-word triple.
_FOREIGN_FUNC = set("""der die das den dem des und ist sind war waren ein eine einen einem
nicht mit von zu fuer ueber auch bei nach aus dass wird werden wurde haben hat sich noch nur
le la les un une des du de et est sont etait pour dans par sur avec au aux ce cette ces qui
que plus pas ne son sa ses leur comme tout tous fut ete
el los las una unos unas y es son era para por con del al se no lo su sus pero mas muy fue
il lo gli uno di da in su per tra fra sono che non piu anche questo questa quello quella dei
delle della nel nella sul sulla agli alle come stato stata
o os as uma um dos das nao mais mas muito ja pelo pela
het een van en zijn niet met voor door op aan bij ook maar dan werd werden
i w z na do nie sie jest sa oraz przez dla ktory ktore tego tym jako zostal
och att som med foer paa den det ett inte var har till om men blev
ve bir bu ile icin olarak da de daha cok ancak
im zum zur vom beim als oder durch gegen ohne um eines einer dieser diese dieses wurden
sowie bereits sein seine seiner ihre ihren dabei damit sollen kann koennen
aux ceux celle celles leurs notre votre dont ainsi afin lors meme encore toujours
sus cual cuales entre sobre hacia desde tambien segun aunque
degli dalla dallo negli nelle sugli quali quale inoltre percio quindi
pelos pelas nos nas aos ao pela pelo aquele aquela
naar zoals waarbij tussen onder tijdens echter terwijl
ktorych ktorym wraz podczas jednak takze poniewaz
vilket vilka dessa denna detta samt eftersom
olan olan bunun icinde uzere gore""".split())
# ...minus every token that is also an ordinary English word. A defence corpus is full
# of "war", "in", "as", "per", "come", "van" and "no"; leaving them in cost 9 of 600
# real English lead-ins, refused as foreign. A word has to be evidence of another
# language to count as evidence.
_FOREIGN_FUNC -= set("""a i o no in as at on to so do de da du des van war son come plus per
man men den la le el es al se me my be he we us it its non via sur tout est are and or the
of for with from by been over under new all any both each more most same some
""".split())


def _foreign_hits(text):
    toks = re.findall(r"[^\W\d_]+", str(text or "").lower(), re.UNICODE)
    return [t for t in toks if t in _FOREIGN_FUNC]


def looks_translated(text):
    """Is this string servable as English? A gate built for a THREE-WORD TRIPLE.

    is_english() is the wrong test here and measurement says so: it requires English
    function words, and 16.3% of the real English lead-ins on staging have none --
    "Warsaw ordered 32 F-35s", "Peru imported cluster munitions", "Compliance Program
    establishes fair-trade culture". Using it as the output gate would refuse one good
    translation in six and serve the foreign original in its place.

    So this tests for evidence of a FOREIGN language instead of evidence of English:
    a non-Latin script, a run of accented words, or foreign function words. A terse
    English triple trips none of them."""
    t = str(text or "")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.12:
        return False                                  # Cyrillic, Hebrew, CJK, Arabic
    hits = _foreign_hits(t)
    toks = re.findall(r"[^\W\d_]+", t, re.UNICODE)
    if not toks:
        return True
    # One hit is a loanword or a name ("Direction generale de l'armement", "von
    # Braun"); two or a tenth of the string is a sentence in another language.
    return len(hits) < 2 or len(hits) / len(toks) < 0.10


def verdict(src, out):
    """-> (ok, reason). Why a translation is refused, so a caller can count them."""
    if not out or not out.strip():
        return False, "empty"
    if out.strip() == (src or "").strip():
        return True, "unchanged"
    if not looks_translated(out):
        return False, "not_english"
    lost = _kept(src) - _kept(out)
    if lost:
        return False, "lost:" + ",".join(sorted(lost)[:3])
    return True, "ok"


def needs_english(text, source_language=None):
    """Should this string be sent to the model at all? Two arms, and both are needed.

    IS_ENGLISH CANNOT SEE CODE-SWITCHING, and code-switching is the defect. It was
    written to reject a wholly foreign label, so it scores non-ASCII letters and
    English function words -- and "sette veicoli ruotati 8x8 Centauro II are forniti"
    has no non-ASCII letter and contains "are", so it passes as English. As a gate on
    the model's OUTPUT that is the right function; as a gate on the input it is blind
    to exactly the row this module exists for.

    So the document's language decides whether to ASK, and the string decides only when
    there is no language to go on. A non-English document costs one call per card
    whatever its lines look like -- the prompt tells the model to copy English lines out
    unchanged, and 34% of them are already English, which `verdict` records as
    "unchanged" rather than a translation."""
    t = (text or "").strip()
    if not t:
        return False
    if len(t) > MAX_CHARS:
        return False                      # never chunk prose we would then reassemble
    lang = (source_language or "").strip().lower()[:2]
    if lang and lang != "en":
        return True
    # No language to go on -- 119 served cards have no extracted.document row at all.
    # The string is all there is, and looks_translated() is the gate built for this
    # shape; is_english() would call "Leonardo signed a production contract" foreign,
    # for want of a function word, and send every terse English triple to the model.
    return not looks_translated(t)


def _ask(prompt):
    """-> (text, via). Raises on transport failure; the caller decides what that means."""
    text, meta = llmapi.client.ask(prompt, npredict=900, with_meta=True)
    return text, (meta or {}).get("via")


def translate_lines(lines, source_language=None, keep=(), stats=None):
    """Translate a batch in ONE model call, preserving order and length.

    A card renders up to six statements. Six calls at ~7s each would add ~40s to a
    document that holds a signal_seen claim while it runs; one call adds ~8s. Any line
    that fails its own verdict keeps its original, so a single bad line cannot take the
    other five down with it."""
    out = list(lines)
    idx = [i for i, t in enumerate(lines) if needs_english(t, source_language)]
    def bump(k, n=1):
        if stats is not None:
            stats[k] = stats.get(k, 0) + n
    bump("seen", len(lines))
    if not idx:
        bump("already_english", len(lines))
        return out
    bump("asked", len(idx))
    body = "\n".join("%d. %s" % (n + 1, lines[i].replace("\n", " "))
                     for n, i in enumerate(idx))
    try:
        raw, via = _ask(_PROMPT % (", ".join(_keep_list(keep)) or "(none)", body))
    except Exception as exc:                                          # noqa: BLE001
        bump("failed")
        bump("err:" + type(exc).__name__)
        return out                        # the original, never an invention
    if FARM_ONLY and via != "farm":
        # A 7b on a CPU box must not write a serving row. Not cached, not stored: the
        # farm flaps, and the next pass should ask it again.
        bump("refused_backend")
        return out
    got = {}
    for line in (raw or "").splitlines():
        m = re.match(r"\s*(\d+)[.)]\s*(.+?)\s*$", line)
        if m:
            got[int(m.group(1))] = m.group(2)
    for n, i in enumerate(idx):
        cand = got.get(n + 1)
        if cand is None:
            bump("no_line")
            continue
        ok, why = verdict(lines[i], cand)
        if ok:
            out[i] = cand
            bump("translated" if why != "unchanged" else "model_said_unchanged")
        else:
            bump("refused")
            bump("refused_" + why.split(":")[0])
    return out


def translate_to_english(text, source_language=None, keep=(), stats=None):
    """The single-string form of translate_lines. Returns the original on any doubt."""
    if not text or not str(text).strip():
        return text
    return translate_lines([str(text)], source_language, keep, stats)[0]


def _demo():
    # --- the gate: what gets asked at all -----------------------------------------
    assert not needs_english(""), "empty asks nothing"
    assert not needs_english(None), "None asks nothing"
    assert not needs_english("   "), "blank asks nothing"
    assert not needs_english("x" * (MAX_CHARS + 1)), "absurdly long is left alone"
    # already English -> no model call, which is what makes this idempotent: running
    # the pass twice cannot re-translate its own output.
    assert not needs_english("Leonardo signed a production contract with the Brazilian Army")
    # THE ROW THIS EXISTS FOR, and it is mixed, not foreign: an English verb welded to
    # an Italian subject and object. The document's language is what catches it...
    assert needs_english("sette veicoli ruotati 8x8 Centauro II are forniti", "it")
    # ...and this is the honest limit: with no language to go on, is_english sees "are",
    # finds no non-ASCII letter, and calls it English. A card whose document row was
    # pruned (119 of them on staging) keeps a mixed lead-in. Stated, not hidden.
    assert not needs_english("sette veicoli ruotati 8x8 Centauro II are forniti")
    # Wholly foreign text is caught with or without a language.
    assert needs_english("Il Centauro II e la evoluzione piu avanzata di questo modello")
    assert needs_english("Обсяг першої поставки біометану до ЄС становив 67 тис.")
    assert needs_english("Leonardo signed a production contract", "it"), \
        "a non-English document asks for every line; the model copies English ones out"

    # --- the verdict: what is allowed to be stored --------------------------------
    src = "Rheinmetall liefert 155-mm-Munition im Wert von 120 Millionen Euro"
    assert verdict(src, "Rheinmetall delivers 155-mm ammunition worth 120 million Euro")[0]
    # A NUMBER THAT DID NOT SURVIVE IS A DIFFERENT CLAIM, not a rough translation.
    ok, why = verdict(src, "Rheinmetall delivers ammunition worth 120 million Euro")
    assert not ok and why.startswith("lost:"), why
    ok, why = verdict(src, "Rheinmetall delivers 155-mm ammunition worth 12 million Euro")
    assert not ok, "120 -> 12 must be refused"
    # a designator that vanished
    ok, why = verdict("The Su-30MKI fleet was upgraded", "The fleet was upgraded")
    assert not ok and why.startswith("lost:"), why
    # output still in the source language: the model echoed instead of translating
    assert not verdict(src, "Rheinmetall liefert 155-mm-Munition im Wert von 120 Mio")[0]
    assert not verdict(src, "")[0], "empty output is a refusal, not a translation"
    # a line the model was told to copy out unchanged is fine, not a failure
    assert verdict("Boxer is armoured personnel carrier",
                   "Boxer is armoured personnel carrier") == (True, "unchanged")

    # --- batch shape --------------------------------------------------------------
    # No network in the demo: a stub stands in for the farm.
    saved = globals()["_ask"]
    calls = []

    def fake(prompt):
        """Stands in for the farm, obeying the prompt: an English line is copied out
        unchanged, anything else comes back as English."""
        calls.append(prompt)
        out = []
        for line in prompt.split("LINES\n", 1)[1].splitlines():
            m = re.match(r"\s*(\d+)[.)]\s*(.+)$", line)
            if not m:
                continue
            body = m.group(2)
            english = body.startswith("Leonardo signed a production")
            out.append("%s. %s" % (m.group(1), body if english
                                   else "the vehicle was delivered to the army in 2024"))
        return "\n".join(out), "farm"

    globals()["_ask"] = fake
    st = {}
    src_lines = ["Leonardo signed a production contract with the Brazilian Army",
                 "sette veicoli ruotati sono forniti",
                 "due veicoli del lotto iniziale sono consegnati"]
    out = translate_lines(src_lines, "it", stats=st)
    assert len(out) == 3, "length is preserved"
    assert len(calls) == 1, "ONE call for the whole card, not one per line"
    # A non-English DOCUMENT sends every line, because a document label cannot tell
    # which of its lines the extraction model already wrote in English...
    assert st["asked"] == 3, st
    assert "1. Leonardo signed" in calls[0] and "2. sette veicoli" in calls[0]
    # ...and the English one comes back untouched, recorded as such rather than as a
    # translation, so the counters do not overstate the work.
    assert out[0] == src_lines[0], "an English line survives the round trip unaltered"
    assert st.get("model_said_unchanged") == 1 and st.get("translated") == 2, st

    # WITH NO LANGUAGE, THE STRING IS ALL THERE IS, AND IT IS NOT ENOUGH. The clearly
    # foreign line goes; "sette veicoli ruotati sono forniti" carries one function word
    # in five and passes. That is the measured recall limit of a stdlib gate on a
    # five-word phrase, and it is exactly why the document-language arm exists -- 192
    # of the 311 served non-English cards have a language, and take the arm above.
    calls.clear(); st = {}
    out = translate_lines(src_lines, None, stats=st)
    assert st["asked"] == 1, st
    assert "Leonardo" not in calls[0], "an English line is not even put in the prompt"
    assert "lotto iniziale" in calls[0], "the clearly foreign line is"

    # ONE BAD LINE MUST NOT TAKE THE OTHERS DOWN. Line 2 comes back having lost its
    # number; line 1 is fine.
    def half_bad(prompt):
        # line 1 is a good translation; line 2 silently drops the quantity, which is a
        # different claim about a contract, not a rough edge.
        return ("1. seven 8x8 wheeled vehicles are supplied\n"
                "2. vehicles of the evaluation lot are delivered"), "farm"

    globals()["_ask"] = half_bad
    st = {}
    src2 = ["sette veicoli 8x8 sono forniti", "due veicoli 2 del lotto sono consegnati"]
    out = translate_lines(src2, "it", stats=st)
    assert out[0] == "seven 8x8 wheeled vehicles are supplied", \
        "a good line is stored even though its neighbour was refused"
    assert out[1] == src2[1], "the refused line keeps its original, untranslated"
    assert st.get("refused") == 1 and st.get("refused_lost") == 1, st

    # THE 7B MUST NOT WRITE A SERVING ROW. Same good answer, wrong backend.
    globals()["_ask"] = lambda p: ("1. the vehicle was delivered to the army in 2024", "vps-a")
    st = {}
    out = translate_lines(["sette veicoli sono forniti"], "it", stats=st)
    assert out == ["sette veicoli sono forniti"], "a fallback answer is refused outright"
    assert st.get("refused_backend") == 1, st

    # A TRANSPORT FAILURE RETURNS THE ORIGINAL, never a partial or an invention.
    def boom(prompt):
        raise RuntimeError("farm on fire")

    globals()["_ask"] = boom
    st = {}
    assert translate_to_english("sette veicoli sono forniti", "it", stats=st) \
        == "sette veicoli sono forniti"
    assert st.get("failed") == 1, st

    # IDEMPOTENCE, stated exactly. Feeding the output back must not alter it. With a
    # non-English document label it still costs a call -- the label describes the
    # document, not the line -- but the model copies English out unchanged and that is
    # recorded as "unchanged" rather than as a translation. With no label it costs
    # nothing at all, because the string gate sees English and never asks.
    globals()["_ask"] = fake
    once = translate_lines(["Leonardo signed a production contract"], "it")
    assert once == ["Leonardo signed a production contract"]
    st = {}
    assert translate_lines(once, "it", stats=st) == once, \
        "re-translating English text must not alter it"
    assert st.get("model_said_unchanged") == 1 and not st.get("translated"), st
    st = {}
    assert translate_lines(once, None, stats=st) == once
    assert not st.get("asked"), "with no document language it costs no call at all"

    globals()["_ask"] = saved

    # --- the keep-list ------------------------------------------------------------
    # Rosomak is a wolverine, Namer is a leopard, Fuchs is a fox. A translator that
    # does not know they are vehicles turns an armoured column into a zoo.
    kl = _keep_list(["Rosomak", "K9 Thunder"])
    assert "Rosomak" in kl and "K9 Thunder" in kl and "Namer" in kl
    assert len(_keep_list(["x" * 3] * 200)) <= 60, "the prompt stays a prompt"
    assert _keep_list(["Rosomak", "rosomak"]).count("Rosomak") == 1, "deduped"
    print("ok")


if __name__ == "__main__":
    _demo()
