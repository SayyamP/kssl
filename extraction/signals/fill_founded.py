"""The founding year of a competitor, from `extracted.proposition` only.

    python fill_founded.py            # dry run: what it would write
    python fill_founded.py --apply    # write serving.competitors.starting_year
    python fill_founded.py --demo     # offline self-check

WHY THIS EXISTS. `serving.competitors.starting_year` is an integer column that nothing
in the enrich pass ever filled -- 0 of 44 shown competitors had a year. The one writer,
competitor_portfolio.py, reads a hand-maintained workbook ("Starting Year / Corporate
Origin") and is not in STEPS, so the pipeline never ran it. This fills the column the
way `fill_revenue` fills `sales`: from the corpus, with the evidence sentence governing.

THE RULE THAT DOES THE WORK IS VOICE. A founding verb in the ACTIVE voice says the
company did something to an object, and that object is never its own birth:

    Kongsberg  "established a test bed in the Oslofjord"     -> a facility, 2025
    Lockheed   "created the Skunk Works division in 1943"    -> a division
    Raytheon   "incorporated the StormBreaker onto an F-15E" -> a weapon, 2018

Each of those was the company's ONLY candidate year, and each is wrong. In the passive
voice the company is what was founded, which is the question being asked:

    "Anduril was founded in 2017"
    "Raytheon was founded in Cambridge, Mass., in 1922"
    "Bharat Dynamics Limited was incorporated on 16 July, 1970"

Measured on live data, that single distinction is the difference between Raytheon
reading 2018 and reading 1922.
"""
import argparse
import datetime
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aliases import canonical as canon_name, fold as fold_name  # noqa: E402
from fill_revenue import same_org, usable_source                # noqa: E402

DSN = os.environ.get("KSSL_DSN", os.environ.get("KSSL_CORPUS_DSN", ""))
THIS_YEAR = datetime.date.today().year
# A company older than this is a data error, not a rival; younger than the current year
# is impossible. Kongsberg (1814) and Rheinmetall (1889) sit comfortably inside.
OLDEST = 1600

# PASSIVE ONLY. "was founded", "were established", "is incorporated", "has been formed".
# The auxiliary is what makes the company the thing founded rather than the founder.
# The gap allows a noun phrase between the two -- "is a Delaware corporation formed in
# 1952" is how a filing says it. Widening the gap is safe because a quote-derived match
# must still find its year in the object, so "is a company that created the StormBreaker"
# reaches the verb and is then dropped for having no year to take.
PASSIVE = re.compile(
    r"\b(?:was|were|is|are|been|being)\s+(?:\w+\s+){0,4}?"
    r"(founded|established|incorporated|formed|created|set\s+up|constituted|"
    r"registered|born)\b", re.I)
# "Founded in 1922 as the American Appliance Company, ..." -- a participial opener is
# passive with the auxiliary elided, and it is how encyclopaedic prose starts a profile.
OPENER = re.compile(r"(?:^|[.;]\s*|\(\s*)(founded|established|incorporated|formed)\b", re.I)
# The noun does the same job as the passive verb: "Since Otokar's establishment in 1963".
NOUN = re.compile(r"\b(establishment|founding|inception|creation|formation|"
                  r"incorporation)\s+(?:of\s+[\w' ]{0,30})?in\b", re.I)

# The founding is of the COMPANY, not of a thing it built or bought. These name the
# object in sentences that would otherwise pass, e.g. "X was formed to build the plant".
NOT_THE_COMPANY = re.compile(
    r"\b(test bed|testbed|plant|factory|facility|facilities|office|centre|center|"
    r"campus|warehouse|line|division|unit|department|team|programme|program|"
    r"consortium|academy|institute|foundation|museum|fund|award|prize|chair|"
    r"agreement|contract|partnership|alliance|task force|committee|board)\b", re.I)

YEAR = re.compile(r"\b(1[6-9]\d\d|20[0-2]\d)\b")
# "on 30 November 1999" is a more exact claim than "in 1993", and where a company's
# candidates disagree the exact one is the one somebody looked up.
EXACT = re.compile(r"\b\d{1,2}\s+\w+,?\s+(1[6-9]\d\d|20[0-2]\d)\b"
                   r"|\b\w+\s+\d{1,2},?\s+(1[6-9]\d\d|20[0-2]\d)\b", re.I)


