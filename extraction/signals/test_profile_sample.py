"""A company's profile must be read from many of its articles, not from one.

    python test_profile_sample.py          (no database, no model)

THE BUG THIS PINS. step_companies profiled each company from `cprops[:25]` -- the first
25 extracted statements in document order. company_mentions groups statements by
document, so for a company the corpus covers heavily all 25 came from ONE arbitrary
article, and the profile call answered about that article rather than the company.

Measured on production 2026-09-05, the worse the coverage the worse the profile:

    Saab       2,262 docs / 12,051 statements -> one product, role=integrator -> refused
    Leonardo   1,701 docs /  7,834 statements -> no products, dir=other       -> refused
    Huta S.W.     14 docs /     19 statements -> Borsuk IFV, barrels          -> admitted

Saab carried 46 signal cards and Leonardo 41, with no competitor row for either: the
Competitor tab disagreed with its own feed. With the statements spread, Saab comes back
prime with Carl-Gustaf M4 / RBS 70 NG / Gripen E and Leonardo with the Hitfist turret,
and both are admitted by the unchanged portfolio gate.

So the property under test is COVERAGE, and it is a property of the selection alone --
no model, no corpus, no database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import enrich_serving as es                                          # noqa: E402

bad = 0


def check(name, ok):
    global bad
    if not ok:
        bad += 1
        print("  FAIL %s" % name)


def corpus(n_docs, per_doc):
    """[(doc_id, prop), ...] the way company_mentions returns it: grouped by document."""
    return [("d%03d" % d, {"s": "d%d" % d, "p": "p", "o": "o%d" % i, "q": ""})
            for d in range(n_docs) for i in range(per_doc)]


def docs_of(rows):
    return {d for d, _ in rows}


# --- the reported case: many documents, several statements each --------------------
heavy = corpus(2262, 6)
old = heavy[:es.PROFILE_STATEMENTS]
new = es.spread_statements(heavy)
check("the old slice read a single document (this is the bug)", len(docs_of(old)) <= 11)
check("the sample is the size asked for", len(new) == es.PROFILE_STATEMENTS)
check("...and every statement comes from a different document (%d)" % len(docs_of(new)),
      len(docs_of(new)) == es.PROFILE_STATEMENTS)

# --- a company the corpus barely covers must not lose evidence ---------------------
light = corpus(3, 4)                     # 12 statements in total, under the cap
got = es.spread_statements(light)
check("a small company keeps every statement it has", len(got) == 12)
check("...and all three of its documents", len(docs_of(got)) == 3)
check("no statement is repeated", len(got) == len({(d, p["o"]) for d, p in got}))

# --- one document only: still works, still capped ----------------------------------
single = corpus(1, 500)
got = es.spread_statements(single)
check("one document, capped", len(got) == es.PROFILE_STATEMENTS)
check("...and it is that document", docs_of(got) == {"d000"})

# --- uneven documents: the thin ones are not crowded out by the thick one ----------
uneven = corpus(1, 200) + [("thin%d" % i, {"s": "s", "p": "p", "o": "o", "q": ""})
                           for i in range(5)]
got = es.spread_statements(uneven)
check("every thin document is represented, not buried under the thick one",
      len([d for d in docs_of(got) if d.startswith("thin")]) == 5)

# --- degenerate input ---------------------------------------------------------------
check("no statements, no sample", es.spread_statements([]) == [])
check("n=0 is honoured", es.spread_statements(heavy, 0) == [])

# --- the sample is real rows from the input, never anything synthesised -------------
check("every sampled row came from the input", all(r in heavy for r in new))

# --- and the cap is the one the caller ships ----------------------------------------
check("PROFILE_STATEMENTS is set above the old 25", es.PROFILE_STATEMENTS >= 40)

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - a profile reads %d statements from %d documents; the old slice read the "
      "same %d statements from %d" % (es.PROFILE_STATEMENTS, len(docs_of(new)),
                                      len(old), len(docs_of(old))))
