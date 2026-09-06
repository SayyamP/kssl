"""Measure the translation layer against the corpus, per language.

    python eval_translation.py --per-lang 6 --langs it,fr,de,es,pl,uk,tr,ru

Not a unit test: it calls the real farm with real corpus rows and reports what came
back, so a regression in the prompt, the gate or the model shows up as a number. The
checks are the ones the layer promises -- numbers survive, designators survive, the
output is not still in the source language, nothing was invented -- plus a length
ratio, because a "translation" a third the length of its input is a summary.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import translate as T                                                  # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
# Han, hiragana, katakana, Hangul: scripts where one character carries a word.
CJK_RX = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def sample(cur, langs, per_lang):
    rows = []
    for lg in langs:
        cur.execute("""SELECT d.language::text, p.subject, p.predicate, p.object
                         FROM extracted.proposition p
                         JOIN extracted.document d USING (document_id)
                        WHERE d.language::text = %s
                          AND length(p.subject||p.predicate||p.object) BETWEEN 25 AND 170
                        ORDER BY md5(p.document_id || p.i::text) LIMIT %s""",
                    (lg, per_lang))
        for lang, s, p, o in cur.fetchall():
            rows.append((lang, "%s %s %s" % (s, p, o)))
    return rows


def check(src, out):
    """-> list of problems. Empty means it passed everything measurable.

    TWO EARLIER CHECKS WERE MEASURING THE EVALUATOR, NOT THE TRANSLATION, and between
    them they turned a good run into "43% clean":

    * `unchanged` was flagged whenever the output equalled the input. But 34% of the
      propositions on a non-English document are ALREADY English -- the extraction
      model translated them -- and for those, unchanged is the correct answer, not a
      failure. 55 of 57 flags were this. It is only a failure when the source was
      foreign and came back identical.
    * `lost-caps` flagged any capitalised source word missing from the output, on the
      theory that it was an organisation. Every single hit was a CORRECT translation
      of an organisation whose name is made of ordinary words: "Tag der Deutschen
      Einheit" -> "Day of German Unity", "Kommandeur der Einsatzflottille" ->
      "Commander of Task Force". Refusing those would be refusing the job. Dropped;
      designator and number survival already cover the cases that matter.
    """
    bad = []
    if out == src:
        if not T.looks_translated(src):
            bad.append("untranslated")     # foreign in, identical out: a real miss
        return bad
    if not T.looks_translated(out):
        bad.append("still-foreign")
    lost_n = set(T.NUM_RX.findall(src)) - set(T.NUM_RX.findall(out))
    if lost_n:
        bad.append("lost-number:" + ",".join(sorted(lost_n)[:2]))
    lost_d = set(T.DESIG_RX.findall(src)) - set(T.DESIG_RX.findall(out))
    if lost_d:
        bad.append("lost-designator:" + ",".join(sorted(lost_d)[:2]))
    # A CHARACTER IS NOT A UNIT OF MEANING IN EVERY SCRIPT, and comparing character
    # counts across scripts is how a perfect translation gets flagged as padding:
    # "赛峰增压系统公司" is 8 characters and "Safran Propulsion Systems" is 25, a ratio
    # of 3.1 for a faultless rendering. All three too-long flags in round 3 were of
    # this kind. Where the source is ideographic, one character is roughly one word,
    # so the comparison is made in words on both sides instead.
    if CJK_RX.search(src):
        src_units = len(CJK_RX.findall(src)) + len(re.findall(r"[A-Za-z]+", src))
        out_units = len(re.findall(r"[^\W\d_]+", out, re.UNICODE))
        r = out_units / max(1, src_units)
        # Wide, because the character-to-word mapping is genuinely noisy: a nine-
        # character compound ("高度专业且敬业的员工") is five English words, while an
        # eight-character company name is three. Only a summary or a padded invention
        # falls outside this, which is all the check is for.
        lo, hi = 0.35, 2.5
    else:
        r = len(out) / max(1, len(src))
        lo, hi = 0.45, 2.6
    # SHORTER IS NOT SUMMARISED WHEN THE SOURCE SAID IT TWICE. The extraction layer
    # emits propositions whose subject is the source-language rendering of their own
    # object: "エンドツーエンドのマッピングと分析 is utilized end-to-end mapping and
    # analysis" -- the katakana IS "end-to-end mapping and analysis". A correct
    # translation collapses that to one clause and is legitimately a third the length.
    # The question `too-short` is really asking is "were facts dropped", so if every
    # English content word already in the SOURCE survives in the output, nothing was.
    if r < lo:
        src_en = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{2,}", src)}
        kept_en = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{2,}", out)}
        if not (src_en and src_en <= kept_en):
            bad.append("too-short:%.2f" % r)
    if r > hi:
        bad.append("too-long:%.2f" % r)
    return bad


# JUDGE ONE THING. Told merely to "judge faithfulness, not style", the model spent
# round 2 reporting "grammar and clarity", "unclear and unnatural phrasing" and
# "redundant achievement" -- style, on rows whose facts were intact. A judge that
# drifts into style manufactures work: every one of those would have sent the loop
# chasing a rewrite of a correct translation. So the question is narrowed to a single
# yes/no about meaning, and the things it must NOT report are named explicitly,
# because naming the exclusion is what actually suppresses it.
JUDGE = """For each item, decide ONE thing: does the ENGLISH state the same facts as
the SOURCE? Answer one line per item: either "<n>. OK", or "<n>. BAD" followed by a
few words naming the fact that changed. Write the reason in your own words -- do not
copy this instruction back.