def year_in(text):
    """The founding year stated in `text`, or 0. Refuses the impossible."""
    for m in YEAR.finditer(text or ""):
        y = int(m.group(1))
        if OLDEST <= y <= THIS_YEAR:
            return y
    return 0


def founding(predicate, obj, quote):
    """(year, exact) if this proposition states the SUBJECT's own founding, else None.

    The predicate carries the voice, and the voice carries the meaning. Checking the
    quote alone would readmit "Lockheed created the Skunk Works division in 1943",
    whose sentence contains both a founding verb and a year.
    """
    pred = predicate or ""
    obj = obj or ""
    quote = quote or ""
    head = pred + " " + obj
    # An object that names a thing is the thing that was founded, not the company.
    if NOT_THE_COMPANY.search(obj):
        return None
    # OPENER is checked against the SENTENCE only. Applied to the predicate it fired on
    # "formed a teaming agreement", where the founding verb leads an ordinary active
    # clause and Raytheon's 2019 partnership would have become its founding year.
    if PASSIVE.search(head):
        y = year_in(obj) or year_in(quote)
    elif (PASSIVE.search(quote) or NOUN.search(quote) or OPENER.search(quote[:80])):
        # THE AUXILIARY IS OFTEN IN THE SENTENCE, NOT THE PREDICATE -- "The company was
        # established in 2016" reaches here with predicate `established`, object `2016`.
        # But a sentence can also found something ELSE, and the subject still matches:
        # "Otokar Europe SAS was established in France in 2011" would give the parent its
        # subsidiary's year. Requiring the YEAR IN THE OBJECT keeps the date tied to what
        # the model actually attributed to this subject -- that object carries no year.
        y = year_in(obj)
    else:
        return None
    if not y:
        return None
    return y, bool(EXACT.search(obj) or EXACT.search(quote))


def collect(cur):
    """{comp_id: (year, votes, exact)} -- one founding year per competitor."""
    cur.execute("SELECT comp_id, name FROM serving.competitors "
                "WHERE name <> '' AND coalesce(dir, '') <> 'client'")
    comps = cur.fetchall()
    cur.execute("""SELECT p.subject, p.predicate, p.object, p.ev_quote, d.url
                     FROM extracted.proposition p
                     JOIN extracted.document d ON d.document_id = p.document_id
                    WHERE p.modality NOT IN ('planned', 'expected')
                      AND (p.predicate || ' ' || p.object) ~*
                          '(founded|established|incorporated|formed|created|set up|'
                          'constituted|registered)'
                      AND (p.object ~ '(1[6-9][0-9][0-9]|20[0-2][0-9])'
                           OR p.ev_quote ~ '(1[6-9][0-9][0-9]|20[0-2][0-9])')""")
    props = cur.fetchall()
    pats = [(cid, n, re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)", re.I))
            for cid, n in comps if len(n) >= 3]
    folded = {fold_name(canon_name(n)): cid for cid, n in comps}

    tally = {}                       # cid -> {year: [votes, exact_seen]}
    for subject, pred, obj, quote, url in props:
        if not usable_source(url):
            continue
        subj = subject or ""
        hits = [cid for cid, n, rx in pats if rx.search(subj) and same_org(subj, n)]
        if not hits:
            cid = folded.get(fold_name(canon_name(subj)))
            hits = [cid] if cid else []
        if not hits:
            continue
        got = founding(pred, obj, quote)
        if not got:
            continue
        y, exact = got
        for cid in hits:
            slot = tally.setdefault(cid, {}).setdefault(y, [0, False])
            slot[0] += 1
            slot[1] = slot[1] or exact
    out = {}
    for cid, years in tally.items():
        # MOST-STATED WINS, because a corpus that says 1998 eleven times and 1995 once
        # is telling you which is the company's own date. A tie goes to the exact date
        # -- "on 30 November 1999" over "in 1993" -- and then to the earliest, since a
        # later founding verb is usually a re-organisation of something already there.
        best = sorted(years.items(),
                      key=lambda kv: (kv[1][0], kv[1][1], -kv[0]), reverse=True)[0]
        out[cid] = (best[0], best[1][0], best[1][1])
    return out


