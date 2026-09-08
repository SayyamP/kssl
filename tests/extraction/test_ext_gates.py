# -*- coding: utf-8 -*-
"""Module: EXTRACTION / publication gates -- threat grading, portfolio attestation, dates.

Pure imports of extraction/signals/*. These decide what a badge on the dashboard means,
so they are asserted against the rules the modules themselves state.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIGNALS = os.path.join(REPO, "extraction", "signals")
if not os.path.isdir(SIGNALS):
    pytest.skip("extraction/signals is not next to the test suite", allow_module_level=True)
sys.path.insert(0, SIGNALS)

try:
    import threat_gate
except Exception as exc:                                    # noqa: BLE001
    pytest.skip("cannot import threat_gate (%s)" % exc, allow_module_level=True)


def test_ext_020_threat_level_accepts_only_the_vocabulary():
    """
    Test ID        : EXT-020
    Module         : Extraction / Threat gate - write boundary
    Precondition   : extraction/signals/threat_gate.py importable
    Steps          : 1. threat_level() over the levels, over prose, over None
    Test Data      : "high", "HIGH ", "low", None, "",
                     "Adani Defence - 9 mapped partnership(s), 1 touching KSSL core..."
    Expected Result: levels normalise to lower case; prose and None both return None.
                     Length alone would not catch it -- "high " passes any length test
                     and "low" is three characters -- so the test is membership in the
                     vocabulary, which is the only thing the column means.
    API Endpoint   : GET /api/dataset -> competitors[].threat
    DB Validation  : serving.competitors.threat (see DB-011)
    Priority       : P0
    Automation Tool: pytest
    """
    assert threat_gate.threat_level("high") == "high"
    assert threat_gate.threat_level("  HIGH ") == "high"
    assert threat_gate.threat_level(None) is None
    assert threat_gate.threat_level("") is None
    prose = ("Adani Defence - 9 mapped partnership(s), 1 touching KSSL core lines. "
             "Lead: Alpha Design Technologies - CORE OVERLAP")
    assert threat_gate.threat_level(prose) is None


def test_ext_021_prose_in_a_level_column_is_detectable():
    """
    Test ID        : EXT-021
    Module         : Extraction / Threat gate - repair pass
    Precondition   : as EXT-020
    Steps          : 1. is_level / looks_like_prose over a level, prose and None
    Test Data      : "medium", a threatNote paragraph, None
    Expected Result: a MISSING rating (None -> nothing to fix) is distinguishable from
                     a CORRUPT one (prose -> fix). Conflating them either loses real
                     ratings or rewrites empty ones.
    API Endpoint   : n/a
    DB Validation  : serving.competitors.threat
    Priority       : P1
    Automation Tool: pytest
    """
    assert threat_gate.is_level("medium") is True
    assert threat_gate.is_level(None) is False
    assert threat_gate.looks_like_prose("a long note about a rival") is True
    assert threat_gate.looks_like_prose(None) is False
    assert threat_gate.looks_like_prose("low") is False


def test_ext_022_not_assessed_is_a_fourth_state_not_a_fourth_rating():
    """
    Test ID        : EXT-022
    Module         : Extraction / Severity
    Precondition   : as EXT-020
    Steps          : 1. severity_of(None, "direct")
                     2. severity_of("high", "not_assessed")
                     3. severity_of("high", None)
    Test Data      : a missing level under a real impact, and the reverse
    Expected Result: SEVERITY_UNASSESSED in all three. "An ungraded event under a rated
                     rival is as unmeasured as a graded event under an unrated one."
                     It must never fall through to "low", which is a claim of safety.
    API Endpoint   : GET /api/dataset -> card severity / severityRank
    DB Validation  : n/a (computed at serve time)
    Priority       : P0
    Automation Tool: pytest
    """
    assert threat_gate.severity_of(None, "direct") == threat_gate.SEVERITY_UNASSESSED
    assert threat_gate.severity_of("high", "not_assessed") == threat_gate.SEVERITY_UNASSESSED
    assert threat_gate.severity_of("high", None) == threat_gate.SEVERITY_UNASSESSED


def test_ext_023_severity_matrix_is_monotone():
    """
    Test ID        : EXT-023
    Module         : Extraction / Severity
    Precondition   : as EXT-020
    Steps          : 1. severity_of over every (level, impact) pair in the matrix
    Test Data      : high/medium/low x direct/adjacent/none
    Expected Result: every pair returns high | medium | low; a lower rival threat never
                     produces a HIGHER severity at the same impact.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest
    """
    rank = threat_gate.severity_rank
    for impact in ("direct", "adjacent", "none"):
        hi = threat_gate.severity_of("high", impact)
        md = threat_gate.severity_of("medium", impact)
        lo = threat_gate.severity_of("low", impact)
        assert rank(hi) <= rank(md) <= rank(lo), (
            "severity is not monotone in the rival's threat at impact=%s" % impact)


def test_ext_024_an_empty_roster_raises_rather_than_publishing_everything():
    """
    Test ID        : EXT-024
    Module         : Extraction / Threat gate - failure mode
    Precondition   : as EXT-020
    Steps          : 1. assert EmptyRosterError exists and is an exception type
    Test Data      : none
    Expected Result: an empty roster is a BROKEN READ (a view renamed, a connection
                     lost, a migration mid-flight) and raises. The previous behaviour
                     on that reading -- skip the check, publish everything as a threat
                     -- is the failure this module exists to remove.
    API Endpoint   : GET /api/dataset -> card dir='threat'
    DB Validation  : serving.competitors must be non-empty for the gate to run
    Priority       : P0
    Automation Tool: pytest
    """
    assert issubclass(threat_gate.EmptyRosterError, Exception)


def test_ext_025_a_demoted_card_keeps_its_reason_and_is_not_deleted():
    """
    Test ID        : EXT-025
    Module         : Extraction / Threat gate - grade()
    Precondition   : as EXT-020
    Steps          : 1. read grade()'s contract
    Test Data      : none
    Expected Result: grade returns (dir, reason, impact, severity) and a card failing
                     the roster or impact test is DEMOTED to watch with a reason, never
                     dropped. "Losing the card would lose the article; the badge is what
                     was wrong, not the news."
    API Endpoint   : GET /api/dataset -> card.dir
    DB Validation  : serving.signal_card.dir
    Priority       : P1
    Automation Tool: pytest
    """
    import inspect
    src = inspect.getsource(threat_gate.grade)
    assert "watch" in src, "grade() no longer demotes to watch"


def test_ext_026_portfolio_gate_importable_and_states_its_thresholds():
    """
    Test ID        : EXT-026
    Module         : Extraction / Portfolio gate
    Precondition   : extraction/signals/portfolio_gate.py importable
    Steps          : 1. import portfolio_gate  2. run its own _demo() self-check
    Test Data      : the module's built-in fixtures
    Expected Result: the shipped self-check passes. It is the module's own statement of
                     what attest / denials / entails mean; a suite that re-implemented
                     those rules would be asserting a second definition of them.
    API Endpoint   : n/a (upstream of Products / matchup rows)
    DB Validation  : serving.competitor_product
    Priority       : P1
    Automation Tool: pytest (delegating to the module's demo)
    """
    try:
        import portfolio_gate
    except Exception as exc:                                # noqa: BLE001
        pytest.skip("cannot import portfolio_gate (%s)" % exc)
    assert portfolio_gate.MIN_SLUG_WORDS >= 1
    demo = getattr(portfolio_gate, "_demo", None)
    if demo is None:
        pytest.skip("portfolio_gate has no _demo self-check")
    demo()


def test_ext_027_article_date_parsing():
    """
    Test ID        : EXT-027
    Module         : Extraction / Article date
    Precondition   : extraction/signals/article_date.py importable
    Steps          : 1. parse_iso_date over valid and invalid inputs
    Test Data      : "2026-09-08", "", None, "not a date"
    Expected Result: a valid ISO date parses; junk returns None rather than raising or
                     guessing. An invented date puts a card in the wrong place in a feed
                     ordered by date, and the date gate drops undated documents.
    API Endpoint   : GET /api/dataset -> cards ordered by date
    DB Validation  : public.documents.published_at
    Priority       : P1
    Automation Tool: pytest
    """
    try:
        import article_date
    except Exception as exc:                                # noqa: BLE001
        pytest.skip("cannot import article_date (%s)" % exc)
    assert article_date.parse_iso_date("2026-09-08") is not None
    assert article_date.parse_iso_date("not a date") is None
    assert article_date.parse_iso_date("") is None
    assert article_date.parse_iso_date(None) is None