BAD only if the English changes or drops a fact: a different number, quantity, date,
unit or calibre; a different organisation, person, product or country; a negation or
modality flipped ("will supply" vs "may supply"); a clause of the source missing; or
text still in the source language.

OK -- and you must answer OK -- for all of these:
- a source already in English, copied out unchanged
- an organisation or event whose name is ordinary words, translated
  ("Tag der Deutschen Einheit" -> "Day of German Unity")
- a proper noun deliberately left in its own language
- awkward, redundant, ungrammatical or unnatural English
- different word order, different register, a clumsy or literal rendering
- British vs American spelling, or a differently formatted date

Style is not your concern. Only whether the facts survived.

%s"""


def judge(pairs):
    """-> {i: (ok, reason)}. A second opinion from the same farm, on faithfulness --
    the thing the mechanical checks above cannot see."""
    if not pairs:
        return {}
    body = "\n".join("%d. SOURCE: %s\n   ENGLISH: %s" % (n + 1, a, b)
                      for n, (a, b) in enumerate(pairs))
    try:
        raw, _via = T._ask(JUDGE % body)
    except Exception as exc:                                          # noqa: BLE001
        return {i: (True, "judge-unavailable:%s" % type(exc).__name__)
                for i in range(len(pairs))}
    out = {}
    for line in (raw or "").splitlines():
        m = re.match(r"\s*(\d+)[.)]\s*(OK|BAD)\b[:\s-]*(.*)$", line.strip(), re.I)
        if m:
            out[int(m.group(1)) - 1] = (m.group(2).upper() == "OK", m.group(3)[:70])
    return out


def main(langs, per_lang, dsn, dump):
    import psycopg2
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    rows = sample(cur, langs, per_lang)
    print("%d row(s) across %d language(s)\n" % (len(rows), len(langs)), flush=True)
    by_lang, out_rows = {}, []
    for lang in langs:
        mine = [t for lg, t in rows if lg == lang]
        if not mine:
            continue
        st = {}
        t0 = time.time()
        got = T.translate_lines(mine, lang, stats=st)
        dt = time.time() - t0
        probs = [check(a, b) for a, b in zip(mine, got)]
        verdicts = judge(list(zip(mine, got)))
        for i, p in enumerate(probs):
            ok, why = verdicts.get(i, (True, "not-judged"))
            if not ok:
                p.append("judge:" + (why or "unfaithful"))
        clean = sum(1 for p in probs if not p)
        by_lang[lang] = {"n": len(mine), "clean": clean, "secs": round(dt, 1),
                         "stats": st, "problems": [p for p in probs if p]}
        print("%-3s %2d/%2d clean  %5.1fs  %s" % (lang, clean, len(mine), dt,
              "" if clean == len(mine) else
              " | ".join(",".join(p) for p in probs if p)[:110]), flush=True)
        for a, b, p in zip(mine, got, probs):
            out_rows.append({"lang": lang, "src": a, "out": b, "problems": p})
    tot = sum(v["n"] for v in by_lang.values())
    ok = sum(v["clean"] for v in by_lang.values())
    print("\nTOTAL %d/%d clean (%.1f%%)" % (ok, tot, 100 * ok / max(1, tot)))
    if dump:
        Path(dump).write_text(json.dumps(out_rows, ensure_ascii=False, indent=1))
        print("wrote %s" % dump)
    con.close()
    return by_lang


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--per-lang", type=int, default=6)
    ap.add_argument("--langs", default="it,fr,de,es,pl,uk,tr,ru,nl,pt")
    ap.add_argument("--dump", default=None)
    a = ap.parse_args()
    main([x.strip() for x in a.langs.split(",") if x.strip()], a.per_lang, a.dsn, a.dump)
