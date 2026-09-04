"""Which machine takes which document -- the dispatch layer in front of run.py.

    python route.py --enqueue --since 2026-08-26     # corpus -> queue
    python route.py --claim --node vps-a             # one document, leased
    python route.py --reap                           # expired leases back to ready
    python route.py --status                         # the deficit, honestly
    python route.py --demo

WHERE THIS SITS
---------------
    crawler -> postgres.documents -> [route.py] -> run.py --node N -> comprehend() -> store.save()

It replaces build_queue.py's job, not its code: build_queue orders work for ONE machine out of a
local file, and four machines cannot share a JSONL. The ordering insight there still holds and is
kept -- interleave so an interrupted run leaves a balanced corpus -- but the queue has to live
where every node can see it, so it lives in the corpus postgres.

THE ONE FACT THAT SHAPES ALL OF THIS
------------------------------------
Measured 2026-08-27: the crawler delivers a 13-day mean of 9,188 documents/day (peak 18,807,
trough 3,018 -- 6.2x). Three CPU nodes extract ~216/day. That is a **42x deficit**, so this is
admission control, not load balancing. Every document that is not dispatched must be visibly
marked `deferred`, never left in `ready` to rot: a queue that silently grows is how a dashboard
reports green for a month.

FRESH ALWAYS BEATS BACKLOG
--------------------------
Class is (freshness, tier) with freshness dominant -- today's crawl before any historical
document, whatever its tier. That is a product decision, and it has a consequence worth stating
in the code rather than only in a design doc: since fresh alone is 18-42x capacity, **P3 never
runs** until either capacity grows or the crawl rate falls below it. The 1.3M backlog is frozen
on purpose. The one mercy is automatic: on a quiet day the class ladder lets spare capacity fall
through to P3 with no operator action and no separate backlog scheduler.
"""
import argparse
import json
import os
import re
import sys

# --- the cost model -------------------------------------------------------------------------
# Calibrated on the real 600-document run: 2,370 input chars produced a measured mean of 11,418
# output tokens. Generation is 99.99% of wall clock (Python on the hot path measured 0.0056%), so
# this single line IS the cost model. RECOMPUTE WEEKLY -- every threshold below hangs off it, and
# a shift in the crawl mix toward tables or CJK moves it.
ALPHA = 4.82

# The farm serves GLiNER too, at https://ollama.i3softlab.com/extract (already wired as
# C_GLINER_URL in activate.sh). This is a SECOND, separate role and a far better fit for an
# intermittent node than LLM work: a GLiNER call is sub-second (measured 0.17s), so losing one to
# the farm vanishing costs nothing, where losing an LLM document costs up to 40 minutes.
# So when the farm is up, point EVERY node's C_GLINER_URL at it -- CPU nodes get faster even
# while the farm does no LLM work at all. comprehend.py already takes the remote branch whenever
# C_GLINER_URL is set and falls back to the local model when it is not, so this needs no code.
GLINER_URL = "https://ollama.i3softlab.com/extract"


def est_out(chars):
    """Estimated OUTPUT tokens for a document of this many characters."""
    return int(chars * ALPHA)


def est_seconds(chars, tok_per_s):
    return est_out(chars) / max(0.01, tok_per_s)


# --- classes --------------------------------------------------------------------------------
# Strict classes, not a weighted score. A score like w1*delta + w2*tier cannot express "fresh
# always wins": pick any tier weight and some sufficiently high-tier backlog document outranks a
# fresh one. At 42x oversubscription the weights would not matter anyway -- the top class eats
# everything -- so the tuning surface is pure liability.
P0, P1, P2, P3 = 0, 1, 2, 3
CLASS_NAME = {P0: "P0 fresh/strong", P1: "P1 fresh/mid", P2: "P2 fresh/weak", P3: "P3 backlog"}

FRESH_HOURS = 24

# presignal.py answers "is this worth 13 minutes of Layer A?" from raw text in under half a
# millisecond, against the same reference_dataset.json the card writer uses. Measured on 1,250
# real trade-press pages: 34% pass at 45, and the other 822 would have cost 184 CPU-HOURS to
# refuse downstream. Nothing else in this pipeline has that ratio, so the gate runs before the
# queue, not after it.
PASS_THRESHOLD = 45

# TRUST TIER IS NOT A PRIORITY KEY. This is the correction that matters most here, and it is not
# an opinion -- it is their measurement. Scored on the same 1,250 pages, tier 1 returns 30%,
# tier 2 returns 39%, tier 3 returns 31%. Trust and productivity are uncorrelated, and if
# anything tier 2 leads. The sharpest case is idrw.org: a tier-3 aggregator with the joint-highest
# yield of any measured source at 72%. Crawl it eagerly, cite it never.
#
#   "Any design that folded trust into crawl priority would have thrown that source away."
#
# An earlier version of this router did exactly that -- P0 = tier 1 -- which would have starved
# the most productive source in the catalogue while looking principled. Trust now rides along as
# metadata for the downstream card gate (publishable()), and decides nothing about dispatch.
#
# Note also the fourth state: `unrated` is NOT a synonym for tier 3. It means nobody has assessed
# the source, which is the same rule this project applies to every unmeasured number.
TIER_UNRATED, TIER_1, TIER_2, TIER_3 = 0, 1, 2, 3


def klass(presignal_pct, age_hours):
    """(within-language percentile of the presignal score, hours since fetch) -> class.

    Freshness dominates, as the product requires: today's crawl before any historical document.
    Within fresh, rank by how much signal the document carries -- not by who published it.

    WHY A PERCENTILE AND NOT THE RAW SCORE. The scorer's own vocabulary coverage differs wildly by
    language: 62% of Polish pages match, against 8% of Hebrew. Ranking on the raw number would
    rank the SCORER'S VOCABULARY rather than the documents, quietly starving every non-English
    source -- including the Indian ones -- while looking like a clean optimisation. Their crawl
    scheduler hit this exact trap and normalises within a language cohort; so does this. A cohort
    where every source ties lands at 0.5, "no information", rather than at the top.
    """
    if age_hours >= FRESH_HOURS:
        return P3
    if presignal_pct >= 0.75:
        return P0
    if presignal_pct >= 0.40:
        return P1
    return P2


# --- delegated scorers ----------------------------------------------------------------------
_PRESIGNAL_FN = None
_PRESIGNAL_WHY = "not looked up yet"


def _load(modname, attr, cands):
    import pathlib as _pl
    for c in cands:
        if not c or not _pl.Path(c, modname + ".py").exists():
            continue
        if c not in sys.path:
            sys.path.insert(0, c)
        try:
            mod = __import__(modname)
            fn = getattr(mod, attr, None)
            if fn:
                return fn, c
        except Exception as e:
            return None, "%s: %s" % (c, type(e).__name__)
    return None, modname + ".py not found on any candidate path"


def _search_paths():
    import os
    import pathlib as _pl
    here = _pl.Path(__file__).resolve().parent
    return [os.environ.get("C_TIERS_PATH"),
            str(here.parent.parent / "app" / "pipeline"),
            str(here.parent.parent.parent / "app" / "pipeline"),
            str(here)]


def presignal_of(text, title="", published_at=None):
    """Raw presignal score for a document. Delegated -- the vocabulary lives in
    reference_dataset.json and must not be forked into this file, or the router and the card
    writer would silently disagree about what counts as signal."""
    global _PRESIGNAL_FN, _PRESIGNAL_WHY
    if _PRESIGNAL_FN is None:
        for attr in ("score", "presignal", "score_text"):
            fn, why = _load("presignal", attr, _search_paths())
            if fn:
                _PRESIGNAL_FN, _PRESIGNAL_WHY = fn, why
                break
        else:
            _PRESIGNAL_WHY = why
    if _PRESIGNAL_FN is None:
        return None
    try:
        # published_at is passed through because the date usually lives in the database column,
        # not the prose: on 1,200 real documents a body-text regex missed it in 73% of cases while
        # the column was populated for 66%. Dropping it here would reinstate a -15 on most of the
        # corpus. Older scorers without the parameter still work -- hence the fallback.
        blob = (title + "\n" + text) if title else text
        try:
            r = _PRESIGNAL_FN(blob, published_at=published_at)
        except TypeError:
            r = _PRESIGNAL_FN(blob)
        return r.get("score") if isinstance(r, dict) else (r[0] if isinstance(r, tuple) else r)
    except Exception:
        return None


def presignal_available():
    """Available means the scorer has its DATASET, not merely that the module imported.

    A scorer with no ds.json still compiles its hard-coded category and event patterns and returns
    numbers -- blind to the +40 competitor signal, so it would gate on 25 where the real answer is
    65. That fails quietly and in the wrong direction, refusing exactly the documents worth
    keeping. So readiness is asked of the module, not inferred from the import succeeding.
    """
    if _PRESIGNAL_FN is None:
        presignal_of("probe")
    if _PRESIGNAL_FN is None:
        return False, _PRESIGNAL_WHY
    try:
        import presignal
        ok, where = presignal.ready()
        return ok, (where if ok else "loaded but blind: %s" % where)
    except Exception:
        return True, _PRESIGNAL_WHY          # older scorer with no ready(): trust the import


def percentile_within(score, cohort_scores):
    """Where this score sits inside its own language cohort, 0..1.

    An all-tied cohort returns 0.5 -- "no information" -- deliberately, rather than 1.0. A cohort
    in which nothing distinguishes the documents must not be promoted to the top of the queue on
    the strength of that tie.
    """
    if not cohort_scores:
        return 0.5
    lo = sum(1 for x in cohort_scores if x < score)
    eq = sum(1 for x in cohort_scores if x == score)
    if eq == len(cohort_scores):
        return 0.5
    return (lo + eq / 2.0) / len(cohort_scores)