def run(dsn=DSN, apply=False):
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=15) as con:
        with con.cursor() as cur:
            found = collect(cur)
            cur.execute("SELECT count(*) FROM serving.competitors")
            total = cur.fetchone()[0]
            print("founded: %d of %d competitor(s) have a founding year in the corpus"
                  % (len(found), total), flush=True)
            if not apply:
                print("dry run: nothing written (pass --apply)", flush=True)
                return {"companies": len(found), "written": 0}
            cur.execute("SET lock_timeout='30s'")
            n = 0
            for cid, (y, _votes, _exact) in found.items():
                cur.execute("UPDATE serving.competitors SET starting_year = %s, "
                            "updated_at = now() WHERE comp_id = %s", (y, cid))
                n += cur.rowcount
        con.commit()
    print("founded: wrote %d row(s)" % n, flush=True)
    return {"companies": len(found), "written": n}


def _demo():
    # Real p.subject/predicate/object/ev_quote triples from extracted.proposition.
    ok = founding("was founded", "in 2017", "Anduril was founded in 2017")
    assert ok == (2017, False), ok

    # THE ACTIVE VOICE CASES. Each of these was its company's ONLY candidate year.
    assert not founding("established", "test bed in the Oslofjord",
                        "Our test bed in the Oslofjord established in June 2025 offers "
                        "an arena for technology demonstrations"), "a facility"
    assert not founding("created", "Skunk Works division",
                        "Lockheed created the Skunk Works divison in 1943 to develop "
                        "breakthrough technologies"), "a division"
    assert not founding("successfully incorporated", "the StormBreaker",
                        "In April 2018, Raytheon successfully incorporated the "
                        "StormBreaker onto a Boeing F-15E Strike Eagle."), "a weapon"
    assert not founding("formed a teaming agreement", "Rheinmetall",
                        "the first joint procurement project of Raytheon and "
                        "Rheinmetall since the launch of their teaming agreement "
                        "in 2019"), "an agreement"

    # A participial opener is passive with the auxiliary left out.
    got = founding("was founded in", "Cambridge, Mass.",
                   "Founded in Cambridge, Mass., in 1922 as the American Appliance "
                   "Company, the company adopted the Raytheon name in 1925.")
    assert got == (1922, False), got

    # An exact date is recognised, and beats a bare year on a tie.
    got = founding("was incorporated", "on 16 July, 1970",
                   "Bharat Dynamics Limited (BDL), was incorporated on 16 July, 1970")
    assert got == (1970, True), got

    # The auxiliary in the sentence, the year in the object.
    got = founding("established", "2016",
                   "The company was established in 2016 as part of Prime Minister "
                   "Narendra Modi's \u201cMake in India\u201d initiative")
    assert got == (2016, False), got
    got = founding("formed", "in 1952",
                   "The company is a Delaware corporation formed in 1952 as successor "
                   "to the Electric Boat Company.")
    assert got == (1952, False), got
    got = founding("established", "1963",
                   "Since Otokar\u2019s establishment in 1963, in an era where "
                   "Turkey\u2019s industrialization efforts started, the company")
    assert got == (1963, False), got
    # ...but a subsidiary founded in the same sentence must not become the parent's year.
    assert not founding("established", "Otokar Europe SAS",
                        "Otokar Europe SAS was established in France in the 3rd quarter "
                        "of 2011."), "a subsidiary is not the parent"

    # Impossible years are refused rather than displayed.
    assert not founding("was founded", "in 2087", "X was founded in 2087"), "future"
    assert not founding("was founded", "in 1421", "X was founded in 1421"), "too old"
    assert year_in("no year here") == 0

    # The subject must still be the company -- shared with fill_revenue.
    assert not same_org("Raytheon Space and Airborne Systems", "Raytheon")
    assert same_org("BAE Systems plc", "BAE Systems")
    print("fill_founded demo ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("--dsn", default=DSN)
        ap.add_argument("--apply", action="store_true")
        a = ap.parse_args()
        run(a.dsn, apply=a.apply)
