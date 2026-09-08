"""English titles for serving.patent, without destroying the office's own words.

    python patent_titles.py                # dry run: says what it would write
    python patent_titles.py --apply        # writes title_en / title_en_v
    python patent_titles.py --demo         # hermetic self-check, no database, no model

THE DEFECT. 169 of the 1,183 stored patent titles are not in English -- German, French,
Spanish and Korean -- because a patent office publishes a title in its own language and
the harvest stores what it is given. The Patents tab is read in English. A row whose
title the reader cannot read is a row they cannot judge, and it is the title that
carries the whole finding: assignee, date and IPC code say who and when, never what.

THE ORIGINAL IS NOT OVERWRITTEN. `title` is the legal name the office published the
invention under and the string that finds the record again in that office's register;
replacing it in place would make the row unverifiable against its own source. The
English rendering goes in its own column and the card shows both -- translated line
first, the office's own title underneath.

THE SHAPE IS serving_fill.retranslate()'s, deliberately, including the reason it has
that shape. `title_en_v` holds the prompt version the row was last done under and the
pass selects rows whose stamp differs from the current one, so:

  * a re-run continues instead of restarting (the window advances -- the fault that
    migration 2026-09-06_signal_detail_translated.sql was written for, where the same
    first 200 of 949 cards were re-asked every cycle for ever);
  * a finished corpus costs nothing at all;
  * bumping translate.PROMPT_VERSION re-queues every row for exactly one pass;
  * a row is stamped even when nothing was changed, or the English rows would be
    re-examined for ever and the window would never pass them.

WHICH TITLES ARE SENT, AND WHY THE GATE IS NOT AN ENGLISH WORD LIST. This repository
has been burned three times by a closed keyword list quietly acting as a language
detector, so the decision is made by translate.needs_english(), the gate the serving
layer already uses, and its two arms are both evidence-of-foreign, never
evidence-of-English:

  1. the STRING -- non-Latin script, words carrying diacritics, foreign function words.
     A terse English title trips none of them and is skipped without a model call.
  2. the row's own PROVENANCE, which is the analogue of the document language that arm
     was built for. OFFICE_LANG below lists only offices that do NOT publish in English;
     everything else -- including every office not in it -- maps to None and is decided
     by arm 1 alone. There is deliberately no list of English offices and no list of
     English words: an office nobody has classified costs nothing and falls back to the
     string test.

Both errors are bounded and neither can corrupt a row. Asking about a title that was
already English costs one line in a batched call and comes back "unchanged", which is
stored as nothing. Not asking about a foreign one leaves the source title on screen,
which is what the tab shows today. And every answer still passes translate.verdict():
an answer that is not English, that drops a number or a designator, or that did not
come from the farm is refused, and the original stands.
"""
import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import translate                                                        # noqa: E402

DSN = os.environ.get("KSSL_CORPUS_DSN") or os.environ.get("DSN") or ""

# How many titles ride in one model call. translate_lines numbers the batch and matches
# the answers back by number, so the only cost of a bigger batch is a longer prompt --
# and a title is a dozen words. 10 keeps the prompt well under the model's attention
# span while turning ~460 candidate titles into ~46 calls.
BATCH = int(os.environ.get("KSSL_PATENT_TITLE_BATCH") or 10)

# OFFICES THAT DO NOT PUBLISH IN ENGLISH. This is the whole of the provenance arm, and
# it is a list of NON-English offices on purpose: an office missing from it is not
# thereby called English, it is called unknown, and the string decides. Multi-language
# offices are deliberately absent -- EP publishes titles in English, German and French
# and WO in the language of filing, so neither one is evidence of anything.
#
# The keys are what the harvest actually stores, both spellings included where the
# vocabulary collides ('India'/'IN'), because this runs against the database as it is
# rather than as 2026-09-06_patent_country_vocab.sql will leave it.
OFFICE_LANG = {
    "DE": "de", "AT": "de", "CH": "de",
    "FR": "fr", "BE": "fr",
    "ES": "es", "CL": "es", "MX": "es", "AR": "es", "CO": "es", "PE": "es",
    "IT": "it", "PT": "pt", "BR": "pt", "NL": "nl",
    "SE": "sv", "NO": "no", "DK": "da", "FI": "fi",
    "PL": "pl", "CZ": "cs", "RU": "ru", "UA": "uk", "TR": "tr",
    "KR": "ko", "JP": "ja", "CN": "zh", "TW": "zh",
    "ID": "id", "TH": "th", "VN": "vi",
    "GR": "el", "HU": "hu", "RO": "ro", "BG": "bg",
}


def office_language(country):
    """-> the language an office publishes in, or None when that is not known.

    None is not "English". It means there is no provenance evidence and the string is
    the only evidence, which is exactly how translate.needs_english() treats it."""
    c = str(country or "").strip().upper()
    if not c:
        return None
    # the collided vocabulary, in the one place that has to survive it either way
    c = {"INDIA": "IN", "USA": "US", "UNITED STATES": "US", "UK": "GB",
         "SOUTH KOREA": "KR", "REPUBLIC OF KOREA": "KR", "KOREA": "KR",
         "GERMANY": "DE", "FRANCE": "FR", "SPAIN": "ES", "JAPAN": "JP",
         "CHINA": "CN"}.get(c, c)
    return OFFICE_LANG.get(c)


