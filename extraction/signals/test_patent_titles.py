# -*- coding: utf-8 -*-
"""The patent-title translation pass: what it sends, what it writes, what it never touches.

    python test_patent_titles.py

Hermetic. The database is a stub that records the statements it is given and the model
is a stub that records the lines it is asked about -- which is the point: the two things
most worth pinning are a model call that should NOT happen and a column that should NOT
be written, and neither is visible from the outside of a real run.

WHAT THIS GUARDS.

  1. AN ENGLISH TITLE IS NEVER SENT. 1,014 of the 1,183 stored titles are already
     English. A pass that asks about all of them still produces the right rows -- the
     model answers "unchanged" and nothing is stored -- so the waste is invisible in the
     output and shows up only as farm time. That is exactly how the signal_detail
     backfill came to burn ~17 minutes a cycle producing no change.

  2. THE OFFICE'S OWN TITLE SURVIVES. The English rendering goes in its own column. An
     UPDATE that assigned to `title` would be undetectable a week later: the source
     string it overwrote is not recoverable from anything the dashboard stores.

  3. A REFUSED TRANSLATION STORES NOTHING AND STILL STAMPS. translate.py returns the
     ORIGINAL when it refuses (not English, a number dropped, not from the farm), so
     "the answer equals the input" is the refusal signal -- and writing that into
     title_en would publish the untranslated title as though it had been checked. The
     row must still be stamped, or the window stops advancing and re-asks the same rows
     for ever, which is the fault serving_fill.retranslate() was fixed for.
"""
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import translate                                                        # noqa: E402
import patent_titles                                                    # noqa: E402

fails = []


def _ascii(x):
    """A failure detail here can be a Korean patent title, and a Windows console is
    cp1252. A test that dies while PRINTING a failure reports a crash instead of the
    assertion that failed -- which is what this did on the first regression run."""
    return str(x).encode("ascii", "backslashreplace").decode("ascii")