# --- nodes ----------------------------------------------------------------------------------
# cap_chars is a HARD ELIGIBILITY CONSTRAINT, never a score term, because a score can be outvoted
# and this one cannot afford to be: the corpus contains a 19,662,845-char document which would
# occupy VPS-A for 71 DAYS. Caps are set at measured percentiles of the real 1.3M-doc
# distribution so each node's worst case is a known number of minutes.
#
# Neither pre-emptible node may hold P0: the farm can vanish mid-document and VPS-B must yield to
# customers, so putting the latency promise on either is a promise you cannot keep.
# Each node declares the WORST-CASE MINUTES it is willing to spend on one document; the character
# cap is derived from that and the node's measured speed. Expressing it this way means the policy
# is the number a human reasons about ("VPS-A must never be blocked for more than 20 minutes"),
# and a speed change re-derives the cap automatically -- if VPS-B's memory cap is raised and it
# goes 3.8 -> 15 tok/s, it starts accepting four times longer documents with no edit here.
#
# Neither pre-emptible node may hold P0: the farm can vanish mid-document and VPS-B must yield to
# customers, so putting the latency promise on either is a promise you cannot keep.
NODES = {
    #                max_class  worst-case  tok/s    why that budget
    "vps-a": dict(max_class=P3, minutes=20, tok_s=15.385),
    # MEASURED, not aspirational. Two independent probes of the dc endpoint with the model
    # already resident: 0.83 tok/s (28 tok in 33.8s) and 1.44-1.67 tok/s. The configured 8.765
    # was 5-10x optimistic, and it is not thread oversubscription -- llama-server runs `-t 6` on
    # a 7-core cpuset, correctly. It is a shared, saturated box: memory bandwidth is the ceiling
    # and the dc does not own it.
    #
    # Why this matters more than a wrong dashboard number: cap, lease and stuck-deadline all
    # derive from it. At 8.765 the dc claimed 9,274-char documents needing ~15 HOURS of decode,
    # held them for hours, was stuck-killed, and completed ZERO documents all day while vps-a and
    # vps-b carried the queue. 1.5 is the conservative end of the measured range; it caps the dc
    # near 1,587 chars, which is work it can actually finish.
    "dc":    dict(max_class=P3, minutes=85, tok_s=1.5),
    "vps-b": dict(max_class=P3, minutes=22, tok_s=3.815, min_class=P1),
    "farm":  dict(max_class=P3, minutes=40, tok_s=53.5,  min_class=P1),
}
# vps-a  20 min -- it carries the only latency promise, so it must turn over fast.
# dc     85 min -- always on and promises nothing, so it absorbs the long tail.
# vps-b  22 min -- pre-emptible: a customer request kills the document, so bound what is lost.
# farm   40 min -- reported as often not alive 2-3 hours straight. A lease longer than the node's
#                  typical uptime does not fail once, it fails EVERY time: claimed, half-done,
#                  re-queued, claimed again, forever. RAISE once farm uptime is measured.
#
# Farm speed MEASURED 2026-08-27 against https://ollama.i3softlab.com/v1, not assumed: 150 tokens
# in 2.80s = 53.5 tok/s on `qwen2.5:7b-ollama`, and 43.7 tok/s on the vLLM-backed `qwen2.5:7b`.
# The design originally carried 18.4 (inferred from an old 600-doc run); the farm is ~3x faster
# than that per stream, which is why its 40-minute budget now buys a bigger document than any
# CPU node can take. Concurrency scales sub-linearly -- 72 tok/s at N=1 rising to only ~106 at
# N=12 -- so the farm is a FAST node, not a wide one; do not model it as unlimited workers.
#
# USE THE OLLAMA BACKEND. `qwen2.5:7b-ollama` carries fp_ollama and is the same artefact the CPU
# nodes run (digest 845dbda0ea48); the vLLM-backed `qwen2.5:7b` is a different serving stack and
# very likely a different quantisation. Same name, different weights, silently different spans --
# and the quality gate compares against a Q4_K_M baseline.

# EVERY node reaches P3, and that is not a weakening of fresh-first. The claim orders by class
# ascending, so a node only ever sees backlog when nothing fresher is eligible for it -- fresh
# still wins every contest it enters. What this changes is the case where fresh work exists but
# not for THIS node: VPS-B was capped at P2 and sat idle beside 225 queued P3 documents that only
# the farm could take, while the farm was down. An idle node is not caution, it is waste, and the
# cost of being wrong is bounded anyway: a lost lease re-queues, and store.save is idempotent per
# document_id, so the worst case is spent compute, never damaged data.
#
# fallback_cap lets a node relax its length limit ONLY when nothing within the strict cap is
# eligible. The strict cap exists to bound what a pre-emption throws away, which matters when
# there is other work to do instead; when the alternative is an idle core it stops being a
# sensible trade. Ordered claims are attempted strict-first, so this never pre-empts better work.
FALLBACK_MULTIPLE = 3.0

# ...but a multiple alone is not a bound. Three times the DC's 85-minute budget is FOUR HOURS on
# one document, which is not a relaxed cap, it is a stalled node -- and a P0 arriving behind it
# waits the whole time. So the fallback is also capped in absolute minutes, and pre-emptible nodes
# get a tighter ceiling because their work is likelier to be thrown away: the farm can vanish
# mid-document and is reported as often not alive for 2-3 hours straight, so a 2-hour fallback
# there would fail every time rather than occasionally.
FALLBACK_MAX_MIN = {"always_on": 90, "preemptible": 60}


# C_NODE_MAX_CLASS lets a worklist-driven deployment claim priority lanes beyond the native P0-P3
# freshness classes. select_worklist.py enqueues the l2_processing_list docs with class = lane
# (P1..P7); without this the nodes' max_class=P3 would leave lanes 4-7 permanently unclaimed.
_MAX_CLASS_OVERRIDE = os.environ.get("C_NODE_MAX_CLASS")
if _MAX_CLASS_OVERRIDE:
    # Only the WORKER's own node (KSSL_NODE) gets the raised ceiling -- raising it on every node
    # trips invariants elsewhere (e.g. the promote check that a live node reaches the P3 backlog).
    _self = os.environ.get("KSSL_NODE", "farm")
    if _self in NODES:
        NODES[_self]["max_class"] = int(_MAX_CLASS_OVERRIDE)

# C_NODE_MIN_CLASS lowers the floor the same way, for a pool that must reach a lane the normal
# workers are fenced out of. The farm's min_class is P1, so class 0 is a lane only an explicitly
# configured pool can claim -- which is how oversize documents get a dedicated drain without a
# second queue.
_MIN_CLASS_OVERRIDE = os.environ.get("C_NODE_MIN_CLASS")
if _MIN_CLASS_OVERRIDE:
    _self = os.environ.get("KSSL_NODE", "farm")
    if _self in NODES:
        NODES[_self]["min_class"] = int(_MIN_CLASS_OVERRIDE)

for _n in NODES.values():
    _n["cap"] = int(_n["minutes"] * 60 * _n["tok_s"] / ALPHA)
    _ceiling = FALLBACK_MAX_MIN["preemptible" if _n.get("min_class", P0) > P0 else "always_on"]
    _n["fallback_cap"] = min(int(_n["cap"] * FALLBACK_MULTIPLE),
                             int(_ceiling * 60 * _n["tok_s"] / ALPHA))
    _n["order"] = "fifo" if _n["max_class"] == P1 or _n["max_class"] == P3 else "short"

# C_NODE_CAP_CHARS raises the length ceiling for one pool without touching `minutes`. The two were
# the same number because a cap derived from a lease window is the honest default -- but the lease
# is now sized per DOCUMENT inside CLAIM (greatest(ttl_floor, 2*chars*sec_per_char + 120)), so a
# long document already gets a long lease and the cap no longer has to encode one.
#
# It exists because 46 documents on the priority worklist sat above the farm's 26,639 cap and were
# not merely last in the queue -- `chars <= cap` is in the claim's WHERE, so they were invisible to
# every worker, forever, with no error anywhere. 37 of them are QinetiQ annual reports, investor
# seminars and interim results: the revenue and profile evidence the worklist exists to collect.
_CAP_OVERRIDE = os.environ.get("C_NODE_CAP_CHARS")
if _CAP_OVERRIDE:
    _self = os.environ.get("KSSL_NODE", "farm")
    if _self in NODES:
        NODES[_self]["cap"] = int(_CAP_OVERRIDE)
        # Relaxed mode must never be SMALLER than strict, or the fallback claim would shrink the
        # ceiling it exists to widen.
        NODES[_self]["fallback_cap"] = max(NODES[_self]["fallback_cap"], NODES[_self]["cap"])


# Above the largest node cap nothing is eligible anywhere and the document is parked for a human.
# Derived, never hard-coded, so a cap change cannot silently orphan a length band into a queue no
# worker will ever claim from.
# Which nodes actually have a worker process. The farm is configured but nothing starts a drain
# for it -- supervise.NODES has no farm entry at all -- so treating it as capacity created a
# 15,149-character band (11,491-26,639) that route() happily marked `ready` and no running node
# could ever claim. `ready` is a claim that the work is dispatchable; for that band it was false.
# Override with C_LIVE_NODES="vps-a,dc,vps-b,farm" the moment a farm worker exists.
LIVE_NODES = tuple(n.strip() for n in
                   os.environ.get("C_LIVE_NODES", "vps-a,dc,vps-b").split(",") if n.strip())

# Park only what NO node could ever take, live or not -- parking is terminal and nothing un-parks,
# so it must mean "impossible", never "nobody is up right now".
PARK_CHARS = max(n["cap"] for n in NODES.values())
# ...while dispatchability is judged against the nodes that are actually running.
LIVE_CAP = max((NODES[n]["cap"] for n in LIVE_NODES if n in NODES), default=0)


def eligible(node, cls, chars):
    """Can this node take this document? Pure predicate, no I/O -- so it is testable."""
    n = NODES[node]
    return (n.get("min_class", P0) <= cls <= n["max_class"]) and chars <= n["cap"]


# The always-on nodes are the only ones that can carry a promise, because the other two can
# disappear mid-document. So they alone decide whether a P0 document can actually BE P0.
ALWAYS_ON = ("vps-a", "dc")


def route(chars, presignal_pct, age_hours):
    """-> (class, [nodes that may take it]). The whole dispatch decision, one pure function.

    Note what is NOT an argument: the trust tier. It rides with the document for the downstream
    card gate and has no vote here.
    """
    if chars > PARK_CHARS:
        return None, []
    c = klass(presignal_pct, age_hours)
    # A class is a PROMISE, and a document that cannot meet the promise must not claim it.
    # A p99 document is 3.5 hours on the DC and over-cap on VPS-A, so no always-on node can
    # deliver it inside a P0 window -- while P0's own rule bars it from the pre-emptible nodes
    # that could. Left as P0 it is eligible NOWHERE, sits in `ready` forever, and is the
    # highest-priority thing in the system. Demote so the farm can take it: later than promised
    # is honest, never is a silent hole.
    if c == P0 and not any(eligible(n, P0, chars) for n in ALWAYS_ON):
        c = P1
    return c, [n for n in NODES if n in LIVE_NODES and eligible(n, c, chars)]


def dispatchable(chars, presignal_pct, age_hours):
    """(class, nodes, state) -- what enqueue should actually write.

    Splits the two questions route() used to blur: what class is this, and can anything RUNNING
    take it. A document only a dead node could serve is `deferred` (visibly not dispatched, and
    recoverable when that node returns), never `ready` (a lie the queue tells about itself) and
    never `parked` (terminal, with no code path out)."""
    c, nodes = route(chars, presignal_pct, age_hours)
    if c is None:
        return None, [], "parked"
    return c, nodes, ("ready" if nodes else "deferred")


# --- the queue ------------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS extract_queue (
  document_id TEXT PRIMARY KEY,
  class       SMALLINT NOT NULL,
  chars       INTEGER  NOT NULL,
  est_out     INTEGER  NOT NULL,
  crawl_ts    TEXT     NOT NULL,
  text_hash   TEXT     NOT NULL,
  state       TEXT     NOT NULL DEFAULT 'ready',
  leased_by   TEXT,
  lease_epoch INTEGER  NOT NULL DEFAULT 0,
  lease_until TIMESTAMPTZ,
  attempts    SMALLINT NOT NULL DEFAULT 0,
  -- WHY a row is in the state it is in. Its absence has now cost three separate things: park()
  -- discarded its reason, `deferred` acquired two indistinguishable meanings, and promote could
  -- not express the policy its own docstring described. A state without a reason is not auditable.
  reason      TEXT
);
ALTER TABLE extract_queue ADD COLUMN IF NOT EXISTS reason TEXT;
-- The claim query filters on (state, class, est_out) and orders within that, so it is one index.
CREATE INDEX IF NOT EXISTS eq_claim ON extract_queue (state, class, est_out, crawl_ts);
CREATE INDEX IF NOT EXISTS eq_lease ON extract_queue (state, lease_until);
"""

# SKIP LOCKED is what makes N workers claim concurrently without a broker. At 0.1 docs/second a
# message queue would be decoration; postgres is already running and already durable.
CLAIM = """
UPDATE extract_queue q SET
  state='leased', leased_by=%(node)s,
  lease_epoch=q.lease_epoch+1, attempts=q.attempts+1,
  -- TTL from the DOCUMENT in hand, not the node's cap. Sized from the cap, the dc's lease was
  -- 172 minutes for every document: a 1,089-char row it finishes in ~9 minutes stayed "in
  -- progress" for nearly three hours after its worker died, invisible to the reap that whole time.
  lease_until=now() + make_interval(secs => greatest(%(ttl_floor)s,
                                                     %(ttl_factor)s * q.chars * %(sec_per_char)s
                                                     + 120))