# A TITLE IS NOT A SENTENCE, and the shared gate is calibrated for sentences.
# looks_translated() wants TWO foreign function words before it will call a string
# foreign, on the measured grounds that in a thirty-word lead-in one is a loanword or a
# name ("Direction generale de l'armement", "von Braun"). A patent title is six words.
# "Dispositif de protection balistique pour vehicule" contains exactly one listed word
# -- `de` is excluded as an ordinary English token -- so the shared gate reads it as
# English, and on a corpus where 203 filings are EP (three publication languages, so no
# provenance evidence either) that is a title nobody can read, left on the page.
#
# So the same evidence is weighed by DENSITY as well as count, over short strings only.
# It is still the foreign-evidence test -- translate.py's own list, no English words
# anywhere in the decision -- read at the length these strings actually are.
#
# It does over-fire, and that is the cheap direction: "Die casting method for a barrel"
# hits `die` from the German list and gets asked about. One numbered line in a batched
# call, answered "unchanged", stored as nothing.
TITLE_TOKENS = 12          # above this a title is prose and the shared gate is right
TITLE_DENSITY = 0.15


def title_needs_english(title, country=None):
    """Should this title be sent to the model at all?

    The cost of a wrong True is one line in a batched call that comes back unchanged.
    The cost of a wrong False is a title nobody can read staying on the page for ever,
    which is why this leans the way it does."""
    if translate.needs_english(title, office_language(country)):
        return True
    toks = re.findall(r"[^\W\d_]+", str(title or ""), re.UNICODE)
    if not toks or len(toks) > TITLE_TOKENS:
        return False
    # translate._foreign_hits is reached into on purpose: the alternative is a second
    # copy of a 400-word function-word list that would drift out of step with the one
    # the rest of the serving layer is measured against.
    hits = translate._foreign_hits(title)
    return bool(hits) and len(hits) / len(toks) >= TITLE_DENSITY


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def plan(rows):
    """-> (asked, skipped). Pure: what the pass would send, grouped by language.

    Separated from the database so the decision can be tested without one, and so a dry
    run reports the same grouping the applying run uses."""
    asked, skipped = {}, []
    for r in rows:
        if not (r.get("title") or "").strip():
            skipped.append(r)
            continue
        if title_needs_english(r["title"], r.get("country")):
            asked.setdefault(office_language(r.get("country")), []).append(r)
        else:
            skipped.append(r)
    return asked, skipped


SELECT_SQL = """SELECT ord, "no", title, country, title_en
                  FROM serving.patent
                 WHERE origin = 'pipeline'
                   AND title IS NOT NULL AND title <> ''
                   AND (%s IS NULL OR "no" = %s)
                   AND (%s OR title_en_v IS DISTINCT FROM %s)
                 ORDER BY title_en_v NULLS FIRST, ord
                 LIMIT %s
                   FOR UPDATE SKIP LOCKED"""


