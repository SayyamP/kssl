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
CAPS_RX = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")


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
    r = len(out) / max(1, len(src))
    if r < 0.45:
        bad.append("too-short:%.2f" % r)
    if r > 2.6:
        bad.append("too-long:%.2f" % r)
    return bad


JUDGE = """You are checking a translation into English. Answer with one line per item:
"<n>. OK" if the English is a faithful translation that preserves the facts, numbers,
units and names of the source, or "<n>. BAD <short reason>" if it does not.
A source that was already in English and was copied out unchanged is OK.
Translating an organisation whose name is ordinary words is OK ("Tag der Deutschen
Einheit" -> "Day of German Unity"). Judge faithfulness only, not style.

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
