"""A leadership card names a living officer of THIS company, in post NOW.

    python3 test_leadership.py        (hermetic: no database, no network, no model)

Every string below is a real proposition from extracted.proposition, and every refusal
below is something this signal actually published into a dry run before the rule that
refuses it existed. A Profile card that names a person in a role is the most damaging
kind of wrong content on this dashboard -- more damaging than an empty panel, which is
why the panel was left empty until something could fill it correctly. So the faults are
pinned individually rather than as one "it works" assertion.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fill_leadership as L   # noqa: E402

# (comp_id, roster name, name regex, origin country)
def _n(cid, name, country):
    return (cid, name, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I), country)


ROSTER = [_n("saab", "Saab", "Sweden"), _n("bae", "BAE Systems", "UK"),
          _n("rhm", "Rheinmetall", "Germany"), _n("ray", "Raytheon", "US"),
          _n("lmt", "Lockheed Martin", "US"), _n("iai", "Israel Aerospace Industries",
                                                 "Israel"),
          _n("patria", "Patria", "Finland"), _n("avav", "AeroVironment", "US")]
# Everyone below is typed `Person` by the extraction layer; the corroboration set is
# what stops a capitalised organisation being read as a human being.
PEOPLE = {L.fold_name(x) for x in (
    "Micael Johansson", "Charles Woodburn", "Barbara Borgonovi", "Raydon Gates",
    "Tom Arseneault", "Andy Keough", "Donald Trump", "Reuven Rivlin", "Per Ahl",
    "Mika Kari", "Wahid Nawabi", "Jim Taiclet", "James D. Taiclet", "Armin Papperger",
    "Colin Whelan", "Colina Whelan")}


def check(subject, pred, obj, quote):
    return L.officer(subject, pred, obj, quote, ROSTER, PEOPLE)


def test_states_the_office():
    got = check("Micael Johansson", "is", "Saab President and CEO",
                "Saab President and CEO, Micael Johansson talks about the transfer")
    assert got == ("saab", "Micael Johansson", "President and CEO", False), got
    # The company as subject, the person beside the role.
    got = check("BAE Systems", "has", "Charles Woodburn as CEO",
                "prezes BAE Systems, Charles Woodburn, nazwal turecki zakup")
    assert got == ("bae", "Charles Woodburn", "CEO", False), got
    # A compound title is ONE title. Read as "Chairman OF <a division called President
    # and Chief Executive Officer>" this printed as gibberish on AeroVironment's card.
    got = check("Wahid Nawabi", "is",
                "AeroVironment Chairman, President and Chief Executive Officer",
                "AeroVironment Chairman, President and CEO Wahid Nawabi said")
    assert got and got[2] == "Chairman, President and Chief Executive Officer", got


def test_the_role_must_be_current():
    # The corpus names outgoing chiefs as often as sitting ones.
    assert not check("Mr Hudson", "served as CEO of", "Rheinmetall Landsysteme GmbH",
                     "Mr Hudson has headed Rheinmetall's Combat Platforms business unit "
                     "and served as the CEO of Rheinmetall Landsysteme GmbH")
    assert not check("Ursa Major", "names", "former Maxar CEO",
                     "Ursa Major names former Maxar CEO as its new chief executive")
    # "tenure as" is past, and it was the ONLY marker in this sentence: Raydon Gates
    # took Lockheed Martin's chief-executive seat from Jim Taiclet without it.
    assert not check("Raydon Gates", "had an outstanding tenure as",
                     "Lockheed Martin's Chief Executive in Australia and New Zealand",
                     "Raydon Gates has had an outstanding tenure as Lockheed Martin's "
                     "Chief Executive in Australia and New Zealand")


def test_the_office_belongs_to_this_company():
    # A subsidiary is not its parent, however exactly the name prefixes it.
    assert not check("Per Ahl", "is", "CEO of Saab Digital Air Traffic Solutions",
                     "Per Ahl is CEO of Saab Digital Air Traffic Solutions (SDATS)")
    # `aliases.fold` drops a legal suffix, so "BAE Systems, Inc." folded to the plc and
    # handed London the chief executive of its Virginia subsidiary.
    assert not check("Tom Arseneault", "is President and Chief Executive Officer of",
                     "BAE Systems, Inc.",
                     "Tom Arseneault is President and CEO of BAE Systems, Inc.,")
    # `same_org` only refuses EXTRA tokens, so a phrase SHORTER than the roster name
    # passes it trivially: the President of Israel became an officer of Israel
    # Aerospace Industries.
    assert not check("Reuven Rivlin", "is", "the President of Israel",
                     "Israel Aerospace Industries hosted the President of Israel, "
                     "Reuven Rivlin.")
    # A role that merely shares a sentence with the company belongs to whoever it sits
    # next to.
    assert not check("Mr. Lynn", "supported",
                     "Senator Kennedy's work as Chairman of the Seapower Subcommittee",
                     "he supported Senator Kennedy's work as Chairman of the Seapower "
                     "Subcommittee.")


def test_a_division_is_named_as_a_division():
    # Not refused -- these are real officers. But "President of Naval Power at Raytheon"
    # printed as Raytheon's president, above the company's actual chief executive.
    got = check("Barbara Borgonovi", "is president of", "Naval Power at Raytheon",
                "Barbara Borgonovi, president of Naval Power at Raytheon.")
    assert got == ("ray", "Barbara Borgonovi", "President of Naval Power", True), got
    # A comma introduces a division as readily as "of" does.
    got = check("Mika Kari", "is", "President, Land Business Unit at Patria",
                "President, Land Business Unit Mika Kari")
    assert got == ("patria", "Mika Kari", "President of Land Business Unit", True), got
    # Company-as-subject must obey the same rule: this appointment is at Saab Australia.
    got = check("Saab", "has appointed Mr Andy Keough as",
                "the new Managing Director of Saab Australia",
                "Saab has appointed Mr Andy Keough as the new Managing Director of "
                "Saab Australia.")
    assert got == ("saab", "Andy Keough", "Managing Director of Saab Australia", True), got


def test_politicians_and_organisations_are_not_officers():
    # A head of state's title sits IN FRONT of the name; an officer's sits behind it.
    assert not check("Donald Trump", "strengthened the momentum after",
                     "President Donald Trump's decision on Rheinmetall",
                     "Following President Donald Trump's decision, Rheinmetall "
                     "strengthened the major momentum it had built")
    assert not check("Andrej Plenkovic", "is", "Rheinmetall Prime Minister",
                     "Prime Minister Andrej Plenkovic visited Rheinmetall")
    # Two capitalised words is not personhood. Both of these were published as chief
    # executives before the typed-Person corroboration existed.
    assert not check("Al Qaeda", "is", "the CEO of Lockheed Martin",
                     "Lockheed Martin ... Al Qaeda ... CEO")
    assert not check("Lockheed Martin", "is", "President of Raytheon programmes",
                     "Lockheed Martin, President of Raytheon programmes")
    # A surname behind an honorific names nobody.
    assert not L.looks_like_person("Mr Hudson")
    assert L.looks_like_person("Micael Johansson")


def test_one_seat_per_office_and_one_spelling_per_person():
    # A company has one chief executive. Nothing in either sentence says which of these
    # is current, so printing both as "President and CEO" states something false.
    people = {"a": {"name": "Micael Johansson", "roles": {"President and CEO": 9},
                    "unit": False, "url": "u1", "line": "l1"},
              "b": {"name": "Hakan Buskhe", "roles": {"President and CEO": 3},
                    "unit": False, "url": "u2", "line": "l2"}}
    out = L.seat(people)
    assert [r["value"] for r in out] == ["Micael Johansson"], out

    # One person, two spellings, two titles -- Lockheed printed Taiclet twice.
    merged = L.merge_spellings({
        "x": {"name": "James D. TAICLET", "roles": {"President and CEO": 2},
              "unit": False, "url": "u", "line": "l"},
        "y": {"name": "Jim Taiclet", "roles": {"Chairman": 5},
              "unit": False, "url": "u", "line": "l"}})
    assert len(merged) == 1, merged
    only = list(merged.values())[0]
    assert only["name"] == "Jim Taiclet", only          # best-attested, not longest
    assert only["roles"] == {"President and CEO": 2, "Chairman": 5}, only

    # A typo is a spelling, and it is one character longer than the right name.
    merged = L.merge_spellings({
        "x": {"name": "Colina Whelan", "roles": {"President": 1}, "unit": False,
              "url": "u", "line": "l"},
        "y": {"name": "Colin Whelan", "roles": {"President": 6}, "unit": False,
              "url": "u", "line": "l"}})
    assert list(merged.values())[0]["name"] == "Colin Whelan", merged


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print("  ok   %s" % name, flush=True)
        except AssertionError as e:                       # noqa: PERF203
            fails += 1
            print("  FAIL %s: %s" % (name, e), flush=True)
    L._demo()
    if fails:
        raise SystemExit("%d leadership regression(s) failed" % fails)
    print("test_leadership: ok", flush=True)


if __name__ == "__main__":
    main()
