"""The bound that makes step_partnerships finish, pinned.

    python3 test_partnership_buckets.py        (no database, no model)

WHAT THIS PROTECTS. step_partnerships used to ask the model about every proposition
whose predicate matched PART_RX -- 4,546 on the staging corpus, ~7,000 on production's
-- issued one at a time. Measured 2026-09-06: the production enrich container had been
inside that one step for eight hours, had never reached its own summary line, and
because the step committed once at the end, every pass rolled back everything it found.
Steps 4-10 sat behind it and never ran.

bucket_partnership_candidates is the fix: ask only about statements that name a company
whose row can hold the answer, once per distinct statement, capped per company. That is
three filters, and each one is a place where a subtle change silently either restores
the old cost or starts dropping real ties. Both failures are invisible in production --
the first looks like a slow farm, the second like a quiet corpus -- so they are pinned
here instead.

Pure function, real regexes, no database and no model call: this file is about which
questions get asked, not what the answers are.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# enrich_serving imports the whole pipeline (llmapi, portfolio, the engine's
# source_tiers). If any of that is missing this test cannot run, and saying so beats a
# traceback that looks like a failure of the thing being tested.
try:
    from enrich_serving import (CLIENT_BUCKET, PART_CLIENT_CAP, PART_PER_COMP,
                                bucket_partnership_candidates)
except Exception as e:                                              # noqa: BLE001
    print("SKIP test_partnership_buckets: cannot import enrich_serving (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(0)

PROFILES = [
    {"comp_id": "saab", "name": "Saab"},
    {"comp_id": "rheinmetall", "name": "Rheinmetall"},
    {"comp_id": "larsen-toubro", "name": "Larsen & Toubro"},
]

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("  ok   %s" % name)
    else:
        fail += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (name, got, want))


def ok(name, cond, detail=""):
    check(name, bool(cond), True) if cond else _fail(name, detail)


def _fail(name, detail):
    global fail
    fail += 1
    print("  FAIL %s%s" % (name, ("\n    " + detail) if detail else ""))


def prop(s, p, o, q=""):
    return {"s": s, "p": p, "o": o, "q": q, "t": None, "pl": None, "m": None}


def docs_for(*dids):
    return {d: {"title": "T " + d, "source": "src", "lang": "en",
                "url": "https://example.com/" + d, "set": None} for d in dids}


def run(props_by_doc, docs=None, per_comp=PART_PER_COMP, profiles=None,
        client_cap=PART_CLIENT_CAP):
    # `is None`, not `or`: an EMPTY roster is a case this file tests, and `profiles or
    # PROFILES` would quietly hand it the full one and pass.
    docs = docs if docs is not None else docs_for(*props_by_doc)
    return bucket_partnership_candidates(PROFILES if profiles is None else profiles,
                                         docs, props_by_doc, per_comp=per_comp,
                                         client_cap=client_cap)


def names(buckets):
    return {k: [(d, p["p"]) for d, p in v] for k, v in buckets.items()}


# --------------------------------------------------------------- the three filters
print("what gets asked at all")

# 1. THE FILTER THAT SAVES MOST OF THE MONEY. A statement about two companies we do not
#    track was asked about, answered, parsed, source-graded -- and then counted as an
#    orphan and dropped, because there is no row to put it on. 3,098 of the 4,546
#    candidates were exactly this.
b, st = run({"d1": [prop("Thales", "signed a joint venture with", "Hensoldt")]})
check("a tie between two untracked companies is never asked about", b, {})
check("  and is still counted as a candidate", st["candidates"], 1)
check("  but not as one worth asking", st["named"], 0)

# 2. The predicate is what PART_RX reads -- not the subject, not the quote.
b, _ = run({"d1": [prop("Saab", "delivered 20 rifles to", "the Indian Army",
                        "Saab has partnered with nobody in this sentence")]})
check("a predicate with no relationship word is not a candidate", b, {})

b, _ = run({"d1": [prop("Saab", "won an order from", "India",
                        "the deal is part of a joint venture with Adani")]})
check("a relationship word in the QUOTE alone does not make a candidate", b, {})

# 3. The company may be named anywhere in the statement, quote included: the subject is
#    often a product or a programme, and the maker is named in the evidence line.
b, _ = run({"d1": [prop("the Carl-Gustaf line", "is produced under a joint venture with",
                        "Adani", "Saab and Adani signed the agreement in 2024")]})
check("a competitor named only in the quote still buckets", sorted(b), ["saab"])

# 4. The client has nowhere to be stored on a competitor row -- its ties are
#    serving.partner rows -- so it needs a bucket of its own or its statements are
#    never asked about at all.
b, _ = run({"d1": [prop("Bharat Forge", "signed an MoU with", "Paramount Group")]})
check("a client statement goes to the client bucket", sorted(b), [CLIENT_BUCKET])

b, _ = run({"d1": [prop("Kalyani Strategic Systems", "has a joint venture with", "Rafael")]})
check("  and every client spelling reaches it", sorted(b), [CLIENT_BUCKET])

# 5. Word boundaries, because the alternative is a company matching inside another
#    company's name and paying for calls about a firm nobody tracks.
b, _ = run({"d1": [prop("Saabtech Holdings", "signed an MoU with", "Nobody Ltd")]})
check("a tracked name inside a longer word does not match", b, {})

b, _ = run({"d1": [prop("SAAB AB", "signed an MoU with", "Nobody Ltd")]})
check("  but case and legal suffix do not stop it", sorted(b), ["saab"])

# 6. '&' is part of a name, not a regex. word_rx escapes it; a bare re.compile would
#    not, and 'Larsen & Toubro' would raise or match nothing.
b, _ = run({"d1": [prop("Larsen & Toubro", "signed an MoU with", "Hanwha Aerospace")]})
check("a punctuated company name is matched literally", sorted(b), ["larsen-toubro"])


# ------------------------------------------------------------------ syndication
print("\nthe same sentence, many times")

# Wire copy reaches the corpus from a dozen domains with identical propositions. Asking
# the model the same question twelve times cannot produce a different answer.
same = [prop("Saab", "signed an MoU with", "Adani")]
b, st = run({"d1": list(same), "d2": list(same), "d3": list(same)})
check("a syndicated statement is asked once", len(b["saab"]), 1)
check("  and the duplicates are counted, not hidden", st["duplicate"], 2)

b, _ = run({"d1": [prop("Saab", "signed an MoU with", "Adani")],
            "d2": [prop("SAAB", "signed  an   MoU with", "adani")]})
check("case and runs of whitespace do not make it a different statement",
      len(b["saab"]), 1)

# ...but a DIFFERENT statement in the same document is a different question.
b, _ = run({"d1": [prop("Saab", "signed an MoU with", "Adani"),
                   prop("Saab", "signed an MoU with", "Bharat Dynamics")]})
check("two different ties in one document are two questions", len(b["saab"]), 2)

# THE KEY IS THE TWO ENDS, NOT THE VERB. Wire copy rewrites the predicate and leaves
# the companies alone, and step_partnerships keys seen_pairs on the organisations -- so
# a second phrasing of the same pair is a call paid for and then discarded.
b, st = run({"d1": [prop("Rheinmetall", "collaborates with", "Lockheed Martin")],
             "d2": [prop("Rheinmetall", "is partnering with", "Lockheed Martin")],
             "d3": [prop("Rheinmetall", "signed a joint venture with",
                         "Lockheed Martin")]})
check("the same pair phrased three ways is one question",
      len(b["rheinmetall"]), 1)
check("  and the strongest phrasing is the one kept",
      b["rheinmetall"][0][1]["p"], "signed a joint venture with")
check("  the rewrites are counted as duplicates", st["duplicate"], 2)

# Ranking must happen BEFORE the dedupe, or the survivor is whichever copy the corpus
# happened to yield first. d1 sorts first by document id and is the weakest.
b, _ = run({"d1": [prop("Saab", "collaborates with", "Adani", "short")],
            "d2": [prop("Saab", "signed a memorandum with", "Adani",
                        "a much longer supporting quote than the other one")]})
check("rank runs before dedupe, so the weakest copy is not the survivor",
      b["saab"][0][1]["p"], "signed a memorandum with")

# Folding, so a legal suffix or punctuation on one end is not a new pair.
b, _ = run({"d1": [prop("Saab AB", "partnered with", "Adani Defence Ltd.")],
            "d2": [prop("Saab", "partners with", "Adani Defence")]})
check("a legal suffix does not make it a different pair", len(b["saab"]), 1)

# A statement naming two tracked rivals is asked once per bucket. Deliberate: the
# alternative is one global dedupe, and then a statement that ranks low in the first
# company's bucket is dropped and the second company never sees it. The duplicate
# answer is caught by seen_pairs at no cost; a starved rival-to-rival tie is not.
b, _ = run({"d1": [prop("Saab", "signed a joint venture with", "Rheinmetall")]})
check("a tie between two tracked rivals is asked under both",
      sorted(b), ["rheinmetall", "saab"])


# ------------------------------------------------------------------------- the cap
print("\nthe cap, and what it keeps")

# The cap is what turns a bound into a guarantee: one company held 237 statements, and
# a corpus that keeps growing makes that number grow with it.
many = {}
for i in range(10):
    many["w%02d" % i] = [prop("Saab", "collaborates with", "Firm %d" % i)]
for i in range(3):
    many["s%02d" % i] = [prop("Saab", "signed a joint venture with", "Strong %d" % i)]
b, st = run(many, per_comp=4)
check("the cap is honoured exactly", len(b["saab"]), 4)
check("  and the excess is reported, not silently dropped", st["over_cap"], 9)
kept = [p["o"] for _d, p in b["saab"]]
check("  the strongest evidence is what survives the cap",
      sorted(k for k in kept if k.startswith("Strong")),
      ["Strong 0", "Strong 1", "Strong 2"])
check("  and a weak statement only fills what is left", len([k for k in kept
                                                             if k.startswith("Firm")]), 1)

b, st = run(many, per_comp=None)
check("no cap means no cap", len(b["saab"]), 13)
check("  and nothing is reported as over it", st["over_cap"], 0)

# THE COUNT THE OPERATOR READS. `calls` is the promise this whole function makes; if it
# stops matching the buckets, the log line stops meaning anything.
b, st = run(many, per_comp=4)
check("the reported call count is the work actually queued",
      st["calls"], sum(len(v) for v in b.values()))


# --------------------------------------------------------------------- determinism
print("\nsame corpus, same questions")

# A cap that keeps a different four statements each pass makes the tab flicker between
# runs for no reason a reader could ever explain. Dict order is insertion order in
# Python 3.7+, so a corpus loaded in a different order must still ask the same things.
base = {"d%02d" % i: [prop("Saab", "signed an MoU with", "Firm %d" % i)]
        for i in range(8)}
b1, _ = run(base, per_comp=3)
b2, _ = run({k: base[k] for k in reversed(list(base))}, per_comp=3)
check("the cap keeps the same statements whatever order the corpus arrives in",
      names(b1), names(b2))

# Same predicate strength, same quote length -> the tiebreak is (document_id, subject),
# so the choice is a property of the corpus rather than of the loader.
tie = {"zz": [prop("Saab", "signed an MoU with", "Z")],
       "aa": [prop("Saab", "signed an MoU with", "A")]}
b, _ = run(tie, per_comp=1)
check("an exact tie breaks on document id", b["saab"][0][0], "aa")


# ------------------------------------------------------------------- rough edges
print("\nrough edges")

# props_by_doc and docs are loaded by two separate queries. A document with
# propositions but no row in extracted.document would KeyError in the call loop, on a
# line that is thousands of calls into a pass.
b, _ = run({"gone": [prop("Saab", "signed an MoU with", "Adani")]}, docs={})
check("a proposition whose document is missing is dropped, not raised", b, {})

# The corpus has nulls. load_props coalesces to "", but a None reaching here must not
# take the pass down.
try:
    b, _ = run({"d1": [{"s": None, "p": None, "o": None, "q": None}]})
    check("a wholly empty proposition is survivable", b, {})
except Exception as e:                                              # noqa: BLE001
    _fail("a wholly empty proposition is survivable", "%s: %s" % (type(e).__name__, e))

try:
    b, _ = run({"d1": [{"s": "Saab", "p": "signed an MoU with", "o": None, "q": None}]})
    check("a null object does not stop a real tie being asked about",
          sorted(b), ["saab"])
except Exception as e:                                              # noqa: BLE001
    _fail("a null object does not stop a real tie", "%s: %s" % (type(e).__name__, e))

check("an empty corpus asks nothing and says so", run({}), ({}, {
    "candidates": 0, "named": 0, "duplicate": 0, "over_cap": 0, "calls": 0,
    "buckets": 0}))

# With no profiled companies the caller returns early, but the function itself must not
# invent a bucket out of the client alone being absent.
b, _ = run({"d1": [prop("Saab", "signed an MoU with", "Adani")]}, profiles=[])
check("no roster means no competitor buckets", b, {})

# The shipped default has to be a real bound, not None or 0 -- either would restore the
# unbounded pass this whole file exists to prevent. `if cap and ...` reads 0 as "no
# cap", so KSSL_PART_PER_COMP=0 was an undocumented way to turn the bound off while
# looking like a way to turn the feature off.
ok("the shipped per-company cap is a real number",
   isinstance(PART_PER_COMP, int) and PART_PER_COMP > 0,
   "PART_PER_COMP is %r" % (PART_PER_COMP,))
ok("and so is the client's", isinstance(PART_CLIENT_CAP, int) and PART_CLIENT_CAP > 0,
   "PART_CLIENT_CAP is %r" % (PART_CLIENT_CAP,))


# --------------------------------------------------------------- the client's budget
print("\nthe client is not a rival")

# serving.partner -- the client's ENTIRE partner roster, and what the overlap read
# measures every rival against -- is deleted and rebuilt each pass out of this one
# bucket. A rival capped at 40 loses its 41st-best statement; the client capped at 40
# loses part of the roster itself.
client_many = {"c%02d" % i: [prop("Bharat Forge", "signed an MoU with", "Firm %d" % i)]
               for i in range(60)}
b, _ = run(client_many, per_comp=5, client_cap=50)
check("the client gets its own budget, not the rival cap",
      len(b[CLIENT_BUCKET]), 50)

# And a pipeline row with dir='client' must not double every client statement into a
# competitor bucket AND the client bucket -- two model calls for one statement, the
# second of which dies in seen_pairs only after it has been paid for.
with_client = PROFILES + [{"comp_id": "bharat-forge", "name": "Bharat Forge"}]
b, _ = run({"d1": [prop("Bharat Forge", "signed an MoU with", "Paramount")]},
           profiles=with_client)
check("a client competitor row does not double the client's statements",
      sorted(b), [CLIENT_BUCKET])


print()
if fail:
    print("%d failure(s)" % fail)
    sys.exit(1)
print("ok - the partnership candidate bound holds")
