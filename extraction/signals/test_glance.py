"""The "At a glance" span rows must ENTAIL what they claim, not merely co-occur.

    python3 test_glance.py

Every fixture here is a REAL sentence from the corpus, found by joining extracted.span to
the proposition whose evidence sentence contains it, on the 1,136 pipeline cards. The
negative ones are the trap this project has fallen into before -- a number or a name that
IS in the article but does NOT belong to the card's subject:

  * "$4 million" in the Stinger article is what one interceptor costs, not the Army's money
  * "PLN5 billion" in the Gdynia article is what a not-yet-chosen private partner will
    raise, though the port authority is named in the same sentence
  * "£8 billion" is the CEILING of a UK framework, not Ericsson's contract
  * "€22.1 billion" is Thales' annual turnover, not a deal
  * Germany is in the sentence where Rheinmetall expects a contract -- and is nobody's
    customer; no Country is ever emitted as one
  * Karan Adani (Adani Ports) attended the Adani Defence ground-breaking; he is not its
    key person
  * "Gripen E" under a "Gripen F" headline, "Suppliers", "Naval Power" (a business unit
    typed Program) are not rows either

This file loads the SHIPPED glance.py and serving_fill.glance_rows -- not a re-implementation
-- and refuses outright if either source carries a control byte, because a backslash-b that
reaches the file as 0x08 compiles fine and matches nothing (test_sowhat_tail.py).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

for src in ("glance.py", "serving_fill.py"):
    raw = (HERE / src).read_bytes()
    bad = re.findall(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw)
    assert not bad, "%s carries control byte(s) %r -- a regex escape was eaten" % (src, bad)

import glance  # noqa: E402
from glance import Prop, Span, glance_facts  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)


def sp(i, a, b, text, type_, in_article=None, gloss=None, source="gliner", score=0.9, sent=0):
    return Span(i, a, b, text, type_, None, gloss, in_article, source, score, sent)


def one(q, *props):
    return [Prop(i, s, p, o, 0, len(q), q) for i, (s, p, o) in enumerate(props)]


# --- negatives: present in the article, not the subject's ----------------------------------
q = ("U.S. air defense missiles — each of which can cost about $4 million — have been used to "
     "shoot down Iranian drones, which cost between $20,000 and $30,000 apiece.")
a, b = q.index("$4 million"), q.index("$20,000 and $30,000")
ref = {}
rows = glance_facts("The Army", "US Army seeks thousands of new missiles to replace Stinger",
                    one(q, ("U.S. air defense missiles", "have been used to shoot down", "Iranian drones")),
                    [sp("m1", a, a + 10, "$4 million", "Money", "the cost of each U.S. air defense missile"),
                     sp("m2", b, b + 19, "$20,000 and $30,000", "Money", "the cost range of Iranian drones")],
                    refused=ref)
check(rows == [], "a unit cost in the Army's article is not the Army's figure: %r" % rows)
check(ref == {"money:unanchored": 2}, "both costs counted as refused: %r" % ref)

q = ("The successful private partner will be responsible for designing and constructing the "
     "new container terminal, arranging financing of around PLN5 billion (USD1.31 billion), "
     "and jointly operating the terminal with the Port of Gdynia Authority.")
a = q.index("PLN5 billion")
ref = {}
rows = glance_facts("Port of Gdynia Authority", "Poland extends deadline for NATO dual-use port bids",
                    one(q, ("The successful private partner", "will jointly operate the terminal with",
                            "the Port of Gdynia Authority")),
                    [sp("m", a, a + 12, "PLN5 billion", "Money",
                        "Arranging financing of around PLN5 billion (USD1.31 billion)", "A monetary value")],
                    refused=ref)
check(rows == [], "the partner's financing is not the port authority's deal: %r" % rows)
check(ref.get("money:untyped") == 1, "refused as untyped, not silently dropped: %r" % ref)

q = "The framework is valued at up to £8 billion over eight years."
a = q.index("£8 billion")
ref = {}
rows = glance_facts("Ericsson", "Ericsson selected for UK Tactical Communication Systems framework",
                    one(q, ("Ericsson", "is a provider for", "the framework")),
                    [sp("m", a, a + 10, "£8 billion", "Money", "the value of the framework over eight years")],
                    refused=ref)
check(rows == [] and ref == {"money:ceiling": 1}, "a ceiling is not a value: %r %r" % (rows, ref))

q = "In 2025, the Group generated sales of €22.1 billion."
a = q.index("€22.1 billion")
ref = {}
rows = glance_facts("Thales", "Thales accelerates defence production and investment",
                    one(q, ("Thales", "generated", "sales of €22.1 billion")),
                    [sp("m", a, a + 13, "€22.1 billion", "Money", "the Group's total sales in 2025")],
                    refused=ref)
check(rows == [] and ref == {"money:not-a-deal-figure": 1}, "turnover is not a deal: %r %r" % (rows, ref))

q = "Rheinmetall expects a multibillion-euro contract after Germany canceled the F126 frigate program."
a = q.index("Germany")
ref = {}
rows = glance_facts("Rheinmetall", "Rheinmetall faces delays with Bundeswehr order",
                    one(q, ("Rheinmetall", "expects", "a multibillion-euro contract")),
                    [sp("o", a, a + 7, "Germany", "Country",
                        "The country that canceled its F126 frigate program", score=0.97)], refused=ref)
check(rows == [] and ref == {}, "a Country is never a counterparty candidate: %r %r" % (rows, ref))

q = "Mr Karan Adani, Managing Director, Adani Ports & SEZ, attended the event."
ref = {}
rows = glance_facts("Adani Defence & Aerospace", "Adani Defence to build missile ecosystem",
                    one(q, ("Mr Karan Adani", "attended", "the event")),
                    [sp("p", 3, 14, "Karan Adani", "Person", "the Managing Director of Adani Ports & SEZ"),
                     sp("r", 16, 33, "Managing Director", "Role")], refused=ref)
check(rows == [] and ref == {"person:unanchored": 1},
      "a sister company's director is not this company's key person: %r %r" % (rows, ref))

q = "Saab has successfully completed the first flight of Gripen F, the two-seat variant of Gripen E."
a = q.index("Gripen E")
ref = {}
rows = glance_facts("Saab", "Saab Completes First Flight of Gripen F",
                    one(q, ("Saab", "completed", "the first flight of Gripen F")),
                    [sp("w", a, a + 8, "Gripen E", "Platform", "the single-seat variant", score=0.9)],
                    refused=ref)
check(rows == [] and ref == {"system:in-title": 1}, "the headline already says Gripen: %r %r" % (rows, ref))

q = "Building a Robust Supply Chain: 10,000 Suppliers support Northrop Grumman."
a = q.index("Suppliers")
ref = {}
rows = glance_facts("Northrop Grumman", "Northrop Grumman invests in U.S. infrastructure",
                    one(q, ("10,000 Suppliers", "support", "Northrop Grumman")),
                    [sp("o", a, a + 9, "Suppliers", "Organization",
                        "the suppliers in Northrop Grumman's supply chain", score=0.7)], refused=ref)
check(rows == [] and ref == {"counterparty:not-a-name": 1}, "a kind of org is not a name: %r %r" % (rows, ref))

q = "Barbara Borgonovi, president of Naval Power at Raytheon, said the array was installed."
a = q.index("Naval Power")
ref = {}
rows = glance_facts("Raytheon", "Raytheon installs first SPY-6(V)4 radar array",
                    one(q, ("Barbara Borgonovi", "said", "the array was installed")),
                    [sp("g", a, a + 11, "Naval Power", "Program",
                        "the Raytheon business unit Barbara Borgonovi presides over", score=0.8)], refused=ref)
check(rows == [] and ref == {"programme:not-a-programme": 1}, "a business unit is not a programme: %r %r" % (rows, ref))

# a quote that does not show the span at its offset proves nothing -- refused, not trusted
q = "Dataminr won a $318 million contract from the Defense Department."
a = q.index("$318 million")
ref = {}
rows = glance_facts("Dataminr", "t", one(q, ("Dataminr", "delivers", "alerting technology")),
                    [sp("m", a + 1, a + 13, "$318 million", "Money", "the amount awarded in the contract")],
                    refused=ref)
check(rows == [] and ref == {"money:misaligned": 1}, "misaligned quote refused: %r %r" % (rows, ref))

# --- positives: the same sentences, read the right way ---------------------------------------
rows = glance_facts("Dataminr", "t", one(q, ("Dataminr", "delivers", "alerting technology")),
                    [sp("m", a, a + 12, "$318 million", "Money", "the amount awarded in the contract")])
check(rows == [["Deal value", "$318 million", q]], "Dataminr's contract, quoted: %r" % rows)

q = ("The Army has asked Congress for $215 million in its fiscal year 2027 budget for the "
     "Stinger replacement along with $713 million for 14 more Sgt. Stout Systems.")
a, b, c = q.index("$215 million"), q.index("14 more"), q.index("Sgt. Stout Systems")
rows = glance_facts("The Army", "US Army seeks thousands of new missiles to replace Stinger",
                    one(q, ("The Army", "asks for", "$215 million in its fiscal year 2027 budget")),
                    [sp("m", a, a + 12, "$215 million", "Money", "the amount requested for the Stinger replacement"),
                     sp("c", b, b + 2, "14", "Count", "the number of Sgt. Stout systems", "a number of items"),
                     sp("w", c, c + 18, "Sgt. Stout Systems", "WeaponSystem", "the system the Army wants more of")])
check(rows == [["Budget", "$215 million", q], ["Quantity", "14 more Sgt. Stout Systems", q],
               ["System", "Sgt. Stout Systems", q]], "the Army's own rows: %r" % rows)

q = "The Army awarded Raytheon a contract for 350 missiles."
a = q.index("Raytheon")
rows = glance_facts("The Army", "t", one(q, ("The Army", "awarded", "Raytheon a contract")),
                    [sp("o", a, a + 8, "Raytheon", "Organization", score=0.9)])
check(rows == [["Supplier", "Raytheon", q]], "the buyer's supplier: %r" % rows)

q = "Kendy Hau, head of defence at Fujitsu Australia, said quantum was years away."
rows = glance_facts("Fujitsu Australia", "t", one(q, ("Kendy Hau", "said", "quantum was years away")),
                    [sp("p", 0, 9, "Kendy Hau", "Person", "the head of defence at Fujitsu Australia"),
                     sp("r", 11, 26, "head of defence", "Role")])
check(rows == [["Key person", "Kendy Hau, head of defence", q]], "a person AT the company: %r" % rows)

# every emitted row carries its quote, and no row is the pillar
for r in rows:
    check(len(r) == 3 and r[2], "row without a quote: %r" % (r,))
check("Primary lens" not in glance.ROW_ORDER, "the pillar is not a glance row")

# --- the writer: serving_fill emits these rows and no Primary lens ----------------------------
import serving_fill as sf  # noqa: E402

src = (HERE / "serving_fill.py").read_text(encoding="utf-8")
check('["Primary lens"' not in src, "serving_fill.py still writes a Primary lens row")
check(hasattr(sf, "glance_rows") and hasattr(sf, "reglance"),
      "serving_fill exposes glance_rows (fill) and reglance (backfill of stored cards)")


class _Cur:
    """Answers glance_rows' two queries: propositions with offsets, then spans."""
    def __init__(self):
        self.n = 0

    def execute(self, *_):
        self.n += 1

    def fetchall(self):
        qq = "Dataminr won a $318 million contract from the Defense Department."
        if self.n == 1:
            return [(0, "Dataminr", "delivers", "alerting technology", 0, len(qq), qq)]
        i = qq.index("$318 million")
        return [("s", i, i + 12, "$318 million", "Money", None, "a unit of currency",
                 "the amount awarded in the contract", "gliner", 0.9, 0),
                ("o", qq.index("Defense Department"), qq.index("Defense Department") + 18,
                 "Defense Department", "Organization", None, None, "the buyer", "gliner", 0.9, 0)]


st = {}
rows = sf.glance_rows(_Cur(), "doc", "Dataminr", "Dataminr wins $318M Pentagon contract", st)
check(rows == [["Deal value", "$318 million",
                "Dataminr won a $318 million contract from the Defense Department."]],
      "glance_rows through the writer: %r" % rows)
check(st.get("glance_refused", 0) >= 1, "the Defense Department (not in the proposition) counted as refused: %r" % st)

if FAILS:
    sys.exit("%d failure(s)" % len(FAILS))
print("ok")