def translate_titles(dsn=None, limit=None, apply=False, verbose=True, only=None,
                     force=False):
    """The pass. Returns its stats dict, or None if it asked the model and stored nothing.

    Dry run by default: --apply is what writes. A dry run still calls the model, because
    the only honest preview of what would be stored is what the model actually answers.
    """
    import psycopg2
    import psycopg2.extras
    con = psycopg2.connect(dsn or DSN)
    cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(SELECT_SQL, (only, only, bool(force or only),
                             translate.PROMPT_VERSION, limit or 10 ** 9))
    rows = [dict(r) for r in cur.fetchall()]
    asked, skipped = plan(rows)
    stats = {"rows": len(rows), "skipped_english": len(skipped),
             "candidates": sum(len(v) for v in asked.values()), "written": 0}

    def stamp(row, title_en):
        # STAMPED EITHER WAY. A row that needed nothing, and a row whose translation was
        # refused, are both DONE for this prompt version; leaving them unstamped is what
        # makes a window stop advancing and re-ask the same rows for ever.
        if not apply:
            return
        cur.execute("""UPDATE serving.patent
                          SET title_en = COALESCE(%s, title_en), title_en_v = %s,
                              updated_at = now()
                        WHERE ord = %s""",
                    (title_en, translate.PROMPT_VERSION, row["ord"]))
        con.commit()                      # per row: a pass that dies has still made progress

    for row in skipped:
        stamp(row, None)

    for lang, group in sorted(asked.items(), key=lambda kv: kv[0] or ""):
        for chunk in _chunks(group, BATCH):
            # ask=: THE DECISION WAS ALREADY MADE, ABOVE. translate_lines re-gates on
            # needs_english() by default, which is calibrated for thirty-word lead-ins
            # and would drop every title the density arm selected -- silently, while
            # this pass counted it as a candidate. plan() has already decided; the gate
            # here would only be a second, weaker opinion about the same string.
            out = translate.translate_lines([r["title"] for r in chunk], lang,
                                            stats=stats, ask=lambda _t: True)
            for row, got in zip(chunk, out):
                got = (got or "").strip()
                if not got or got == (row["title"] or "").strip():
                    # refused, or the model said it was already English. Either way
                    # there is nothing to store: title_en stays NULL and the card keeps
                    # showing the source title, which is the honest fallback.
                    stamp(row, None)
                    continue
                if verbose:
                    print("  %s [%s]" % (row["no"], lang or "?"))
                    print("    - %s" % row["title"][:110])
                    print("    + %s" % got[:110])
                stamp(row, got)
                stats["written"] += 1

    print("patent_titles: %d row(s) in window, %d already English, %d asked, "
          "%d translated%s" % (stats["rows"], stats["skipped_english"],
                               stats["candidates"], stats["written"],
                               "" if apply else "  (dry run -- nothing written)"),
          flush=True)
    if verbose:
        print("  %s" % {k: v for k, v in sorted(stats.items())}, flush=True)
    con.close()
    # ASKED AND STORED NOTHING IS AN OUTAGE, NOT A QUIET SUCCESS -- the same alert
    # retranslate() carries, for the same reason: translate.py refuses any answer that
    # did not come from the farm, so a renamed model alias silently refuses every line
    # for ever and an exit code of 0 would keep that out of the log.
    if stats.get("asked") and not (stats.get("translated") or
                                   stats.get("translated_on_retry")):
        print("[ALERT] patent_titles: asked for %d title(s) and stored none -- backend "
              "refusals %d, failures %d. Check C_MODEL and that llmapi reports "
              "via='farm'." % (stats["asked"], stats.get("refused_backend", 0),
                               stats.get("failed", 0)), file=sys.stderr, flush=True)
        return None
    return stats


def _demo():
    """Hermetic: the gate only. No database, no model, no network."""
    # --- already English: never sent, whatever office it came from -----------------
    for t in ("Armour plate assembly for a combat vehicle",
              "Method of manufacturing a gun barrel",
              "Projectile"):
        assert not title_needs_english(t, "US"), t
        assert not title_needs_english(t, None), t
    # ...and an English title filed at a non-English office is still sent, because the
    # provenance arm cannot see the string. It comes back "unchanged" and stores nothing.
    assert title_needs_english("Armour plate assembly", "DE")

    # --- foreign by the STRING alone, with no provenance to go on -------------------
    assert title_needs_english("Verfahren und Vorrichtung zur Herstellung", None)
    assert title_needs_english(u"장갑차용 포탑", None)  # Korean
    # ...including the short-title arm: one French function word in six tokens, which
    # the shared gate (built for thirty-word lead-ins) calls English.
    assert title_needs_english("Dispositif de protection balistique pour vehicule", None)
    assert not translate.needs_english("Dispositif de protection balistique pour vehicule"),         "if the shared gate ever catches this, the density arm can go"
    # ...and length is the whole of what separates the two: a long English abstract-like
    # title with one stray listed token is left alone.
    assert not title_needs_english(
        "Method and apparatus for the continuous casting of a hollow steel billet used "
        "in the manufacture of large calibre artillery barrels", None)

    # --- foreign by PROVENANCE, where the string gives nothing away -----------------
    # "Sistema de armas" carries no diacritic and no listed function word: the string
    # arm calls it English and is wrong. This is exactly what the office arm is for.
    assert title_needs_english("Sistema de armas", "ES")

    # --- an office nobody classified is NOT called English --------------------------
    assert office_language("ZZ") is None
    assert office_language("EP") is None, "EP publishes in three languages; not evidence"
    assert office_language("India") == office_language("IN")
    assert office_language("USA") == office_language("US")

    # --- nothing to say, nothing asked ---------------------------------------------
    for t in ("", "   ", None):
        assert not title_needs_english(t, "DE"), repr(t)

    # --- plan() groups by language and never sends a blank --------------------------
    rows = [{"ord": 1, "title": "Armour plate", "country": "US"},
            {"ord": 2, "title": "Sistema de armas", "country": "ES"},
            {"ord": 3, "title": "Verfahren zur Herstellung", "country": "DE"},
            {"ord": 4, "title": "", "country": "DE"}]
    asked, skipped = plan(rows)
    assert sorted(asked) == ["de", "es"], asked
    assert [r["ord"] for r in skipped] == [1, 4], skipped
    print("patent_titles --demo: ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help='one patent number ("no"), for a single-row check')
    ap.add_argument("--force", action="store_true",
                    help="revisit rows already done under this prompt version")
    ap.add_argument("--apply", action="store_true",
                    help="write. Without it this is a dry run and stores nothing.")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        return _demo()
    if translate_titles(a.dsn, limit=a.limit, apply=a.apply, only=a.only,
                        force=a.force) is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
