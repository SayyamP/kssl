"""Continuous crawl scheduler: what to fetch next, so a fresh signal lands every day.

THE PROBLEM
-----------
Fixed tiers (daily/weekly/monthly) are set once and drift. Measured on the live
catalogue, 27 news sources sit in the wrong tier -- 14 crawled TOO SLOWLY
(infodefensa.com changes 72 times a day and was visited monthly) and 13 crawled
too often for what they publish. 13 of them should be on a daily cadence.
Meanwhile the crawl budget is finite and a browser page costs 20-50x an httpx one.

The scheduler answers one question in a loop: of everything I could fetch right
now, which page buys the most NEW SIGNAL per second of crawl?

    priority = expected_new_signals / expected_cost_seconds

where
    expected_new_signals = min(lambda * elapsed_days, RETRIEVABLE_PAGES) * yield
    lambda   changes/day, measured, cadence-invariant (site_measurements)
    yield    fraction of this source's articles clearing presignal.PASS_THRESHOLD
    cost     measured crawl seconds, x1 for httpx, x25 for a browser tier,
             discounted where a cheap change-probe exists

THE TRAP THIS DESIGN AVOIDS
---------------------------
`yield` comes from presignal.py, whose vocabulary is far better in English than
in Korean. Measured per language on live pages, portfolio-term coverage ran from
57% (tr) to 0% in several languages. Ranking sources on the RAW yield would
therefore rank the SCORER'S VOCABULARY, not the sources -- and would starve every
language the vocabulary is thin in, permanently, while looking like a clean
optimisation. So yield is normalised WITHIN a language cohort: a source is judged
against others in its own language, never across.

That is a mitigation, not a fix, and it does not resolve itself: a cohort the
scorer cannot read stays tied at "no information" no matter how often it is
crawled. Only vocabulary work moves it. (presignal_terms.py is where that work
goes; the audit that produced this note is recorded in continuous_signal_crawl.html.)

WHAT THIS MODULE IS NOT
-----------------------
It is a pure ranking function over a list you hand it. It does NOT read
site_measurements, does not persist anything, and does not update `hours_since`
or `lam` after a crawl. The caller owns that loop, and the caller is where the
following must live or the ranking is meaningless:

    * refresh lam / yield_ from measurements after each completed crawl
    * set hours_since = 0 on SUCCESS only, and increment consecutive_failures
      on failure (otherwise a dead source is re-picked forever)
    * re-measure supports_304: a site that stops emitting ETags still gets the
      probe discount here and will silently overrun the budget
    * carry realised seconds into the next window -- `plan()` budgets EXPECTED
      cost, and a 304 source that did change costs ~26x its charge
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# A browser fetch costs 20-50x an httpx one (measured on this box). Using the
# low end: the scheduler should be reluctant, not absolutist.
BROWSER_COST_MULTIPLIER = 25.0

# Never let a source go unvisited longer than this, whatever the maths says. A
# lambda is an estimate from a handful of runs; starving a source forever on a
# weak estimate is how a source silently dies. Applies per fetch class.
MAX_SILENCE_DAYS = {"httpx": 7.0, "browser": 21.0}

# Cheap change-probes, as a fraction of a full crawl. These are NOT the same
# mechanism and must not share a constant: a conditional GET is one request with
# no body, a depth-0 sentinel is a real fetch and parse of the front page.
# Both numbers are estimates until the crawler reports probe seconds separately.
PROBE_COST_FRACTION = {"304": 0.04, "sentinel": 0.15}

# How much genuinely new material ONE crawl can come back with. A site that
# changes 70 times a day has not left 70 distinct stories reachable after a day
# of silence -- the front page holds a fixed number of links and the crawler only
# sees what is still linked. This is a PAGE constraint, so it is a constant: the
# earlier `min(lam*days, lam*3)` was `lam * min(days, 3)`, which scales with lam
# and therefore caps nothing for exactly the fast sources it was written for.
RETRIEVABLE_PAGES = 40.0

# What to assume about a source that has never been measured. Not zero: zero is
# a measurement, and treating "unknown" as "barren" is how a source that changes
# 70 times a day sits unvisited behind a starvation guard for a week.
EXPLORE_LAM = 1.0

# After this many consecutive failures a source stops being scheduled at all and
# belongs to the host circuit breaker. Without it the starvation guard pins a
# dead source at top priority forever and it becomes a permanent budget tax.
MAX_CONSECUTIVE_FAILURES = 3


# eq=False: two sources with identical parameters are still two different
# sources. With dataclass value-equality, `s not in chosen` treats them as the
# same row and drops one of them from the plan.
@dataclass(eq=False)
class Source:
    domain: str
    lam: float | None = None         # changes per DAY (measured); None = never measured
    yield_: float | None = None      # fraction clearing presignal.PASS_THRESHOLD; None = unmeasured
    cost_s: float = 60.0             # measured seconds for a full crawl
    browser: bool = False            # needs C3/C4
    supports_304: bool = False       # honours If-None-Match / If-Modified-Since
    sentinel: bool = False           # cheap depth-0 change probe is configured
    language: str = "en"
    hours_since: float = 24.0        # since last SUCCESSFUL crawl
    consecutive_failures: int = 0
    # filled by the scheduler
    priority: float = 0.0
    cost: float = 0.0
    starved: bool = False
    reason: str = ""


def _lam(s: Source) -> float:
    return EXPLORE_LAM if s.lam is None else s.lam


def normalise_yield(sources) -> dict:
    """Rank each source's yield WITHIN its language cohort, returning 0..1.

    A cohort of one, or a source with no measured yield, gets 0.5 -- neutral. We
    know nothing about it relative to its peers, and inventing a number in either
    direction is worse than saying 'no information'."""
    by_lang = {}
    for s in sources:
        by_lang.setdefault(s.language, []).append(s)
    out = {}
    for lang, group in by_lang.items():
        measured = [s for s in group if s.yield_ is not None]
        for s in group:
            if s.yield_ is None:
                out[s.domain] = 0.5
        if len(measured) < 2:
            for s in measured:
                out[s.domain] = 0.5
            continue
        ys = [s.yield_ for s in measured]
        n = len(ys)
        for s in measured:
            # MID-rank, not "count at or below". With the plain version, a cohort
            # where every source scores the same -- which is what a language the
            # scorer has no vocabulary for looks like -- normalises everyone to
            # 1.0, the maximum, and promotes a source we know nothing about above
            # sources we have measured. Averaging the strict and inclusive counts
            # puts a total tie at 0.5: "no information", which is the truth.
            lo = sum(1 for y in ys if y < s.yield_)
            hi = sum(1 for y in ys if y <= s.yield_)
            r = (lo + hi) / (2.0 * n)
            # Then rescale so the ceiling does not depend on cohort SIZE. Raw
            # mid-rank caps the best of n at 1 - 1/(2n): 0.75 for a pair, 0.95
            # for ten. That discounts the top source of every small-language
            # cohort by ~25% against its English peers purely for having fewer
            # peers -- a structural bias against exactly the languages the
            # cohort split exists to protect. A tie still maps to 0.5.
            out[s.domain] = 0.5 + (r - 0.5) * n / (n - 1)
    return out


def effective_cost(s: Source) -> float:
    """Expected seconds to find out whether this source has anything new.

    THE ONLY PLACE THIS ARITHMETIC LIVES. It used to be computed once in
    score_source (to print in `reason`, then discarded) and again in plan() (to
    spend the budget). They agreed on the day they were written, which is the
    whole problem with computing a number twice."""
    base = max(s.cost_s * (BROWSER_COST_MULTIPLIER if s.browser else 1.0), 1.0)

    frac = None
    if s.supports_304:
        frac = PROBE_COST_FRACTION["304"]
    elif s.sentinel:
        frac = PROBE_COST_FRACTION["sentinel"]
    if frac is None:
        return base

    days = max(s.hours_since, 0.01) / 24.0
    p_changed = 1.0 - math.exp(-_lam(s) * days)     # Poisson: P(at least one change)
    # min(1.0, ...): probe THEN crawl costs more than crawling once, so above
    # p_changed ~= 0.96 the right move is to skip the probe. Without the clamp a
    # 304-capable source was charged 1.04x a full crawl and ranked BELOW its
    # non-304 twin at any lambda above ~3/day -- i.e. the discount inverted for
    # every source fast enough to be worth polling daily.
    return base * min(1.0, frac + p_changed)


def score_source(s: Source, ynorm: float) -> Source:
    days = max(s.hours_since, 0.01) / 24.0
    cls = "browser" if s.browser else "httpx"
    lam = _lam(s)

    expected = min(lam * days, RETRIEVABLE_PAGES)
    s.cost = effective_cost(s)
    s.priority = (expected * max(ynorm, 0.05)) / s.cost
    s.starved = False

    probe = ("304 probe" if s.supports_304
             else "sentinel probe" if s.sentinel else "full crawl")
    basis = "lam" if s.lam is not None else f"UNMEASURED lam, exploring at {EXPLORE_LAM}"

    if s.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        # Not starving -- broken. Hand it to the host circuit breaker instead of
        # letting the starvation guard re-pick it every window forever.
        s.priority = 0.0
        s.reason = (f"{s.consecutive_failures} consecutive failures - "
                    f"withheld for the host breaker")
    elif s.hours_since / 24.0 >= MAX_SILENCE_DAYS[cls]:
        # + hours_since so starved sources order by HOW starved. A flat 1e6 made
        # them all tie, and the stable sort then picked by list position, which
        # can visit the least starved first under budget pressure.
        s.priority = 1e6 + s.hours_since
        s.starved = True
        s.reason = f"starvation guard: {s.hours_since / 24:.1f}d without a successful visit"
    else:
        s.reason = (f"{basis}={lam:.2f}/d x {days:.2f}d x yield_norm={ynorm:.2f} "
                    f"/ cost={s.cost:.0f}s ({probe})")
    return s


def plan(sources, budget_seconds: float):
    """Fill one scheduling window. Returns (chosen, skipped, spent_seconds).

    Starved sources are funded FIRST and are allowed to take the window over
    budget once, because the greedy fill alone cannot honour the guarantee the
    guard is making: a browser source costing more than a whole window was
    skipped silently, every window, forever -- priority 1e6 and never crawled.
    Anything still unaffordable after that keeps `starved` set and says so in
    `reason`, so it shows up as a budget problem instead of vanishing."""
    ynorm = normalise_yield(sources)
    ranked = sorted((score_source(s, ynorm[s.domain]) for s in sources),
                    key=lambda s: -s.priority)

    chosen, spent = [], 0.0
    taken = set()

    for s in ranked:
        if not s.starved:
            continue
        if spent >= budget_seconds:
            s.reason += " - STARVED BUT UNFUNDABLE: the window is already full"
            continue
        chosen.append(s)
        taken.add(id(s))
        spent += s.cost

    for s in ranked:
        if id(s) in taken or s.priority <= 0.0:
            continue
        if spent + s.cost > budget_seconds:
            continue
        chosen.append(s)
        taken.add(id(s))
        spent += s.cost

    return chosen, [s for s in ranked if id(s) not in taken], spent


def demo():
    """The ordering claims must hold, or this is just arithmetic with opinions."""
    fast_rich = Source("infodefensa.com", lam=72.3, yield_=0.30, cost_s=60, language="es")
    fast_poor = Source("topwar.ru", lam=20.0, yield_=0.00, cost_s=60, language="ru")
    slow_rich = Source("defense-aerospace.com", lam=0.5, yield_=0.80, cost_s=60, language="en")
    browsery = Source("defenseindustrydaily.com", lam=6.2, yield_=0.30, cost_s=60,
                      browser=True, language="en")
    peer_es = Source("defensa.com", lam=1.5, yield_=0.10, cost_s=60, language="es")
    peer_ru = Source("vpk.name", lam=5.0, yield_=0.00, cost_s=60, language="ru")
    srcs = [fast_rich, fast_poor, slow_rich, browsery, peer_es, peer_ru]

    chosen, skipped, spent = plan(srcs, budget_seconds=200)
    for s in sorted(srcs, key=lambda x: -x.priority):
        print(f"  {s.domain:26s} pri={s.priority:9.4f}  {s.reason}")

    # 1. yield must matter ON ITS OWN. The first version of this check compared
    #    two sources whose LAMBDAS also differed 3.6x, so it passed with yield
    #    hardcoded to a constant -- it proved nothing at all.
    a = Source("a.com", lam=10.0, yield_=0.9, cost_s=60, language="en")
    b = Source("b.com", lam=10.0, yield_=0.1, cost_s=60, language="en")
    yn = normalise_yield([a, b])
    score_source(a, yn["a.com"]); score_source(b, yn["b.com"])
    assert a.priority > b.priority, "yield must matter with lambda held equal"

    # 2. a browser source must be penalised against an identical httpx one
    same = Source("x.com", lam=6.2, yield_=0.30, cost_s=60, language="en")
    score_source(same, 0.5); score_source(browsery, 0.5)
    assert same.priority > browsery.priority, "browser cost must be charged"

    # 3. language normalisation: the Russian pair must not both be crushed just
    #    because the scorer has poor Russian vocabulary
    yn = normalise_yield(srcs)
    assert yn["vpk.name"] > 0 and yn["topwar.ru"] > 0, "a whole language cohort was zeroed"
    # ...but an all-tied cohort must sit at "no information", not at the top
    assert abs(yn["vpk.name"] - 0.5) < 1e-9, f"tied cohort not neutral: {yn['vpk.name']}"
    # a cohort the scorer CAN read must still spread out rather than all tie
    assert yn["infodefensa.com"] != yn["defensa.com"], "measured cohort collapsed to one value"
    # and the top of a 2-cohort must not be discounted against the top of a 10-cohort
    big = [Source(f"d{i}.com", lam=1, yield_=i / 10.0, language="xx") for i in range(10)]
    ynb = normalise_yield(big)
    assert abs(max(ynb.values()) - max(yn["infodefensa.com"], yn["defensa.com"])) < 1e-9, \
        "cohort size changes the ceiling"
    # an unmeasured yield is neutral, not bottom
    unm = Source("new.com", lam=1, yield_=None, language="es")
    assert normalise_yield(srcs + [unm])["new.com"] == 0.5, "unmeasured yield ranked as barren"

    # 4. starvation guard fires, and orders by how starved
    stale = Source("quiet.com", lam=0.01, yield_=0.0, cost_s=60, hours_since=24 * 30)
    staler = Source("quieter.com", lam=0.01, yield_=0.0, cost_s=60, hours_since=24 * 60)
    score_source(stale, 0.1); score_source(staler, 0.1)
    assert stale.priority >= 1e6, "starvation guard did not fire"
    assert staler.priority > stale.priority, "starved sources tie instead of ordering"

    # ...and a starved source too expensive for the window is still funded,
    # rather than silently skipped every window forever
    big_browser = Source("huge.gov", lam=1.0, yield_=0.2, cost_s=1500, browser=True,
                         hours_since=24 * 60)
    got, _, _ = plan([big_browser], budget_seconds=600)
    assert big_browser in got, "a starved source the window cannot afford was dropped"

    # 5. 304 support must make a source cheaper AT EVERY CHANGE RATE, not just
    #    at the one the assert happened to pick. At lam=6 the unclamped version
    #    charged MORE than a full crawl and inverted the ranking.
    for lam in (0.5, 2.0, 8.0, 40.0):
        p = Source("p.com", lam=lam, yield_=0.3, cost_s=60, supports_304=True)
        q = Source("q.com", lam=lam, yield_=0.3, cost_s=60)
        score_source(p, 0.5); score_source(q, 0.5)
        assert p.priority >= q.priority, f"304 penalised at lam={lam}"
    # A sentinel probe is cheaper than nothing and dearer than a 304 -- at a
    # change rate where probing is worth it at all. Above p(changed) ~= 0.85 the
    # sentinel discount clamps away, which is the clamp working, not a bug.
    sen = Source("s.com", lam=0.3, yield_=0.3, cost_s=60, sentinel=True)
    p304 = Source("t.com", lam=0.3, yield_=0.3, cost_s=60, supports_304=True)
    plain = Source("u.com", lam=0.3, yield_=0.3, cost_s=60)
    assert effective_cost(p304) < effective_cost(sen) < effective_cost(plain), \
        "the two probe mechanisms are being priced the same"

    # 6. the cap is on PAGES, not on days -- a 200/day source and a 2000/day one
    #    must not differ by 10x in expected yield after a day of silence
    hot = Source("hot.com", lam=2000.0, yield_=0.3, cost_s=60)
    warm = Source("warm.com", lam=200.0, yield_=0.3, cost_s=60)
    score_source(hot, 0.5); score_source(warm, 0.5)
    assert abs(hot.priority - warm.priority) < 1e-9, "expected-new-material cap scales with lambda"

    # 7. a repeatedly-failing source is withheld, not pinned at the top
    dead = Source("dead.com", lam=5.0, yield_=0.3, cost_s=60, hours_since=24 * 30,
                  consecutive_failures=5)
    score_source(dead, 0.5)
    assert dead.priority == 0.0, "a dead source is still being scheduled"

    # 8. plan() itself: budget respected for non-starved work, nothing chosen twice
    pool = [Source(f"p{i}.com", lam=10, yield_=0.3, cost_s=100, language="en") for i in range(10)]
    got, skip, sp = plan(pool, budget_seconds=350)
    assert len(got) == 3 and sp <= 350, f"budget not respected: {len(got)} crawls, {sp}s"
    assert len(got) + len(skip) == len(pool), "a source vanished between chosen and skipped"
    assert len({id(x) for x in got}) == len(got), "a source was chosen twice"

    print(f"\n  window 200 s -> {len(chosen)} crawls, {spent:.0f}s spent")
    print("ok - all eight ordering claims hold")


if __name__ == "__main__":
    demo()