WHERE q.document_id = (
  SELECT document_id FROM extract_queue
   WHERE state='ready' AND class BETWEEN %(min_class)s AND %(max_class)s AND chars <= %(cap)s
     AND attempts < %(max_attempts)s
   ORDER BY class ASC, {order}
   LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING q.document_id, q.lease_epoch, q.chars, q.text_hash;
"""
ORDER_SQL = {"fifo": "crawl_ts ASC", "short": "est_out ASC"}

# The commit is fenced on lease_epoch. Without this, a worker whose lease expired while it was
# still alive commits on top of a re-run's result -- at-least-once turns into last-writer-wins,
# and in a provenance chain that is not cosmetic. store.save() is already idempotent per
# document_id, so a duplicated LEASE only ever costs compute; only a stale COMMIT can corrupt.
COMMIT = """
UPDATE extract_queue SET state='done', leased_by=NULL, lease_until=NULL
WHERE document_id=%(doc)s AND lease_epoch=%(epoch)s
RETURNING document_id;
"""

# A dead worker announces itself by silence. Nothing else needs to detect the farm going away.
REAP = """
UPDATE extract_queue SET state=CASE WHEN attempts >= %(max_attempts)s
                          THEN 'parked' ELSE 'ready' END,
       leased_by=NULL, lease_until=NULL,
       -- Bump the epoch. Without it a reaped worker keeps a VALID epoch, and because DONE_SQL
       -- checks only (document_id, epoch) and never state, a worker the queue believes it evicted
       -- can still flip its row -- including flipping a `parked` row to `done`, silently undoing
       -- the park decision that evicted it.
       lease_epoch=lease_epoch+1
WHERE state='leased' AND lease_until < now()
RETURNING document_id, attempts;
"""


# Expiry USED to be survivable: a slow worker's late commit still landed, because REAP left the
# epoch alone. Now REAP bumps it, so expiry means the in-flight extraction is discarded outright.
# That makes a tight lease actively destructive: ALPHA is a mean over a corpus whose dense chunks
# need ~4x the tokens and whose hungry scripts cost 1.5-2.3x Latin, so a document above the mean
# could be reaped mid-work every time -- never finishing, parked at three attempts, no alarm.
# The supervisor's stuck-check (3x measured, 1800s floor) is the real defence against a wedged
# worker now, so the lease can afford slack. Slack is cheap; the discard is not.
TTL_FACTOR = 4.0
TTL_FLOOR_S = 1800


def lease_ttl(chars, tok_s):
    """The lease CLAIM grants for one document -- THE definition, in one place.

    It used to say `2 * est + 120` while CLAIM used TTL_FACTOR/TTL_FLOOR_S, so this function kept
    the obvious name and the wrong answer, called only by a self-check. In a codebase whose most
    repeated failure is two copies of one formula drifting apart, that is a loaded gun; CLAIM's
    parameters and supervise.granted_ttl are both derived from these same two constants now."""
    return int(max(TTL_FLOOR_S, TTL_FACTOR * est_seconds(chars, tok_s) + 120))


def claim_sql(node, relaxed=False):
    """The claim, strict by default. `relaxed=True` raises only the LENGTH cap -- never the class
    range -- so a node that would otherwise idle can take a longer document, but still cannot take
    work its class rules forbid. P0 stays off the pre-emptible nodes under every circumstance."""
    n = NODES[node]
    cap = n["fallback_cap"] if relaxed else n["cap"]
    return CLAIM.format(order=ORDER_SQL[n["order"]]), dict(
        node=node, ttl_floor=TTL_FLOOR_S, ttl_factor=TTL_FACTOR, max_attempts=MAX_ATTEMPTS,
        sec_per_char=ALPHA / max(0.01, n["tok_s"]),
        min_class=n.get("min_class", P0), max_class=n["max_class"], cap=cap)


# --- the corpus side ------------------------------------------------------------------------
def connect_queue(dsn=None):
    """Queue connection, or None. Returns None rather than raising so `route.py --demo` and every
    other pure-logic path stay runnable on a laptop with no postgres and no psycopg installed."""
    import os
    dsn = dsn or os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        return None
    try:
        import psycopg
    except ImportError:
        return None
    return psycopg.connect(dsn)


def text_hash(text):
    """Short content hash. The offset contract (`text[start:end] == span.text`) silently assumes
    every node extracts from byte-identical text; one differing unicode normalisation between node
    images raises the unlocatable-span rate with no error anywhere. This is what makes that
    assumption checkable at claim time instead of discoverable in an audit weeks later."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# fetched_at rides along with published_at because the two are only meaningful
# together: when the crawler cannot find a publication date it stamps the fetch
# date, and the serving date-gate can only tell that apart by comparing them.
# On its own, published_at looks like a proven date even when it is not.
DOC_COLS = ("document_id, url, source_id, language, title, main_text, "
            "published_at, fetched_at")


def fetch_doc(q, doc_id):
    """The document, or None if the corpus no longer has it.

    Returning dict(zip(cols, None)) raised TypeError and killed the worker outright. A queue row
    whose document has been pruned is a poison pill: it takes down whichever worker claims it,
    over and over. It becomes likely the moment enqueue runs continuously against a crawler that
    prunes -- so this is a park, not a crash."""
    with q.cursor() as c:
        c.execute(f"SELECT {DOC_COLS} FROM documents WHERE document_id=%s", (doc_id,))
        r = c.fetchone()
    if r is None:
        return None
    return dict(zip(DOC_COLS.replace(" ", "").split(","), r))


RELEASE = """
UPDATE extract_queue SET
  state = CASE WHEN greatest(0, attempts - %(refund)s) >= %(max_attempts)s
               THEN 'parked' ELSE 'ready' END,
  reason = %(reason)s,
  leased_by=NULL, lease_until=NULL,
  lease_epoch=lease_epoch+1, attempts=greatest(0, attempts - %(refund)s)
WHERE document_id=%(doc)s AND lease_epoch=%(epoch)s AND state='leased'
RETURNING document_id, state;
"""

# THE ATTEMPTS ECONOMY, stated once so it cannot drift again.
#
# CLAIM charges +1. Exactly one question decides whether that charge is refunded:
# *was an extraction attempted on this document?*
#
#   refund   -- no extraction happened: worker down, orphaned, deploy/restart. The document was
#               never tried, so charging it would let three deploys park a perfectly good row.
#   CHARGE   -- an extraction happened and failed: crashed, wedged and stuck-killed, or failed to
#               store. That attempt genuinely consumed a node, which is the only thing `attempts`
#               exists to count.
#
# Refunding BOTH cases makes the net change per failure cycle zero, which sounds merciful and is
# not: park-at-3 becomes unreachable, and a document that deterministically crashes is re-claimed
# from the head of its FIFO class forever, consuming a node with nothing to show. MAX_ATTEMPTS is
# 5 rather than 3 to keep slack for genuinely transient faults -- bounded with slack, never
# unbounded.
MAX_ATTEMPTS = 5


def release(q, doc_id, epoch, why="", charge=True):
    """Hand a document back immediately after a failure we already know about.

    charge=True (the default, and the safe default) keeps the attempt: the extraction was tried.
    Pass charge=False only where no extraction was attempted at all. Fenced on state and epoch,
    so a late release can never disturb whoever holds the lease now."""
    with q.cursor() as c:
        c.execute(RELEASE, {"doc": doc_id, "epoch": epoch, "refund": 0 if charge else 1,
                            "max_attempts": MAX_ATTEMPTS, "reason": (why or "")[:200] or None})
        got = c.fetchone()
    q.commit()
    if got and got[1] == "parked":
        print(f"      {doc_id} PARKED after {MAX_ATTEMPTS} attempts: {why}", flush=True)
    return got is not None


def park(q, doc_id, epoch, why):
    with q.cursor() as c:
        c.execute("UPDATE extract_queue SET state='parked', leased_by=NULL, lease_until=NULL "
                  "WHERE document_id=%s AND lease_epoch=%s", (doc_id, epoch))
    q.commit()


# app/pipeline/source_tiers.py returns STRINGS, not numbers. Getting this wrong is not a crash,
# it is a silently wrong queue: int("official") raises, an except swallows it, every document
# lands at tier 3, P0 and P1 collapse into P2, and the whole priority ladder stops existing while
# the dashboard reports a perfectly healthy queue. So the mapping is explicit and asserted.
TIER_NUM = {"official": 1, "registry": 2, "news": 3}

# source_tiers.py lives in app/pipeline/ while this file lives in engine/l2/comprehend/, so the
# import needs a hint. C_TIERS_PATH overrides; otherwise try the layout as deployed.
_TIER_FN = None
_TIER_WHY = "not looked up yet"


def _load_tier_fn():
    global _TIER_FN, _TIER_WHY
    import os
    import pathlib as _pl
    here = _pl.Path(__file__).resolve().parent
    for c in (os.environ.get("C_TIERS_PATH"),
              str(here.parent.parent / "app" / "pipeline"),
              str(here.parent.parent.parent / "app" / "pipeline"),
              str(here)):
        if not c or not _pl.Path(c, "source_tiers.py").exists():
            continue
        if c not in sys.path:
            sys.path.insert(0, c)
        try:
            import source_tiers
            _TIER_FN, _TIER_WHY = source_tiers.tier, c
            return _TIER_FN
        except Exception as e:
            _TIER_WHY = "%s: %s" % (c, type(e).__name__)
    _TIER_WHY = "source_tiers.py not found on any candidate path"
    return None


def tier_of(url, source_id=""):
    """Source reliability tier as 1 (official) .. 3 (unknown).

    Delegated to source_tiers.tier(); this module does not reimplement the ladder, because two
    tier tables that disagree is worse than one that is merely absent. Unknown falls to 3, the
    conservative direction -- a mis-tiered document loses priority, never gains it.
    """
    if _TIER_FN is None:
        _load_tier_fn()
    if _TIER_FN is None:
        return 3
    try:
        return TIER_NUM.get(_TIER_FN(url or ""), 3)
    except Exception:
        return 3


def tier_available():
    """-> (bool, explanation). Enqueue MUST refuse when this is False: a queue built with every
    document at tier 3 looks entirely normal and is entirely wrong."""
    if _TIER_FN is None:
        _load_tier_fn()
    return _TIER_FN is not None, _TIER_WHY


ENQUEUE = """
INSERT INTO extract_queue (document_id, class, chars, est_out, crawl_ts, text_hash)
VALUES (%(doc)s, %(cls)s, %(chars)s, %(est)s, %(ts)s, %(hash)s)
ON CONFLICT (document_id) DO NOTHING;
"""


# Filtered on REASON, never on size. Filtering on `chars <= LIVE_CAP` did the exact opposite of
# what this function promises: the farm-band rows it exists to rescue (9,275-26,639 chars) FAILED
# the predicate, while ~7,400 gate-rejected rows PASSED it -- so `--promote N` would have
# re-admitted N documents the relevance gate had refused, which is the corpus-composition decision
# this function explicitly must not make.
PROMOTE = """
UPDATE extract_queue q SET state='ready', reason=NULL
WHERE q.state='deferred' AND q.reason = 'no-live-node'
  AND q.document_id IN (SELECT document_id FROM extract_queue
                        WHERE state='deferred' AND reason = 'no-live-node'
                          AND chars <= %(live_cap)s
                        ORDER BY class, crawl_ts LIMIT %(lim)s)
RETURNING document_id;
"""


def promote_deferred(q, limit=0):
    """Give `deferred` a way back to `ready`.

    `deferred` is documented as "visibly not dispatched, and recoverable". It was not recoverable:
    ENQUEUE is ON CONFLICT DO NOTHING and _mark only ever stamps AWAY from ready, so no code path
    anywhere promoted a deferred row. That made it `parked` wearing a friendlier name -- and it
    now holds thousands of rows, growing every enqueue cycle.

    Two different things land in `deferred` and only ONE of them may be promoted here:
      * no LIVE node could take it (a farm-only document) -- promotable the moment a node returns,
        which is what this does, bounded by the live cap.
      * the relevance gate rejected it -- NOT promotable by this function. Re-admitting those is a
        corpus-composition decision, not a queue-maintenance one, and it belongs to whoever owns
        the gate policy.
    Rows are selected by reason='no-live-node' ONLY -- gate-rejected rows are never promoted
    here. Passing limit=0 promotes nothing; the caller must ask for it explicitly."""
    if not limit:
        return 0
    with q.cursor() as c:
        c.execute(PROMOTE, {"live_cap": LIVE_CAP, "lim": int(limit)})
        got = c.fetchall()
    q.commit()
    return len(got)


# --- backfill: never idle beside a full queue -------------------------------------------------
# Measured on the live queue: `ready` 0, `deferred/gate` 51,994, 198 workers all printing
# "nothing eligible; polling with backoff". The queue was 98% full and the fleet was asleep.
#
# promote_deferred() refuses to touch gate rows on purpose -- its docstring calls re-admitting
# them "a corpus-composition decision, not a queue-maintenance one". This is that decision, made
# once and made explicit, and it rests on what the gate actually asks:
#
#     "is this document worth 13 minutes of Layer A?"  is shorthand for
#     "...worth 13 minutes INSTEAD OF something better?"
#
# While better work exists the answer is no and the gate stands. When `ready` is empty there is
# no better work, the opportunity cost the threshold encodes is zero, and the honest answer
# flips. So the gate is not weakened -- PASS_THRESHOLD is untouched and enqueue still refuses
# these rows -- it is given the one exception its own premise implies.
#
# It cannot displace real work, by construction:
#   * it only runs when `ready` is below BACKFILL_FLOOR, and only tops up TO that floor;
#   * `class` is left exactly as enqueue set it, and CLAIM orders by class ASC -- so a fresh P0
#     or a worklist lane-1 document enqueued one second later is still claimed first;
#   * it promotes nothing a live node could not take (same class/cap predicate as dispatch).
#
# Two passes, because the ordering must be GLOBAL and scoring is not free:
#   1. score a bounded batch of never-examined `gate` rows, and record each score IN the reason
#      (`gate:NN`). Nothing is promoted in this pass and no row is ever scored twice.
#   2. promote the best-scoring examined rows across every batch ever scanned. Highest presignal
#      score means most competitor/defence vocabulary, so the KSSL-relevant rejects drain first
#      and the bulk-government noise last -- which is the whole reason to score rather than to
#      take these FIFO.
BACKFILL_FLOOR = int(os.environ.get("C_BACKFILL_FLOOR", "400"))
BACKFILL_SCAN = int(os.environ.get("C_BACKFILL_SCAN", "4000"))

# What the RUNNING fleet can claim. LIVE_CAP already exists; the class window is the same idea
# and must come from the same place, or backfill promotes rows into `ready` that no worker can
# claim -- which is the "lie the queue tells about itself" dispatchable() exists to prevent.
_LIVE_CFG = [NODES[n] for n in LIVE_NODES if n in NODES] or list(NODES.values())
LIVE_MIN_CLASS = min(n.get("min_class", P0) for n in _LIVE_CFG)
LIVE_MAX_CLASS = max(n["max_class"] for n in _LIVE_CFG)

_HOLD_RX = re.compile(r"^gate:(\d+)$")


def hold_reason(score):
    """A scanned-but-not-yet-promoted gate row, with its score kept in `reason`.

    extract_queue has no score column, and adding one is a migration on a live table for a
    number three lines read. The reason text is already the row's audit trail ('gate',
    'no-live-node'), so the score rides there -- clamped, because reason feeds a regex."""
    return "gate:%d" % max(0, min(999, int(score)))


def held_score(reason):
    """-> int for a scanned row, None for anything else. 'gate' (never examined) is NOT 0:
    unscored and scored-zero must stay distinguishable or pass 1 rescans its own output."""
    m = _HOLD_RX.match(reason or "")
    return int(m.group(1)) if m else None


BACKFILL_SCAN_SQL = """
SELECT q.document_id, d.title, d.main_text, d.published_at
  FROM extract_queue q JOIN documents d USING (document_id)
 WHERE q.state='deferred' AND q.reason='gate'
   AND q.class BETWEEN %(min_class)s AND %(max_class)s AND q.chars <= %(cap)s
 ORDER BY q.crawl_ts DESC
 LIMIT %(lim)s;
"""

BACKFILL_HOLD_SQL = """
UPDATE extract_queue SET reason=%s
 WHERE document_id=%s AND state='deferred' AND reason='gate';
"""

# reason='backfill' on the promoted row, never NULL: a document that was extracted only because
# the farm would otherwise have idled must stay tellable from one the gate admitted on merit.
# `done` keeps the reason, so this survives into the audit.
BACKFILL_PROMOTE_SQL = """
UPDATE extract_queue SET state='ready', reason='backfill'
 WHERE state='deferred'
   AND document_id IN (SELECT document_id FROM extract_queue
                        WHERE state='deferred' AND reason ~ '^gate:[0-9]+$'
                          AND class BETWEEN %(min_class)s AND %(max_class)s
                          AND chars <= %(cap)s
                        ORDER BY (substring(reason from 6))::int DESC, crawl_ts DESC
                        LIMIT %(lim)s)
RETURNING document_id;
"""


BACKFILL_BAND_SQL = """
SELECT (substring(reason from 6))::int AS score FROM extract_queue
 WHERE state='deferred' AND reason ~ '^gate:[0-9]+$'
   AND class BETWEEN %(min_class)s AND %(max_class)s AND chars <= %(cap)s
 ORDER BY (substring(reason from 6))::int DESC, crawl_ts DESC
 LIMIT %(lim)s;
"""


def backfill(q, floor=None, scan=None, dry=False):
    """Top `ready` back up to `floor` from what the gate refused. -> a dict of counts.

    Called by the feeder every cycle. A no-op -- one COUNT -- whenever the queue is healthy,
    which is the common case and must stay cheap."""
    floor = BACKFILL_FLOOR if floor is None else int(floor)
    scan = BACKFILL_SCAN if scan is None else int(scan)
    band = {"min_class": LIVE_MIN_CLASS, "max_class": LIVE_MAX_CLASS, "cap": LIVE_CAP}
    out = {"ready": 0, "other": 0, "want": 0, "nolive": 0, "scanned": 0, "promoted": 0,
           "hi": None, "lo": None, "why": ""}
    # `ready` IS NOT A SCALAR, and treating it as one is how the first version of this failed
    # in production: promote_deferred filled the whole 400-row shortfall with class-0 rows,
    # which only the oversize pool (min_class=0) can claim, and the 182 farm workers went on
    # printing "nothing eligible" beside a queue that now looked full. A floor is only
    # meaningful against the population that can actually claim it, so it is counted with the
    # SAME predicate the gate backfill promotes into -- band in, band out.
    band_where = ("class BETWEEN %(min_class)s AND %(max_class)s AND chars <= %(cap)s")
    with q.cursor() as c:
        c.execute("SELECT count(*) FROM extract_queue WHERE state='ready' AND " + band_where,
                  band)
        out["ready"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM extract_queue WHERE state='ready' AND NOT (" +
                  band_where + ")", band)
        out["other"] = c.fetchone()[0]
    out["want"] = want = max(0, floor - out["ready"])
    # 1. Rows deferred only because nothing was RUNNING. Free and correct under any gate policy,
    #    so they go first -- but against THEIR OWN shortfall. They land outside the live band
    #    (class 0, the oversize lane), so they neither compete with the gate backfill for the
    #    budget nor count towards satisfying it.
    want_other = max(0, floor - out["other"])
    if want_other and not dry:
        out["nolive"] = promote_deferred(q, want_other)
    if not want:
        out["why"] = "in-band ready %d >= floor %d" % (out["ready"], floor)
        return out

    # 2. Score a batch of never-examined gate rows. Refusing to run without the dataset is the
    #    same rule enqueue applies: a blind scorer returns numbers, and ordering 52k documents
    #    by a number nobody computed is worse than not reordering them at all.
    have_ps, ps_why = presignal_available()
    if not have_ps:
        out["why"] = "presignal unavailable, refusing to rank blind: %s" % ps_why
        return out
    with q.cursor() as c:
        c.execute(BACKFILL_SCAN_SQL, dict(band, lim=scan))
        rows = c.fetchall()
    holds = []
    for did, title, text, pa in rows:
        s = presignal_of(text or "", title=title or "", published_at=pa)
        holds.append((hold_reason(s or 0), did))
    out["scanned"] = len(holds)
    if holds and not dry:
        with q.cursor() as c:
            c.executemany(BACKFILL_HOLD_SQL, holds)
        q.commit()

    # 3. Promote the best examined rows -- across every batch ever scanned, not just this one.
    #    The band promoted is reported because it is the number that matters operationally: while
    #    it is high the fleet is eating real defence copy the gate was too strict about; once it
    #    reaches 0 the backlog holds nothing relevant left and the only thing still being bought
    #    is "not idle". That is a decision for a human, so it is printed rather than acted on.
    if not dry:
        with q.cursor() as c:
            c.execute(BACKFILL_BAND_SQL, dict(band, lim=want))
            got = c.fetchall()
            if got:
                out["hi"], out["lo"] = got[0][0], got[-1][0]
            c.execute(BACKFILL_PROMOTE_SQL, dict(band, lim=want))
            out["promoted"] = len(c.fetchall())
        q.commit()
    out["why"] = "in-band ready %d (+%d out of band) -> want %d" % (
        out["ready"], out["other"], out["want"])
    return out


def enqueue(q, since, now_iso, limit=20000, cohort_min=30):
    """Corpus -> queue, gated and classified.

    Order of operations matters and is not arbitrary:

      1. PRESIGNAL GATE first. Below PASS_THRESHOLD the document never enters the queue at all.
         Measured on 1,250 real pages, 66% fail this gate and would otherwise have cost 184
         CPU-hours to refuse downstream, after paying the full ~13 minutes of Layer A each.
      2. Then rank the survivors by percentile WITHIN THEIR LANGUAGE COHORT, never by raw score.
      3. Trust tier is attached but has no vote -- it is for the card gate, later.

    Nothing is silently dropped. Gate failures are `deferred`, over-cap documents are `parked`,
    and both are counted: a document that is simply never inserted is indistinguishable from one
    that was processed, which is exactly how a backlog hides behind a green dashboard.
    """
    import collections
    import datetime
    ok, why = tier_available()
    if not ok:
        raise RuntimeError(
            "refusing to enqueue without source_tiers: the trust tier would be wrong on every "
            "row. Set C_TIERS_PATH to the directory holding source_tiers.py. (%s)" % why)
    have_ps, ps_why = presignal_available()
    if not have_ps:
        # Explicit, once, loudly -- and recorded per row as presignal=NULL rather than as a
        # score we invented. Without the scorer every fresh document ties at "no information"
        # (0.5) and lands in P1: a flat queue, which is honest, rather than a confident order
        # built on a number nobody computed.
        print("WARNING: presignal unavailable (%s).\n"
              "         Every fresh document will tie at 0.5 and land in P1. The 66%% relevance\n"
              "         gate is NOT running, so the queue will carry work worth ~184 CPU-hours\n"
              "         per 1,250 documents that Layer A would only refuse at the far end."
              % ps_why)

    with q.cursor() as c:
        # Exclude rows already in the queue: without this, already-enqueued newest documents consume
        # the LIMIT on every run, so on a burst day the oldest documents in the window fall off the
        # end and -- once `since` advances past them -- are never selected again (silent permanent
        # loss). Excluding them also stops re-scoring/re-loading main_text for rows we already have.
        # fetched_at is part of DOC_COLS now; selecting it again here would put the
        # same name twice into `cols` below and quietly misalign the zip.
        c.execute("SELECT %s, text_len, language FROM documents "
                  "WHERE fetched_at >= %%s AND text_len > 0 "
                  "  AND NOT EXISTS (SELECT 1 FROM extract_queue eq "
                  "                  WHERE eq.document_id = documents.document_id) "
                  "ORDER BY fetched_at DESC LIMIT %%s"
                  % DOC_COLS, (since, limit))
        rows = c.fetchall()
    cols = DOC_COLS.replace(" ", "").split(",") + ["text_len", "language"]
    docs = [dict(zip(cols, r)) for r in rows]

    # Score everything first: a percentile needs the cohort, so this cannot stream.
    cohorts = collections.defaultdict(list)
    for d in docs:
        # published_at is now fetched (DOC_COLS) and passed: presignal applies a -15 penalty to
        # undated docs (~73% by body regex), and the metadata date is the fix. The export path always
        # passed it; this direct-DB path did not, so the same doc scored differently by which path
        # enqueued it -- and a whole cohort enqueued here was systematically depressed.
        d["_ps"] = presignal_of(d.get("main_text") or "", d.get("title") or "",
                                d.get("published_at")) if have_ps else None
        if d["_ps"] is not None:
            cohorts[(d.get("language") or "??")].append(d["_ps"])

    now = datetime.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    n = collections.Counter()
    for d in docs:
        if d["_ps"] is not None and d["_ps"] < PASS_THRESHOLD:
            n["deferred"] += 1
            _mark(q, d["document_id"], "deferred", d, why="gate")
            continue
        lang = d.get("language") or "??"
        pool = cohorts.get(lang, [])
        # A cohort too small to rank within is "no information", not a confident ordering. Their
        # scheduler makes the same call: a tie lands at 0.5 rather than at the top.
        pct = percentile_within(d["_ps"], pool) if (d["_ps"] is not None and len(pool) >= cohort_min) else 0.5
        try:
            age = (now - datetime.datetime.fromisoformat(
                d["fetched_at"].replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            age = 9e9                      # unparseable timestamp -> backlog, never "fresh"
        cls, nodes, state = dispatchable(d["text_len"], pct, age)
        why = None if state == "ready" else (
            "no-live-node" if state == "deferred" else "over-park-threshold")
        _mark(q, d["document_id"], state, d, cls if cls is not None else P3, why=why)
        n[state] += 1
    q.commit()
    return dict(n)


def _mark(q, doc_id, state, d, cls=P3, why=None):
    with q.cursor() as c:
        c.execute(ENQUEUE, dict(doc=doc_id, cls=cls, chars=d["text_len"],
                                est=est_out(d["text_len"]), ts=d["fetched_at"],
                                hash=text_hash(d.get("main_text") or "")))
        # ONLY a row still sitting in a pre-dispatch state may be re-stamped. Unguarded, a
        # re-enqueue whose window overlaps already-processed work sets state='deferred' on a
        # DONE document: the spans stay in the store, but the queue then reports it as never
        # processed and permanently ineligible. It can also stamp over a row a worker is 20
        # minutes into. Re-enqueue is meant to be routine and idempotent, so it must never be
        # able to walk a document backwards out of a terminal or in-flight state.
        if state != "ready":
            c.execute("UPDATE extract_queue SET state=%s, reason=%s WHERE document_id=%s "
                      "AND state IN ('ready','deferred')", (state, why, doc_id))


# --- driver-free enqueue --------------------------------------------------------------------
# The DC host has no postgres driver and no pip, and installing one to run a batch job would mean
# changing someone else's system for our convenience. psql is already there via `docker exec`, so
# the enqueue runs as export -> score -> load: psql writes JSONL, pure Python scores and
# classifies it, psql loads the result back. No driver, nothing installed, and each of the three
# steps is separately inspectable -- which is worth more than the round-trip it costs.

# 'h' is the hash of the WHOLE text, computed server-side, and 'x' is a prefix for SCORING only.
# They were once the same field: the export carried a 4,000-char prefix and this module hashed
# that, while run_node.py verifies against the hash of the full column -- so the two could never
# agree for a longer document and every one of them parked at first claim as "text changed since
# enqueue", with no text having changed. Measured on the live queue: 325 of 1,710 rows (19%)
# carried a prefix hash, and every single row over 4,000 chars matched the prefix and not the
# full text. Keep these two fields separate and never derive one from the other.
# 20,000 for the prefix because that is exactly what presignal.py itself reads; scoring a 4,000
# char prefix gave the same document a different score on this path than on the psycopg path.
#
# convert_to(..., 'UTF8'), NOT ::bytea. A text->bytea cast is an I/O conversion: the string is fed
# to bytea_in, which PARSES bytea literal syntax. Any backslash that is not a valid escape raises
# "invalid input syntax for type bytea" and kills the whole export -- verified against the live
# database on 'C:\Users\defence' and on 'a\134b' -- while a string starting with \x is silently
# DECODED as hex, giving different bytes, a different hash, and every such document parked at
# first claim as "text changed". That is the identical bug this line was added to fix, re-armed
# for every crawled page containing a Windows path, a code snippet, LaTeX or embedded JSON.
EXPORT_SQL = """
SELECT json_build_object('id',document_id,'u',coalesce(url,''),'s',coalesce(source_id,''),
  'l',coalesce(language,'??'),'t',coalesce(title,''),'p',coalesce(published_at,''),
  'f',fetched_at,'n',text_len,'x',substr(coalesce(main_text,''),1,20000),
  'h',substr(encode(sha256(convert_to(coalesce(main_text,''),'UTF8')),'hex'),1,16))::text
FROM documents WHERE fetched_at >= '%s' AND text_len > 0
ORDER BY fetched_at DESC LIMIT %d;
"""


def _export_hash(d):
    """The full-text hash from the export. Refuses to fall back to hashing the prefix.

    A fallback here is what the bug WAS: silently hashing whatever text happened to be to hand.
    An export made by an older EXPORT_SQL has no 'h', and the only safe response is to stop --
    a queue built from it parks every long document, which looks like corpus drift and is not."""
    h = d.get("h")
    if not h:
        raise SystemExit(
            "export row %s has no 'h' (full-text hash). This JSONL was produced by an older "
            "EXPORT_SQL that shipped only a 4,000-char prefix; hashing that parks every document "
            "longer than 4,000 chars at first claim. Re-export with the current EXPORT_SQL."
            % d.get("id", "?"))
    return h


def plan_from_jsonl(path, now_iso, cohort_min=30):
    """Export JSONL -> rows ready for COPY, plus a summary. Pure: no database, no network, so it
    can be run and checked on a laptop against a sample before it ever touches the queue."""
    import collections
    import datetime
    have_ps, ps_why = presignal_available()
    docs, cohorts = [], collections.defaultdict(list)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            d["_ps"] = presignal_of(d.get("x") or "", d.get("t") or "",
                                    d.get("p") or None) if have_ps else None
            if d["_ps"] is not None:
                cohorts[d.get("l") or "??"].append(d["_ps"])
            docs.append(d)

    now = datetime.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    rows, n = [], collections.Counter()
    for d in docs:
        ps = d["_ps"]
        if ps is not None and ps < PASS_THRESHOLD:
            n["deferred"] += 1
            rows.append((d["id"], P3, d["n"], est_out(d["n"]), d["f"],
                         _export_hash(d), "deferred", "gate"))
            continue
        pool = cohorts.get(d.get("l") or "??", [])
        pct = percentile_within(ps, pool) if (ps is not None and len(pool) >= cohort_min) else 0.5
        try:
            age = (now - datetime.datetime.fromisoformat(
                (d["f"] or "").replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            age = 9e9
        cls, nodes, state = dispatchable(d["n"], pct, age)
        why = None if state == "ready" else (
            "no-live-node" if state == "deferred" else "over-park-threshold")
        rows.append((d["id"], cls if cls is not None else P3, d["n"], est_out(d["n"]),
                     d["f"], _export_hash(d), state, why))
        n[state] += 1
        if state == "ready":
            n["class_P%d" % cls] += 1
    n["scored"] = sum(1 for d in docs if d["_ps"] is not None)
    n["presignal"] = "on" if have_ps else "OFF: " + ps_why
    return rows, dict(n)


def write_copy_tsv(rows, out):
    """COPY-format TSV. Tabs and newlines cannot appear in any column here -- ids are hashes,
    states are literals, timestamps are ISO -- so no escaping is needed and none is faked."""
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            # \N is COPY's NULL. str(None) would load the literal text "None" into `reason`,
            # which then reads as a real reason and would make PROMOTE's filter wrong.
            fh.write("\t".join("\\N" if x is None else str(x) for x in r) + "\n")
    return out


# --- pacing: never run a node flat out ------------------------------------------------------
# The queue cannot overload a node by itself -- workers PULL, and hold one document at a time, so
# a busy node simply does not ask. What the queue does not prevent is a node asking again the
# instant it finishes, forever. Sustained 100% CPU is its own hazard, and not mainly a thermal one:
#
#   * Shared VPS hosting treats permanent full-core load as abuse. Throttling or suspension is a
#     real outcome, and it removes the node for far longer than pacing ever cost.
#   * Sustained all-core load pushes a CPU into thermal throttling, where you pay the same watts
#     for fewer tokens. A paced node is often barely slower in tokens/day than an unpaced one.
#   * A node at 100% has no headroom to answer a health check, an SSH login, or -- on VPS-B --
#     a customer request.
#
# THE REQUIREMENT WAS ONE DOCUMENT IN FLIGHT PER MACHINE -- and that is already structural, not a
# thing this table has to buy. drain() is a single-threaded loop: it claims one document, extracts
# it, stores it, and only then asks for another. A node is never sent a second document while the
# first is outstanding, at any duty value, because there is no code path that can send one.
#
# The duty cycle sat on top of that guarantee and bought nothing further. It was my over-reading
# of "don't overload the VPS" into a sleep nobody asked for, and it was expensive: vps-b at 0.50
# rested as long as it worked, 6.2 hours of one night, worth about 46 documents -- more than the
# whole fleet actually delivered in that time. Measured across all three nodes: 8.3 hours idle.
#
# 1.00 means "ask for the next document as soon as this one is stored". MIN_GAP_S still applies,
# so a pathologically fast document cannot turn the claim loop into a storm.
DUTY = {
    "vps-a": 1.00,
    "dc":    1.00,
    "vps-b": 1.00,
    "farm":  1.00,
}
MIN_GAP_S = 5        # floor between documents even for a fast one -- stops claim-storms
MAX_BACKOFF_S = 300  # ceiling when the queue has nothing for this node


def cooldown_s(node, elapsed_s):
    """Gap before asking for the next document.

    At duty 1.00 this is just MIN_GAP_S -- long enough that a zero-second document cannot spin the
    claim loop, short enough to be noise against an 8-25 minute extraction. Below 1.00 it holds
    the declared ratio, which is retained for a node that genuinely shares a box with something
    latency-sensitive; it is not the mechanism that keeps one document in flight."""
    d = DUTY.get(node, 1.0)
    if d >= 1.0:
        return MIN_GAP_S
    return max(MIN_GAP_S, elapsed_s * (1.0 / d - 1.0))


def backoff_s(empty_rounds):
    """Exponential, capped. A worker eligible for nothing must not spin on the queue: at one claim
    per second an idle farm worker is 86,400 pointless transactions a day."""
    return min(MAX_BACKOFF_S, MIN_GAP_S * (2 ** min(empty_rounds, 8)))


# A BUSY SHARED GATEWAY IS NOT AN EMPTY QUEUE, and backing off from one the way you back off from
# the other is what kept the Pune farm at 6/12 instead of 12/12. The two failures have opposite
# shapes:
#
#   an empty queue stays empty     -> re-asking costs a transaction and gains nothing: climb to 300s
#   a busy gateway recovers in     -> re-asking costs one HTTP call and gains a worker: stay low
#   seconds
#
# 144 workers re-probing every 30s is 4.8 probes/second, which is nothing next to the inference
# load they are waiting on. Meanwhile every second of over-long backoff is a whole GPU slot idle,
# so the ceiling here is deliberately an order of magnitude below MAX_BACKOFF_S.
SVC_MAX_BACKOFF_S = 30


def svc_backoff_s(fail_rounds):
    """Backoff for a MODEL SERVER that is not answering, counted separately from queue emptiness.

    Observed on the live fleet: a gateway returning 502s for ten seconds put workers on the shared
    `empty` ladder, which only resets on a successful claim -- so a ten-second blip bought a
    five-minute sleep, and the farm oscillated between 6/12 and idle instead of settling at 12/12.
    """
    return min(SVC_MAX_BACKOFF_S, MIN_GAP_S * (2 ** min(fail_rounds, 8)))


# Where each node's model actually lives. A node is not "up" because its box is up.
ENDPOINTS = {
    "vps-a": "http://127.0.0.1:11434/api/tags",
    "vps-b": "http://127.0.0.1:11434/api/tags",
    "dc":    "http://172.24.0.2:11434/api/tags",
    # The farm health URL is env-driven: the gateway moved from ollama.i3softlab.com to
    # farm-llm.i3softlab.com, and a hardcoded old URL reports the fastest node dead (530) forever.
    "farm":  os.environ.get("C_FARM_HEALTH_URL") or "https://farm-llm.i3softlab.com/v1/models",
}
# The model name the health probe must see in the node's /models response. The farm serves
# "text-model"; CPU nodes serve "qwen2.5:7b". Env-driven so one image can check either.
MODEL_MUST_MATCH = os.environ.get("C_MODEL_MUST_MATCH") or "qwen2.5:7b"
_SVC_CACHE = {}                   # node -> (monotonic_deadline, ok, detail)
SVC_TTL_OK, SVC_TTL_BAD = 60.0, 15.0


SVC_PROBE_TIMEOUT = float(os.environ.get("C_SVC_PROBE_TIMEOUT", "10"))


def service_ok(node, url=None, timeout=None, now=None, fetch=None):
    """Is this node's MODEL SERVER answering, and does it hold the model we require?

    Checked before claiming, never after. Claim first and the document is leased to a node that
    cannot process it: the worker fails on its first call, the lease has to expire, and the
    document sits frozen for the whole TTL before anyone else can have it. On a node whose server
    is simply down that repeats forever -- claim, fail, expire, claim -- and the queue quietly
    grinds while every box looks healthy.

    Checking the MODEL and not just the port matters as much. An Ollama server with no model
    pulled answers /api/tags instantly and 200s, then spends 150 seconds loading on the first real
    request -- or fails outright. And the farm serves two models under near-identical names, only
    one of which matches the CPU nodes' digest.

    Results are cached briefly: a probe per claim would be one HTTP round trip per document, and a
    failed node is re-probed sooner than a healthy one so recovery is noticed quickly.
    """
    import time as _t
    timeout = SVC_PROBE_TIMEOUT if timeout is None else timeout
    now = now if now is not None else _t.monotonic()
    hit = _SVC_CACHE.get(node)
    if hit and now < hit[0]:
        return hit[1], hit[2]
    # OLLAMA_URL wins over the table. The worker already knows where its own model server is --
    # and it is the only thing that does: from inside a container the DC's server is
    # `kssl-extract-ollama`, from the host it is 172.24.0.2, and a static table cannot be right
    # for both. A probe pointed at the wrong address reports a healthy node as dead and stops it
    # claiming anything, which is the most expensive way to be wrong here.
    base = os.environ.get("OLLAMA_URL")
    if url is None and base and node != "farm":
        url = base.rstrip("/") + "/api/tags"
    url = url or ENDPOINTS.get(node)
    if not url:
        return True, "no endpoint configured"      # unknown node: do not block on our own gap
    try:
        body = fetch(url, timeout) if fetch else _http_get(url, timeout)
        ok = MODEL_MUST_MATCH in body
        detail = "serving %s" % MODEL_MUST_MATCH if ok else "up but %s not present" % MODEL_MUST_MATCH
    except Exception as e:
        ok, detail = False, "%s: %s" % (type(e).__name__, str(e)[:60])
    _SVC_CACHE[node] = (now + (SVC_TTL_OK if ok else SVC_TTL_BAD), ok, detail)
    return ok, detail


def _http_get(url, timeout):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "kssl-route/1"})
    # The farm rejects unauthenticated probes with a 530, which reads exactly like "the farm is
    # down" -- so a missing key would take the fastest node in the fleet out of service and blame
    # the farm for it. C_FARM_KEY is checked too, because OLLAMA_API_KEY is unset on the DC
    # profile by design (activate_dc.sh unsets it to force native mode) and the probe must not
    # inherit that decision.
    key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("C_FARM_KEY")
    if key and url.startswith("https"):
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(20000).decode("utf-8", "replace")


def _cgroup_pressure():
    """This container's own CPU stall share, or None.

    /sys/fs/cgroup/cpu.pressure reports the percentage of time runnable tasks were stalled waiting
    for CPU, for THIS cgroup only. `some avg10=12.34` means 12% of the last ten seconds.
    """
    try:
        with open("/sys/fs/cgroup/cpu.pressure") as fh:
            for line in fh:
                if line.startswith("some "):
                    for kv in line.split():
                        if kv.startswith("avg10="):
                            return float(kv.split("=", 1)[1])
    except Exception:
        pass
    return None


def _own_cores():
    """How many cores THIS process may actually use -- the cgroup's answer, not the host's."""
    try:
        return len(os.sched_getaffinity(0))
    except Exception:
        return os.cpu_count() or 8


def load_ok(node, loadavg=None, cores=None, pressure=None, max_pressure=60.0):
    """Is there room for another document on THIS node?

    Prefer the cgroup's own CPU pressure over the host load average, because a pinned container is
    not the machine it sits in. This worker owns cores 35-39 of 40; the crawler on cores 0-19 can
    push the host load average past any sensible threshold while our five cores sit completely
    idle, and a host-wide signal would stop us claiming anything at all. That is not hypothetical
    -- it is exactly what happened on the first run, and it is the same mistake as llama.cpp
    reading the host's CPU count and spawning 40 threads inside a 7-core cpuset: ask the cgroup,
    never the machine.

    Falls back to loadavg only when no cgroup pressure is available (bare metal, a Mac, cgroup v1),
    and even then scales against the cores we may actually use rather than the ones that exist.
    """
    if pressure is None and loadavg is None:
        pressure = _cgroup_pressure()
    if pressure is not None:
        # Some stall is normal and healthy under load; sustained heavy stall is not.
        return pressure < max_pressure
    if loadavg is None:
        try:
            loadavg = os.getloadavg()[0]
        except (OSError, AttributeError):
            return True                      # no signal is not the same as a bad signal
    return loadavg < (cores or _own_cores()) * 0.75


# --- capacity -------------------------------------------------------------------------------
def capacity(p50_chars=2128):
    """Docs/day per node at the measured median document. Reported at the MEDIAN, not the mean:
    the mean (3,835) is 1.8x the median because a handful of huge documents drag it, so planning
    on the mean understates real throughput badly."""
    return {n: 86400 * DUTY.get(n, 1.0) / est_seconds(p50_chars, c["tok_s"])
            for n, c in NODES.items()}


def _demo():
    # The cost model must reproduce the run it was calibrated on.
    assert abs(est_out(2370) - 11418) < 200, "alpha no longer reproduces the 600-doc run"

    # Fresh beats backlog regardless of how strong the signal is -- the whole point of the policy.
    assert klass(0.9, 1) == P0 and klass(0.1, 1) == P2
    assert klass(0.9, 999) == P3, "a strong stale document must still lose to any fresh one"
    assert klass(0.1, 1) < klass(0.9, 999), "a weak fresh document outranks a strong backlog one"
    # Language-cohort normalisation, which is what stops the router ranking the SCORER instead of
    # the sources. An all-tied cohort is "no information" (0.5), never the top of the queue.
    assert percentile_within(50, [50, 50, 50]) == 0.5, "an all-tied cohort must not be promoted"
    assert percentile_within(90, [10, 20, 30]) > percentile_within(15, [10, 20, 30])
    # A Hebrew doc at the top of a low-scoring cohort must beat a Polish doc mid-cohort, even
    # though its raw score is lower. This is the non-English starvation guard.
    he, pl = [8, 10, 12], [55, 60, 65]
    assert klass(percentile_within(12, he), 1) < klass(percentile_within(58, pl), 1), \
        "within-language ranking must not be overridden by the raw score"

    # The 71-day document must be unroutable, on every node, always.
    c, nodes = route(19662845, 0.9, 0)
    assert nodes == [] and c is None, "the 19.6MB document escaped the cap"
    assert est_seconds(19662845, 15.385) / 86400 > 60, "sanity: that doc really is ~71 days"

    # Pre-emptible nodes must never be handed the latency promise.
    for n in ("vps-b", "farm"):
        assert not eligible(n, P0, 500), f"{n} is pre-emptible and must not take P0"
    assert eligible("vps-a", P0, 500) and eligible("dc", P0, 500)

    # Caps bound worst-case occupancy to the minutes each node can actually sustain. The farm is
    # held to a much tighter bound than the always-on nodes precisely because it disappears.
    for n, cfg in NODES.items():
        mins = est_seconds(cfg["cap"], cfg["tok_s"]) / 60
        assert mins <= cfg["minutes"] + 1, f"{n} exceeds its own {cfg['minutes']}min budget"

    # No length band may exist that every node refuses but nothing parks -- that band would sit in
    # `ready` forever and no dashboard would ever show why.
    assert PARK_CHARS == max(c["cap"] for c in NODES.values())
    # and the derived caps must still honour each node's declared minute budget
    for n, cfg in NODES.items():
        assert abs(est_seconds(cfg["cap"], cfg["tok_s"])/60 - cfg["minutes"]) < 1.5
    # EVERY class, not just one: the first version of this check tested P2 alone and missed that
    # a p99 Tier-1 document was eligible nowhere -- orphaned in the highest-priority lane.
    # There are THREE honest outcomes, not two: dispatchable now, not dispatchable until a dead
    # node returns, or impossible for any node. The earlier version asserted `nodes` outright,
    # which forced the farm to be counted as capacity -- and that is exactly how 15,149 chars'
    # worth of document width came to sit in `ready` with no running node able to claim it.
    for ch in (465, 2128, 6256, 9229, 23141, PARK_CHARS, PARK_CHARS - 1):
        for pct, age in ((0.9, 1), (0.5, 1), (0.1, 1), (0.9, 99)):
            cls, nodes, st = dispatchable(ch, pct, age)
            assert st in ("ready", "deferred", "parked"), st
            assert (st == "ready") == bool(nodes), \
                f"{ch} chars pct {pct} age {age}h -> state {st} but nodes {nodes}"
            assert not (st == "parked" and ch <= PARK_CHARS), \
                f"{ch} chars parked despite being within PARK_CHARS {PARK_CHARS}"
            if st == "deferred":
                # deferred must mean "a real node could, but it is not running" -- never
                # "nothing could ever", which is what `parked` is for.
                assert any(eligible(n, cls, ch) for n in NODES), \
                    f"{ch} chars deferred but NO node could ever take it -- should be parked"
    assert route(23141, 0.9, 1)[0] == P1, "oversized P0 must demote so the farm can take it"
    assert route(2128, 0.9, 1)[0] == P0, "a normal strong document must stay P0"

    # A document at a node's cap is eligible; one character more is not. Derived from the config
    # rather than restated, so the boundary cannot drift away from the cap it is testing.
    for n, cfg in NODES.items():
        c = cfg["cap"]
        cl = cfg.get("min_class", P0)
        assert eligible(n, cl, c) and not eligible(n, cl, c + 1), f"{n} cap boundary is wrong"

    # Lease TTL must exceed the work it covers, or live workers get re-queued under themselves.
    for n, cfg in NODES.items():
        assert lease_ttl(cfg["cap"], cfg["tok_s"]) > est_seconds(cfg["cap"], cfg["tok_s"])

    # Ordering is per-node and must be real SQL, not a silent default.
    for n, cfg in NODES.items():
        sql, args = claim_sql(n)
        assert ORDER_SQL[cfg["order"]] in sql and "SKIP LOCKED" in sql
        assert args["cap"] == cfg["cap"]

    # The tier mapping is string -> int, and must stay pointing the right way.
    assert TIER_NUM == {"official": 1, "registry": 2, "news": 3}
    assert TIER_NUM["official"] < TIER_NUM["news"], "official must outrank news"
    # ...but trust must have NO vote in dispatch. Same document, three tiers, one class.
    assert len({route(2128, 0.9, 1)[0] for _ in TIER_NUM}) == 1, "trust must not change routing"
    # With no tier module the fallback must be the CONSERVATIVE 3, never a guess at 1.
    # Blocking the LOADER as well as the cached function is the whole point: the first version of
    # this test only nulled the cache, so on any machine where source_tiers actually imports it
    # reloaded and returned 1. It passed on the laptop precisely BECAUSE the module was missing
    # there, and failed the moment it ran somewhere the module exists -- a test that only holds
    # when its subject is absent is not a test.
    _save_fn, _save_loader = globals()["_TIER_FN"], globals()["_load_tier_fn"]
    try:
        globals()["_TIER_FN"] = None
        globals()["_load_tier_fn"] = lambda: None
        assert tier_of("https://mod.gov.in/x") == 3, "absent tier module must fall back to 3"
    finally:
        globals()["_TIER_FN"], globals()["_load_tier_fn"] = _save_fn, _save_loader
    # ...and where the module IS present, an official domain must actually come back as 1.
    if tier_available()[0]:
        assert tier_of("https://mod.gov.in/x") == 1, "a .gov domain must tier as official"

    # The presignal call signature must match the scorer's, INCLUDING published_at. This is
    # checked with a stub rather than the real module because on a machine with no ds.json the
    # scorer reports itself blind, the caller skips it entirely, and a broken signature sails
    # through untested -- which is exactly how it reached the DC.
    _save = globals()["_PRESIGNAL_FN"]
    try:
        seen = {}

        def _stub(blob, published_at=None):
            seen["pa"] = published_at
            return {"score": 77}
        globals()["_PRESIGNAL_FN"] = _stub
        assert presignal_of("body", "title", "2026-08-26") == 77
        assert seen["pa"] == "2026-08-26", "published_at was not passed to the scorer"
        # ...and a scorer that predates the parameter must still work.
        globals()["_PRESIGNAL_FN"] = lambda blob: {"score": 55}
        assert presignal_of("body", "title", "2026-08-26") == 55
    finally:
        globals()["_PRESIGNAL_FN"] = _save

    # An idle node with work available is waste. Every node must be able to reach backlog, so
    # that spare capacity drains P3 instead of stalling beside it.
    for n in NODES:
        assert NODES[n]["max_class"] >= P3, f"{n} cannot reach backlog and will idle beside it"
    # ...but fresh-first must survive that: the claim orders by class, so backlog is only ever
    # reached when nothing fresher is eligible.
    assert "ORDER BY class ASC" in CLAIM

    # The relaxed claim raises the length cap and NOTHING else.
    strict, sa = claim_sql("vps-b")
    loose, la = claim_sql("vps-b", relaxed=True)
    # Relaxed is strictly larger, and never larger than the multiple -- but it may be SMALLER
    # than the multiple, because the absolute minute ceiling can bind first. Asserting exact
    # equality with cap * multiple encoded the rule before the ceiling existed and broke the
    # moment the ceiling started doing its job.
    assert la["cap"] > sa["cap"], "relaxed must actually relax"
    assert la["cap"] <= int(sa["cap"] * FALLBACK_MULTIPLE), "relaxed must not exceed the multiple"
    assert la["min_class"] == sa["min_class"] == P1, "relaxing must not let VPS-B take P0"
    assert la["max_class"] == sa["max_class"]
    # The lease is now sized per DOCUMENT inside the CLAIM, not per node cap, so the params carry
    # the rate rather than a fixed TTL. Same intent, checked against the expression SQL evaluates:
    # greatest(floor, 2*chars*sec_per_char + 120).
    def _ttl(prm, chars):
        return max(prm["ttl_floor"], 2 * chars * prm["sec_per_char"] + 120)
    assert la["sec_per_char"] == sa["sec_per_char"], "relaxing changes the cap, never the rate"
    assert _ttl(sa, 2000) > _ttl(sa, 500), "a longer document needs a longer lease"
    # ...and the defect this replaced: a small document must NOT inherit the CAP's lease. Stated
    # against the principle, not against a specific cap -- the first version hardcoded the dc's
    # 9,274 and broke the moment that cap was corrected from a real measurement, which is exactly
    # the drift these checks exist to catch.
    for _n in NODES:
        _p = claim_sql(_n)[1]
        _small, _full = _ttl(_p, 200), _ttl(_p, NODES[_n]["cap"])
        assert _small <= _full, f"{_n}: a small document must never lease longer than a cap-sized one"
        if _full > TTL_FLOOR_S:          # only meaningful where the floor is not already binding
            assert _small < _full, \
                f"{_n}: a 200-char document is holding the cap's lease ({_small:.0f}s)"
    # No node may be stalled for hours by its own fallback, and the pre-emptible ones are held
    # tighter still because their work is the likeliest to be lost.
    for n, c in NODES.items():
        mins = est_seconds(c["fallback_cap"], c["tok_s"]) / 60
        lim = FALLBACK_MAX_MIN["preemptible" if c.get("min_class", P0) > P0 else "always_on"]
        assert mins <= lim + 1, f"{n} fallback is {mins:.0f} min, ceiling {lim}"
        assert c["fallback_cap"] > c["cap"], f"{n} fallback must actually relax something"

    # These assertions used to demand that pacing COST throughput -- "if it does not, it is not
    # doing anything". That was the wrong requirement, and asserting it kept the wrong behaviour
    # alive: the requirement is ONE DOCUMENT IN FLIGHT PER MACHINE, which drain()'s single-threaded
    # claim loop provides for free. A sleep on top bought nothing and cost 8.3 hours in one night.
    for n in ("vps-a", "dc", "vps-b", "farm"):
        assert cooldown_s(n, 600) == MIN_GAP_S, \
            f"{n} must ask for the next document as soon as the current one is stored"
    # ...and the gap must stay a claim-storm floor, never a throttle: negligible against a real
    # document, but non-zero so a zero-second document cannot spin the loop.
    assert cooldown_s("vps-b", 0) == MIN_GAP_S and MIN_GAP_S < 30, \
        "the inter-document gap must be a floor, not a rest"
    # The mechanism that actually bounds a node is the single in-flight document. If drain() ever
    # gains concurrency, THAT is what must be reviewed -- not this number.
    import inspect as _i
    assert "ThreadPoolExecutor" not in _i.getsource(cooldown_s), \
        "cooldown is not the concurrency control; drain()'s one-at-a-time loop is"
    assert cooldown_s("vps-a", 1) == MIN_GAP_S, "a fast document must still leave a gap"
    assert backoff_s(0) == MIN_GAP_S and backoff_s(99) == MAX_BACKOFF_S
    assert backoff_s(3) > backoff_s(1), "backoff must actually climb"
    assert load_ok("vps-a", loadavg=2.0, cores=8) and not load_ok("vps-a", loadavg=7.0, cores=8)
    # Cgroup pressure wins over the host load average when both could be consulted.
    assert load_ok("vps-a", pressure=5.0) and not load_ok("vps-a", pressure=95.0)
    # A pinned container must not be blocked by a busy neighbour: host load 28 on 40 cores while
    # our own five are idle has to read as HEALTHY, which the host-wide version got wrong.
    assert load_ok("dc", pressure=3.0), "a quiet cgroup must claim even on a busy host"

    # A node whose model server is down must not be handed work, and a server that is UP but
    # holding the wrong model must not either -- that is the case a port check would wave through.
    # Built FROM MODEL_MUST_MATCH, not from a literal: the required model is configurable
    # (C_MODEL_MUST_MATCH is "text-model" on the farm deployments), and a hardcoded "qwen2.5:7b"
    # made `route.py --demo` fail on every box that sets it -- a self-check that only passes
    # where the thing it checks is unconfigured.
    _right = '{"models":["%s"]}' % MODEL_MUST_MATCH
    # NOT derived from MODEL_MUST_MATCH by prefixing it: the check is a substring test, so
    # "definitely-not-text-model" CONTAINS "text-model" and passes. The wrong name has to share
    # nothing with the right one.
    _wrong = '{"models":["zzz-no-such-model"]}'
    assert MODEL_MUST_MATCH not in _wrong, "the negative fixture must not contain the model"
    _SVC_CACHE.clear()
    ok, why = service_ok("t1", url="http://x", fetch=lambda u, t: _right)
    assert ok, why
    _SVC_CACHE.clear()
    ok, why = service_ok("t2", url="http://x", fetch=lambda u, t: _wrong)
    assert not ok and "not present" in why, "wrong model must fail the check: %s" % why
    _SVC_CACHE.clear()

    def _boom(u, t):
        raise OSError("connection refused")
    ok, why = service_ok("t3", url="http://x", fetch=_boom)
    assert not ok and "OSError" in why
    # A dead node is re-probed sooner than a healthy one, so recovery is noticed quickly.
    assert SVC_TTL_BAD < SVC_TTL_OK
    # A busy gateway must be re-asked in seconds, not minutes. This is the whole fix for the farm
    # sitting at 6/12: the ceiling for "server not answering" is an order of magnitude below the
    # ceiling for "queue is empty", because the two recover on completely different timescales.
    assert svc_backoff_s(0) == MIN_GAP_S, "the first retry must be immediate-ish"
    assert svc_backoff_s(99) == SVC_MAX_BACKOFF_S
    assert SVC_MAX_BACKOFF_S < MAX_BACKOFF_S / 5, \
        "a recoverable gateway is being backed off from like an empty queue"
    # ...and it must actually climb, or 144 workers hammer a struggling gateway at 5s intervals.
    assert svc_backoff_s(3) > svc_backoff_s(1), "service backoff must still climb"
    # The probe has to outlast a gateway that is busy SERVING. At 4s it reported the hardest-
    # working node in the fleet as dead, which is the most expensive possible false negative.
    assert SVC_PROBE_TIMEOUT >= 8, "probe times out before a loaded gateway can answer"
    _SVC_CACHE.clear()

    cap = capacity()
    tot = cap["vps-a"] + cap["dc"] + cap["vps-b"] * 0.4
    # Band moved 150-240 -> 100-200 when the dc's tok_s was corrected from the configured 8.765 to
    # a measured 1.5, taking it from ~62 docs/day to ~11. The old band was not wrong about the
    # arithmetic; it was ratifying a number nobody had measured. Any future move should likewise
    # come from a measurement, and should trip this assertion first.
    assert 100 < tot < 200, \
        "capacity moved to %.0f/day: re-derive the caps before trusting this" % tot
    print("ok  capacity %.0f docs/day vs 9,188 arriving -> %.0fx deficit, %.1f%% coverage"
          % (tot, 9188 / tot, 100 * tot / 9188))

    # --- backfill ------------------------------------------------------------------------
    # The score has to survive a round trip through `reason`, because that column IS the
    # storage. A silent mismatch here would not fail -- it would order 52,000 documents
    # arbitrarily while looking exactly like a ranking.
    for v in (0, 7, 45, 65, 999):
        assert held_score(hold_reason(v)) == v, v
    assert hold_reason(-3) == "gate:0" and hold_reason(10**6) == "gate:999", "clamp the regex input"
    # 'gate' means NEVER EXAMINED and must not read as zero, or pass 1 rescans its own output
    # forever and pass 2 never sees a candidate.
    assert held_score("gate") is None and held_score(None) is None
    assert held_score("backfill") is None and held_score("no-live-node") is None
    assert held_score("gate:") is None and held_score("gate:12x") is None
    # SQL sorts on `substring(reason from 6)::int`; Python sorts on _HOLD_RX. Two expressions,
    # one meaning -- so check they agree on the same strings rather than trusting the offset.
    for v in (0, 5, 45, 123):
        assert hold_reason(v)[5:] == str(v), "substring(from 6) no longer lines up with 'gate:'"
    # A backfill that can never promote anything is worse than none: it looks like insurance.
    # The gate defers at the class enqueue assigned, so the live band must actually contain it.
    assert LIVE_MIN_CLASS <= P3 <= LIVE_MAX_CLASS, \
        "no live node can claim the class the gate defers at -- backfill would be a no-op"
    assert LIVE_CAP > 0, "live cap of 0 promotes nothing, ever"

    class _FakeCur:
        """Just enough cursor to prove the guard. Counts what SQL would have run."""
        def __init__(self, ready, other, log):
            self.ready, self.other, self.log = ready, other, log
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def execute(self, sql, args=None):
            self.log.append(sql.strip().split()[0].upper())
            if "count(*)" in sql:
                # the second COUNT is the negated band -- "NOT (" is the only difference
                self._r = [(self.other if "NOT (" in sql else self.ready,)]
            else:
                self._r = []
        def executemany(self, sql, seq):
            self.log.append("MANY")
        def fetchone(self):
            return self._r[0] if self._r else None
        def fetchall(self):
            return self._r

    class _FakeQ:
        def __init__(self, ready, other=0):
            self.ready, self.other, self.log = ready, other, []
        def cursor(self):
            return _FakeCur(self.ready, self.other, self.log)
        def commit(self):
            pass

    # BOTH bands above the floor: do nothing but count. This runs every feeder cycle forever
    # and must never touch a row while every pool has work. Both bands, not one -- 16 of the 198
    # workers claim only class 0, and a healthy in-band queue says nothing about them.
    q = _FakeQ(500, other=500)
    r = backfill(q, floor=400)
    assert r["want"] == 0 and r["promoted"] == 0 and r["nolive"] == 0, r
    assert set(q.log) == {"SELECT"}, "backfill wrote to the queue while every pool had work"
    # ...but a full in-band queue must NOT stop the oversize pool being fed. Those 16 workers
    # idle silently: nothing about `ready` being 500 tells you class 0 is empty.
    q = _FakeQ(500, other=0)
    r = backfill(q, floor=400)
    assert r["want"] == 0, r
    assert "UPDATE" in q.log, "in-band work must not starve the class-0 pool"
    # Below the floor it asks for exactly the shortfall, never for the whole backlog.
    q = _FakeQ(120)
    r = backfill(q, floor=400, dry=True)
    assert r["want"] == 280, r
    # THE PRODUCTION FAILURE, stated as an invariant. `ready` is counted per BAND: 378 rows
    # sitting in `ready` that this band cannot claim (class 0, the oversize lane) must leave the
    # shortfall untouched. The first version counted them and let 182 farm workers idle beside a
    # queue that looked full.
    q = _FakeQ(0, other=378)
    r = backfill(q, floor=400, dry=True)
    assert r["want"] == 400, "out-of-band ready rows must not satisfy this band's floor: %r" % r
    assert r["other"] == 378, r
    print("ok  backfill: %d-row floor, score survives the reason round trip, "
          "no-op above the floor" % BACKFILL_FLOOR)


STATUS = """
SELECT state, class, count(*), min(crawl_ts), max(crawl_ts)
FROM extract_queue GROUP BY state, class ORDER BY state, class;
"""


def status(q):
    """Report health the way the design demands: never as queue depth.

    Depth is useless here and actively misleading -- the central queue is permanently full and
    node-local queues are permanently empty, so both look 'fine' forever. What matters is whether
    the promised class is being met and whether the deficit is the one we chose.
    """
    with q.cursor() as c:
        c.execute(STATUS)
        rows = c.fetchall()
    by_state = {}
    for st, cls, n, lo, hi in rows:
        by_state.setdefault(st, {})[cls] = (n, lo, hi)
    print("%-9s %-14s %10s   %s" % ("state", "class", "count", "oldest crawl_ts"))
    print("-" * 62)
    for st in sorted(by_state):
        for cls in sorted(by_state[st]):
            n, lo, _ = by_state[st][cls]
            print("%-9s %-14s %10s   %s" % (st, CLASS_NAME.get(cls, cls), f"{n:,}", lo or ""))
    ready = by_state.get("ready", {})
    p0 = ready.get(P0, (0, None, None))
    cap = capacity()
    tot = cap["vps-a"] + cap["dc"] + cap["vps-b"] * 0.4
    print("\n  P0 waiting        %s   <- the only number with a promise attached" % f"{p0[0]:,}")
    print("  oldest unstarted  %s" % (p0[1] or "none"))
    print("  CPU capacity      %.0f docs/day" % tot)
    print("  deferred+parked   %s   <- must be non-zero and OWNED, not accidental"
          % f"{sum(v[0] for k in ('deferred', 'parked') for v in by_state.get(k, {}).values()):,}")
    if p0[0] > cap["vps-a"]:
        print("\n  WARNING: P0 alone exceeds VPS-A's daily capacity. The guaranteed lane is")
        print("           oversubscribed, which means sampling must start INSIDE P0.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="self-check, no database needed")
    ap.add_argument("--plan", metavar="CHARS,TIER,AGE_H",
                    help="explain where one document would go, and why")
    ap.add_argument("--init", action="store_true", help="create the queue table")
    ap.add_argument("--enqueue", action="store_true", help="corpus -> queue")
    ap.add_argument("--promote", type=int, default=0, metavar="N",
                    help="promote up to N node-unavailable `deferred` rows back to ready")
    ap.add_argument("--backfill", action="store_true",
                    help="top `ready` back up from what the gate refused, best-scoring first")
    ap.add_argument("--backfill-floor", type=int, default=None, metavar="N",
                    help="keep at least N rows in `ready` (default C_BACKFILL_FLOOR=%d)"
                         % BACKFILL_FLOOR)
    ap.add_argument("--since", default="2026-08-01", help="enqueue documents fetched on/after")
    ap.add_argument("--now", default=None, help="ISO timestamp to age against (default: now)")
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--claim", metavar="NODE", help="lease one document for NODE and print it")
    ap.add_argument("--reap", action="store_true", help="expired leases -> ready (or parked)")
    ap.add_argument("--status", action="store_true", help="the deficit, honestly")
    ap.add_argument("--plan-file", metavar="JSONL",
                    help="driver-free enqueue: score an export and write COPY-ready rows")
    ap.add_argument("--out", default="queue_rows.tsv")
    a = ap.parse_args()

    if a.plan:
        ch, ti, ag = (int(float(x)) for x in a.plan.split(","))
        cls, nodes = route(ch, ti, ag)
        if cls is None:
            print("%s chars -> PARKED (> %s); %.1f days on the fastest node we own"
                  % (f"{ch:,}", f"{PARK_CHARS:,}", est_seconds(ch, 15.385) / 86400))
            return
        print("%s chars, tier %d, %dh old -> %s, %s est tokens"
              % (f"{ch:,}", ti, ag, CLASS_NAME[cls], f"{est_out(ch):,}"))
        for n in nodes:
            print("    %-6s %6.1f min" % (n, est_seconds(ch, NODES[n]["tok_s"]) / 60))
        if not nodes:
            print("    (no node eligible -- over every cap for its class)")
        return

    if a.plan_file:
        import datetime
        now = a.now or datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows, summary = plan_from_jsonl(a.plan_file, now)
        write_copy_tsv(rows, a.out)
        print("planned %d rows -> %s" % (len(rows), a.out))
        for k in sorted(summary):
            print("  %-12s %s" % (k, summary[k]))
        return

    # Every action that needs the QUEUE has to be listed here, or the flag silently runs
    # the self-check instead and reports success having touched nothing. --promote had
    # this defect from the start and --backfill inherited it: `route.py --backfill` ran
    # _demo() against the live feeder for a full cycle.
    if not (a.init or a.enqueue or a.claim or a.reap or a.status
            or a.promote or a.backfill):
        _demo()
        return

    q = connect_queue()
    if q is None:
        sys.exit("no queue connection: set KSSL_CORPUS_DSN and install psycopg")
    if a.init:
        with q.cursor() as c:
            c.execute(DDL)
        q.commit()
        print("queue table ready")
    if a.enqueue:
        import datetime
        now = a.now or datetime.datetime.now(datetime.timezone.utc).isoformat()
        n = enqueue(q, a.since, now, a.limit)
        print("enqueued  ready %s  deferred %s  parked %s"
              % (f"{n.get('ready', 0):,}", f"{n.get('deferred', 0):,}",
                 f"{n.get('parked', 0):,}"))
    if a.promote:
        print("promoted %d deferred row(s) back to ready" % promote_deferred(q, a.promote))
    if a.backfill:
        b = backfill(q, floor=a.backfill_floor)
        band = ("" if b["hi"] is None
                else "  promoted scores %d..%d" % (b["hi"], b["lo"]))
        print("backfill: in-band ready %d, want %d -> %d from the gate (%d newly scored)%s; "
              "%d out-of-band promoted from no-live-node [%s]"
              % (b["ready"], b["want"], b["promoted"], b["scanned"], band,
                 b["nolive"], b["why"]))
    if a.reap:
        with q.cursor() as c:
            c.execute(REAP, {"max_attempts": MAX_ATTEMPTS})
            rows = c.fetchall()
        q.commit()
        back = sum(1 for _, at in rows if at < 3)
        print("reaped %d expired lease(s): %d requeued, %d parked" % (len(rows), back, len(rows) - back))
    if a.claim:
        sql, args = claim_sql(a.claim)
        with q.cursor() as c:
            c.execute(sql, args)
            row = c.fetchone()
        q.commit()
        print(row if row else "nothing eligible for %s" % a.claim)
    if a.status:
        status(q)


if __name__ == "__main__":
    main()