def check(name, ok, detail=""):
    print("  %-68s %s%s" % (name, "PASS" if ok else "FAIL",
                            "  " + _ascii(detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


# --------------------------------------------------------------------------- stubs
class FakeCur(object):
    def __init__(self, rows):
        self.rows = rows
        self.selects = []
        self.updates = []
        self._out = []

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("SELECT"):
            self.selects.append((sql, params))
            self._out = [dict(r) for r in self.rows]
        else:
            self.updates.append((sql, params))

    def fetchall(self):
        return self._out


class FakeCon(object):
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0

    def cursor(self, **_kw):
        return self._cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def install_fake_db(rows):
    cur = FakeCur(rows)
    con = FakeCon(cur)
    mod = types.ModuleType("psycopg2")
    mod.connect = lambda *_a, **_k: con
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    mod.extras = extras
    sys.modules["psycopg2"] = mod
    sys.modules["psycopg2.extras"] = extras
    return cur, con


def install_fake_model(answers):
    """answers: {source title -> what the model returns}. Records every ASK."""
    asked = []
    real = translate.translate_lines

    def fake(lines, source_language=None, keep=(), stats=None, ask=None):
        # THE STUB MUST TAKE THE SAME ARGUMENTS THE REAL ONE DOES, or it hides the
        # difference between "the pass sent this line" and "the pass sent it and the
        # real gate dropped it". The check below drives the REAL translate_lines for
        # exactly that reason.
        asked.append((source_language, list(lines), ask))
        if stats is not None:
            stats["asked"] = stats.get("asked", 0) + len(lines)
            stats["translated"] = stats.get("translated", 0) + len(lines)
        # translate_lines returns the ORIGINAL for any line it refuses
        return [answers.get(t, t) for t in lines]

    translate.translate_lines = fake
    return asked, real


ROWS = [
    # already English -- must never be asked about
    {"ord": 1, "no": "US1", "title": "Armour plate assembly for a combat vehicle",
     "country": "US", "title_en": None},
    # German, by both arms
    {"ord": 2, "no": "DE1", "title": "Verfahren zur Herstellung eines Rohres",
     "country": "DE", "title_en": None},
    # Spanish: no diacritic, no listed function word -- caught only by provenance
    {"ord": 3, "no": "ES1", "title": "Sistema de armas", "country": "ES",
     "title_en": None},
    # Korean script
    {"ord": 4, "no": "KR1", "title": u"장갑차용 포탑",
     "country": "KR", "title_en": None},
    # foreign, but the model will refuse it (returns the original)
    {"ord": 5, "no": "DE2", "title": "Vorrichtung und Verfahren", "country": "DE",
     "title_en": None},
    # nothing to translate
    {"ord": 6, "no": "US2", "title": "   ", "country": "US", "title_en": None},
]
ANSWERS = {
    "Verfahren zur Herstellung eines Rohres": "Method for producing a tube",
    "Sistema de armas": "Weapon system",
    u"장갑차용 포탑": "Turret for an armoured vehicle",
    # "Vorrichtung und Verfahren" deliberately absent -> comes back unchanged = refused
}

cur, con = install_fake_db(ROWS)
asked, real_lines = install_fake_model(ANSWERS)
try:
    stats = patent_titles.translate_titles(dsn="postgresql://stub", apply=True,
                                           verbose=False)
finally:
    translate.translate_lines = real_lines

sent = [t for _lang, lines, _ask in asked for t in lines]

# --- 1. what was sent -------------------------------------------------------------
check("the already-English title is never sent to the model",
      "Armour plate assembly for a combat vehicle" not in sent, sent)
check("a blank title is never sent", not any(not t.strip() for t in sent), sent)
check("the German title is sent", "Verfahren zur Herstellung eines Rohres" in sent)
check("the Korean title is sent", u"장갑차용 포탑" in sent)
check("the Spanish title, invisible to the string gate, is sent on its office",
      "Sistema de armas" in sent, sent)
check("exactly the four foreign titles are sent, no more", len(sent) == 4, sent)
check("batches are grouped by language, one language per call",
      sorted(lang for lang, _l, _a in asked) == ["de", "es", "ko"],
      [lang for lang, _l, _a in asked])

# --- 2. what was written ----------------------------------------------------------
by_ord = {}
for sql, params in cur.updates:
    by_ord.setdefault(params[-1], []).append((sql, params))

check("every row in the window is stamped, English ones included",
      sorted(by_ord) == [1, 2, 3, 4, 5, 6], sorted(by_ord))
check("the stamp is the current prompt version",
      all(p[1] == translate.PROMPT_VERSION for _s, p in cur.updates),
      [p[1] for _s, p in cur.updates])

written = {o: v[0][1][0] for o, v in by_ord.items()}
check("the German translation is stored", written[2] == "Method for producing a tube",
      written)
check("the Spanish translation is stored", written[3] == "Weapon system")
check("the Korean translation is stored", written[4] == "Turret for an armoured vehicle")
check("an already-English row stores no translation", written[1] is None, written[1])
check("a REFUSED translation stores nothing rather than the untranslated title",
      written[5] is None, written[5])
check("... and the refused row is still stamped, so the window advances",
      5 in by_ord)

# --- 3. what was NOT touched ------------------------------------------------------
assigns = re.compile(r"\btitle\s*=", re.I)
check("no statement assigns to `title` -- the office's own words are never overwritten",
      not any(assigns.search(s.replace("title_en", "")) for s, _p in cur.updates),
      [s for s, _p in cur.updates][:1])
check("the write is COALESCEd, so a stamp cannot blank an existing translation",
      all("COALESCE" in s.upper() for s, _p in cur.updates))
check("it commits per row, so a pass that dies has still made progress",
      con.commits >= len(cur.updates), con.commits)

# --- 4. the window ----------------------------------------------------------------
sel_sql, sel_params = cur.selects[0]
check("the SELECT filters on the version stamp, not on offset",
      "title_en_v IS DISTINCT FROM" in sel_sql and "OFFSET" not in sel_sql.upper())
check("... and asks for the current prompt version",
      translate.PROMPT_VERSION in sel_params, sel_params)
check("... oldest-stamped first, so a re-run continues rather than restarts",
      "ORDER BY title_en_v NULLS FIRST" in sel_sql)
check("... and only pipeline rows (the 26 curated reference rows are not ours)",
      "origin = 'pipeline'" in sel_sql)
check("... taking a row lock that three replicas cannot fight over",
      "FOR UPDATE SKIP LOCKED" in sel_sql)
check("the stats report what happened",
      stats["written"] == 3 and stats["skipped_english"] == 2, stats)

# --- 5. a dry run writes nothing --------------------------------------------------
cur2, con2 = install_fake_db(ROWS)
asked2, real_lines = install_fake_model(ANSWERS)
try:
    patent_titles.translate_titles(dsn="postgresql://stub", apply=False, verbose=False)
finally:
    translate.translate_lines = real_lines
check("without --apply nothing is written at all", cur2.updates == [], cur2.updates)
check("... but the model is still asked, so the preview is the real answer",
      len([t for _l, lines, _a in asked2 for t in lines]) == 4)

# --- 6. the gate the pass hands over is the gate that is USED --------------------
# THE ARM THAT WAS INERT. translate_lines re-gates every line on needs_english(), which
# is calibrated for thirty-word lead-ins and wants two foreign function words. A patent
# title has six words: "Dispositif de protection balistique pour vehicule" carries one
# (`de` is excluded as an ordinary English token), so the shared gate calls it English.
# patent_titles selects it by DENSITY -- and, until translate_lines grew `ask`, passed
# it in only for translate_lines to drop it again on its own gate, while this pass
# counted it as a candidate. A model call that never happens, logged as one that did.
#
# So this drives the REAL translate_lines, with only the transport stubbed.
FRENCH = "Dispositif de protection balistique pour vehicule"
check("the shared gate really does miss a short foreign title (else drop the arm)",
      not translate.needs_english(FRENCH, None))
check("patent_titles catches it anyway", patent_titles.title_needs_english(FRENCH, None))

seen = []
real_ask, real_farm = translate._ask, translate.FARM_ONLY
translate._ask = lambda prompt: (seen.append(prompt) or
                                 ("1. Ballistic protection device for a vehicle", "farm"))
try:
    st = {}
    out = translate.translate_lines([FRENCH], None, stats=st)
    check("...and without `ask` the real translate_lines drops it (the inert path)",
          st.get("asked") is None and out == [FRENCH], (st, out))
    st = {}
    out = translate.translate_lines([FRENCH], None, stats=st, ask=lambda _t: True)
    check("`ask` puts it in front of the model", st.get("asked") == 1, st)
    check("...and the answer is stored, having passed the same verdict",
          out == ["Ballistic protection device for a vehicle"], out)
finally:
    translate._ask, translate.FARM_ONLY = real_ask, real_farm

check("the pass hands translate_lines its own decision, not a second opinion",
      all(a is not None for _l, _s, a in asked), [a for _l, _s, a in asked])

print()
if fails:
    print("%d check(s) FAILED" % len(fails))
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("test_patent_titles: ok")
