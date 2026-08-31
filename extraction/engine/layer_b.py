"""Layer B -- canonical entities. Turn spellings into things, reversibly.

THE PROBLEM, STATED EXACTLY
---------------------------
Today no table says "Bharat Forge Limited and Bharat Forge are the same company". Statements store
plain text. The reason that was DEFERRED rather than botched is sound and still holds: every span
keeps its verbatim text and its exact offsets, so every field of this layer stays derivable later.
Deferring cost nothing. Building it now costs nothing either -- which is why it can start.

WHAT THIS IS NOT
----------------
It is not a rename of the span table. A mention keeps its text and its offsets for ever. This layer
only ever ADDS a cross-reference: "these mentions point at the same thing, decided on this date, for
these reasons". If the decision was wrong you delete the slip and every mention is untouched.

That is the whole design, and it is why `merge_event` is append-only and carries its signals: a
wrong merge is not a hypothetical. Bharat Forge, Bharat Electronics and Bharat Dynamics are three
different companies sharing a word, and any system that cannot undo one merge without losing a
week's adjudication will eventually lose a week's adjudication.

THREE BLOCKERS, BECAUSE ONE IS NOT ENOUGH
-----------------------------------------
  1. folded surface        catches "Paramount Group" / "PARAMOUNT GROUP (Pty) Ltd"
  2. character 3-grams     catches typos and word order; blind to a change of script
  3. embedding neighbours  the ONLY one that can pair a Chinese name with an English one

A design that blocks on string similarity alone is a Latin-script design wearing a multilingual
label. That is measured below, not assumed.
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

# The console on Windows is cp1252, and this module prints ENTITY NAMES -- which are
# exactly the strings a multilingual corpus fills with characters cp1252 cannot encode.
# Without this the resolution completes, computes every group correctly, and then dies on
# the print that reports them, taking the WRITE with it. It surfaced only once the corpus
# passed 23 languages; the first six documents happened to be Latin-1-safe.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = Path(__file__).parent
D = HERE / "data"

# --------------------------------------------------------------------------- normalisation
_LEGAL = re.compile(
    r"\b(?:limited|ltd|llc|inc|incorporated|corp|corporation|company|co|plc|gmbh|ag|sa|s\.a\.|"
    r"nv|n\.v\.|bv|b\.v\.|spa|s\.p\.a\.|as|a\.s\.|oy|ab|aps|pty|pvt|private|public|group|holdings?|"
    # The trailing guard is (?!\w) and NOT \b, because several of these alternatives end in a full
    # stop. A word boundary after "s.a." requires a word character adjacent to the dot, so at the
    # end of a string it simply never matches and the suffix is never stripped. This is the same
    # trap that made "250mm" written with the CJK unit character unparseable in the value layer.
    r"industries|systems|technologies|international|joint stock|jsc|ojsc|pjsc)(?!\w)", re.I)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def fold(s):
    """Case, accent and legal-suffix folding. Unicode-aware, so it does not quietly favour Latin.

    The decompose-strip-RECOMPOSE dance is not decoration. NFKD splits Latin accents into a base
    plus a combining mark, which is what lets them be stripped -- but it ALSO splits a Hangul
    syllable into its Jamo, and Jamo are not combining marks, so they survive the strip and the
    word comes out as its constituent letters. Recomposing with NFC puts Hangul back together and
    leaves the now-accentless Latin exactly as it is. Without the final NFC every Korean name folds
    to something no other spelling of it will ever match.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = unicodedata.normalize("NFC", s)
    s = s.casefold()
    stripped = _WS.sub(" ", _PUNCT.sub(" ", _LEGAL.sub(" ", s))).strip()
    # A name that is ONLY a legal suffix -- "AS", "Group", "Corporation" -- strips to nothing, and
    # every empty string matches every other one. Left alone this merges "AS", "A.S.", "company",
    # "corporation" and "group" into a single ten-member entity, which is what it did on the first
    # run. When stripping removes everything, keep the unstripped form instead.
    if not stripped:
        return _WS.sub(" ", _PUNCT.sub(" ", s)).strip()
    return stripped


def grams(s, n=3):
    s = " " + fold(s) + " "
    return {s[i:i + n] for i in range(max(1, len(s) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- identifiers
# A registration number, a stock number or a ticker is a HARD gate in both directions: a match
# forces a link, a clash forbids one no matter how similar the names look.
_ID_PAT = [
    re.compile(r"\b\d{4}/\d{6}/\d{2}\b"),                 # ZA company registration
    re.compile(r"\bU\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b"),  # IN CIN
    re.compile(r"\b\d{4}-\d{2}-\d{6}\b"),                 # NATO stock number shape
]


def identifiers(text):
    out = set()
    for p in _ID_PAT:
        out.update(p.findall(text or ""))
    return out


# --------------------------------------------------------------------------- scripts
_SCRIPTS = [
    ("latin", re.compile(r"[A-Za-zÀ-ÿ]")),
    ("cyrillic", re.compile(r"[Ѐ-ӿ]")),
    ("greek", re.compile(r"[Ͱ-Ͽ]")),
    ("arabic", re.compile(r"[؀-ۿݐ-ݿ]")),
    ("hebrew", re.compile(r"[֐-׿]")),
    ("devanagari", re.compile(r"[ऀ-ॿ]")),
    ("han", re.compile(r"[㐀-䶿一-鿿]")),
    ("kana", re.compile(r"[぀-ヿ]")),
    ("hangul", re.compile(r"[가-힯ᄀ-ᇿ]")),
]


def scripts_of(s):
    return {name for name, rx in _SCRIPTS if rx.search(s or "")}


def comparable_scripts(a, b):
    """Can a string-similarity score mean anything for this pair?

    Only if the two share a writing system. Two names in different scripts score zero on every
    character measure no matter how certainly they name the same company, so a zero must be read
    as 'not applicable' rather than as 'different'.
    """
    sa, sb = scripts_of(a), scripts_of(b)
    if not sa or not sb:
        return True                      # digits or symbols only: nothing to rule out
    return bool(sa & sb)


# --------------------------------------------------------------------------- union-find
class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.p[rb] = ra
        return True


SCHEMA = """
create table if not exists entity(
  entity_id   text primary key,
  canonical   text not null,
  type        text not null,
  n_mentions  integer not null,
  n_aliases   integer not null);

create table if not exists entity_alias(
  entity_id text not null, surface text not null, lang text, n integer,
  primary key (entity_id, surface, lang));

-- a mention keeps its own identity for ever; this table only points at it
create table if not exists mention_resolution(
  document_id text not null, span_key text not null,
  entity_id text not null, method text not null, confidence real,
  primary key (document_id, span_key));

-- APPEND ONLY. Deleting a row here undoes exactly one decision and nothing else.
create table if not exists merge_event(
  merge_id integer primary key autoincrement,
  winner text not null, loser text not null,
  score real not null, signals text not null,
  reason text not null, decided_by text not null, decided_at text not null);

-- a human's verdict is stored as a CONSTRAINT and replayed into every later run, so a redeploy
-- cannot discard a week of adjudication
create table if not exists pair_constraint(
  a text not null, b text not null,
  kind text not null check (kind in ('must_link','must_not_link')),
  note text, primary key (a, b));
-- The review band, persisted. It used to live only inside one process, which meant the ~3,900
-- pairs a human is supposed to adjudicate could not be shown to one -- and `pair_constraint`
-- could therefore only ever be empty.
create table if not exists review_pair(
  a text not null, b text not null,
  a_text text not null, b_text text not null, type text not null,
  a_lang text, b_lang text,
  score real not null, signals text not null, reason text not null,
  cross_script integer not null default 0,
  primary key (a, b));
create index if not exists ix_alias on entity_alias(surface);
create index if not exists ix_review_score on review_pair(score desc);
"""


def _ckey(a, b):
    """Constraints are unordered: adjudicating (a,b) must also settle (b,a)."""
    return (a, b) if a <= b else (b, a)


def load_constraints(db):
    """Human verdicts recorded against an earlier run of this layer."""
    p = Path(db) if Path(db).is_absolute() else D / Path(db).name
    if not p.exists():
        return {}
    con = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    try:
        rows = con.execute("select a, b, kind from pair_constraint").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {_ckey(a, b): kind for a, b, kind in rows}


def load(sset=None):
    """Load one embedded population. `sset` names the file prefix -- "bench" is the 182-document
    set every published number was computed from, and it stays the default so a second corpus
    cannot silently redefine a result that has already been reported."""
    sset = sset or os.environ.get("C_SET", "bench")
    vec = np.load(D / ("%s_vec.npy" % sset))
    keys = json.loads(io.open(D / ("%s_keys.json" % sset), encoding="utf-8").read())
    rows = [json.loads(l) for l in io.open(D / ("%s_pop.jsonl" % sset), encoding="utf-8")
            if l.strip()]
    order = [tuple(k.split("\t", 1)) for k in keys]
    idx = {k: i for i, k in enumerate(order)}
    info = [{"text": "", "type": t, "langs": collections.Counter(), "docs": set(), "n": 0}
            for _, t in order]
    for r in rows:
        k = (r["text"].lower(), r["type"])
        i = idx[k]
        info[i]["text"] = r["text"] if len(r["text"]) > len(info[i]["text"]) else info[i]["text"]
        info[i]["langs"][r["lang"]] += 1
        info[i]["docs"].add(r["doc"])
        info[i]["n"] += 1
    return vec, order, info


def resolve(vec, order, info, tau_auto=0.93, tau_review=0.55, knn=12, verbose=True,
            constraints=None):
    N = len(order)
    t0 = time.time()

    # ---- blocker 1: identical folded surface -------------------------------
    by_fold = collections.defaultdict(list)
    for i, (surf, typ) in enumerate(order):
        f = fold(info[i]["text"])
        if len(f) < 3:          # too little left to be evidence of anything
            continue
        by_fold[(f, typ)].append(i)
    pairs = set()
    for v in by_fold.values():
        for a in range(len(v)):
            for b in range(a + 1, len(v)):
                pairs.add((v[a], v[b]))
    n1 = len(pairs)

    # ---- blocker 2: shared character 3-grams -------------------------------
    g = [grams(info[i]["text"]) for i in range(N)]
    inv = collections.defaultdict(list)
    for i in range(N):
        for tri in list(g[i])[:24]:
            inv[tri].append(i)
    for tri, v in inv.items():
        if len(v) > 60:            # a gram this common carries no information
            continue
        for a in range(len(v)):
            for b in range(a + 1, len(v)):
                if order[v[a]][1] == order[v[b]][1]:
                    pairs.add((min(v[a], v[b]), max(v[a], v[b])))
    n2 = len(pairs) - n1

    # ---- blocker 3: embedding neighbours -- the only cross-script one -------
    sims = vec @ vec.T
    np.fill_diagonal(sims, -1)
    # np.argpartition raises when kth is not strictly inside the row, so a population smaller than
    # knn crashed the whole layer rather than simply having fewer neighbours to offer. That is
    # reachable in practice: a single-language slice, or any small store, is under 12 surfaces.
    k = max(1, min(knn, N - 1))
    # Partition on sims directly and take the TOP slice, rather than negating first. `-sims`
    # allocated a second full N x N array: 1,004 MB at the measured N=15,845, on top of the 1,004 MB
    # sims already holds. Identical neighbours -- the loop below consumes nn[i] as a set and neither
    # form promises an order -- verified equal for N in {2, 13, 50, 200, 500} including k == N-1.
    nn = np.argpartition(sims, N - k, axis=1)[:, N - k:] if N > 1 else np.zeros((N, 0), dtype=int)
    for i in range(N):
        for j in nn[i]:
            if order[i][1] == order[j][1]:
                pairs.add((min(i, j), max(i, j)))
    n3 = len(pairs) - n1 - n2

    if verbose:
        print("blocking produced %d candidate pairs  (surface %d, 3-gram %d, embedding %d)  %.1fs"
              % (len(pairs), n1, n2, n3, time.time() - t0))

    # ---- scoring -----------------------------------------------------------
    auto, review, ledger = [], [], []
    # Hoisted out of the pair loop. Each of these is a pure function of ONE surface's text, which
    # resolve() never mutates, but they were being recomputed per PAIR -- and there are far more
    # pairs than surfaces (232,578 vs 15,845 measured). Cost of the recompute, measured on the real
    # pair set: fold 3.97s, comparable_scripts 3.06s (it was called TWICE per pair, four scripts_of
    # calls), identifiers 1.70s = 8.73s of a 33s loop. Precomputing all three costs ~0.4s.
    _ids = [identifiers(m["text"]) for m in info]
    _fld = [fold(m["text"]) for m in info]
    _scr = [scripts_of(m["text"]) for m in info]
    for (i, j) in pairs:
        ti, tj = info[i]["text"], info[j]["text"]
        # inline of comparable_scripts(ti, tj), computed ONCE for the two places that ask
        comparable = (not _scr[i] or not _scr[j]) or bool(_scr[i] & _scr[j])
        s_surface = jaccard(g[i], g[j])
        s_embed = float(sims[i, j])
        shared_docs = len(info[i]["docs"] & info[j]["docs"])
        s_cooc = min(1.0, shared_docs / 3.0)
        ids_i, ids_j = _ids[i], _ids[j]

        if ids_i and ids_j:
            if ids_i & ids_j:
                score, why = 1.0, "identifier match"
            else:
                continue                       # a clash forbids the link outright
        else:
            exact = 1.0 if _fld[i] == _fld[j] else 0.0
            # Surface similarity between two DIFFERENT SCRIPTS is zero by construction. That is
            # absence of evidence, not evidence of difference -- and weighting it at 0.55 anyway
            # caps a cross-script pair at 0.30 + 0.15 = 0.45, below any sane auto-merge threshold.
            # The third blocker exists precisely to pair a Chinese name with an English one, and
            # the scorer was making that structurally impossible to act on.
            # So the weights are renormalised over the signals that actually APPLY to the pair.
            w = {"surface": 0.55, "embed": 0.30, "cooc": 0.15}
            if not comparable:
                why = "embedding+co-occurrence (cross-script: surface does not apply)"
                del w["surface"]
                s_surface = 0.0
            else:
                why = "surface+embedding+co-occurrence"
            tot = sum(w.values())
            parts = {"surface": s_surface, "embed": max(0.0, s_embed), "cooc": s_cooc}
            score = sum(w[k] * parts[k] for k in w) / tot
            score = max(score, 0.94 if exact else 0.0)

            # MEASURED, and it changed this design: across 8,457 cross-script candidate pairs the
            # top scorers were six DIFFERENT Russian media outlets at embedding similarity 1.00 --
            # because they share a gloss, not an identity. The gloss embedding answers "same kind
            # of thing", never "same thing", and co-occurrence does not rescue it either: six
            # outlets cited in one article co-occur without being one outlet.
            #
            # So a cross-script pair is never auto-merged, whatever it scores. It is capped into
            # the review band and a human decides. This is a refusal, not a threshold that happens
            # to hold -- a threshold can be tuned past by accident.
            if not comparable:
                score = min(score, tau_auto - 0.01)
                why += " [capped: cross-script identity needs a human]"

        rec = (i, j, round(score, 4),
               {"surface": round(s_surface, 3), "embed": round(s_embed, 3),
                "cooc": round(s_cooc, 3), "shared_docs": shared_docs}, why)
        # A human verdict is not a hint, it is a decision, and it OVERRIDES the score in both
        # directions. Without this the constraint table is write-only: a week of adjudication
        # would be re-derived away by the next run, which is exactly the failure the append-only
        # merge ledger exists to prevent on the other side.
        verdict = (constraints or {}).get(_ckey(order[i][0], order[j][0]))
        if verdict == "must_link":
            auto.append((i, j, 1.0, rec[3], "human verdict: must_link"))
            continue
        if verdict == "must_not_link":
            continue
        if score >= tau_auto:
            auto.append(rec)
        elif score >= tau_review:
            review.append(rec)

    # ---- build entities ----------------------------------------------------
    dsu = DSU(N)
    for i, j, sc, sig, why in sorted(auto, key=lambda r: -r[2]):
        if dsu.union(i, j):
            ledger.append((i, j, sc, sig, why))
    return auto, review, ledger, dsu


def main(write=False, sset=None, db_name=None):
    vec, order, info = load(sset)
    N = len(order)
    print("Layer B over %d distinct (surface, type) mentions\n" % N)
    cons = load_constraints(db_name or "layer_b.db")
    if cons:
        print("replaying %d human verdict(s) recorded against an earlier run" % len(cons))
    auto, review, ledger, dsu = resolve(vec, order, info, constraints=cons)

    groups = collections.defaultdict(list)
    for i in range(N):
        groups[dsu.find(i)].append(i)
    sizes = collections.Counter(len(v) for v in groups.values())
    merged = sum(1 for v in groups.values() if len(v) > 1)
    print("\nauto-merge pairs %d | review queue %d | merges applied %d" %
          (len(auto), len(review), len(ledger)))
    print("entities: %d  (from %d mentions -- %.1f%% collapsed)"
          % (len(groups), N, 100.0 * (1 - len(groups) / N)))
    print("groups with more than one spelling: %d" % merged)
    print("size distribution:", dict(sorted(sizes.items())[:8]))

    # ---- did it cross scripts? the whole reason blocker 3 exists ------------
    cross = 0
    for v in groups.values():
        if len(v) < 2:
            continue
        ls = {info[i]["langs"].most_common(1)[0][0] for i in v}
        if len(ls) > 1:
            cross += 1
    print("groups joining mentions from more than one language: %d" % cross)

    print("\nlargest groups:")
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:8]:
        names = sorted({info[i]["text"] for i in v})[:6]
        print("  %-14s %2d  %s" % (order[k][1][:14], len(v), " | ".join(n[:26] for n in names)))

    if write:
        db = D / (db_name or "layer_b.db")
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute("delete from entity"); con.execute("delete from entity_alias")
        con.execute("delete from mention_resolution"); con.execute("delete from merge_event")
        # NOT pair_constraint: those are human decisions and a rebuild must never discard them.
        con.execute("delete from review_pair")
        for k, v in groups.items():
            eid = "E" + hashlib.sha1(
                (order[k][1] + "\x00" + "|".join(sorted(order[i][0] for i in v)))
                .encode()).hexdigest()[:12]
            best = max(v, key=lambda i: (info[i]["n"], len(info[i]["text"])))
            con.execute("insert into entity values (?,?,?,?,?)",
                        (eid, info[best]["text"], order[k][1],
                         sum(info[i]["n"] for i in v), len(v)))
            for i in v:
                for lg, n in info[i]["langs"].items():
                    con.execute("insert or replace into entity_alias values (?,?,?,?)",
                                (eid, info[i]["text"], lg, n))
        for i, j, sc, sig, why in review:
            a, b = order[i][0], order[j][0]
            con.execute("insert or replace into review_pair values (?,?,?,?,?,?,?,?,?,?,?)",
                        (a, b, info[i]["text"], info[j]["text"], order[i][1],
                         info[i]["langs"].most_common(1)[0][0],
                         info[j]["langs"].most_common(1)[0][0],
                         sc, json.dumps(sig), why, int("capped" in why)))
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for i, j, sc, sig, why in ledger:
            con.execute("insert into merge_event(winner,loser,score,signals,reason,decided_by,"
                        "decided_at) values (?,?,?,?,?,?,?)",
                        (info[i]["text"], info[j]["text"], sc, json.dumps(sig), why,
                         "layer_b@" + version(), now))
        con.commit()
        print("\nwrote %s -- %d entities, %d aliases, %d merge events, %d pairs queued for review"
              % (db.name, con.execute("select count(*) from entity").fetchone()[0],
                 con.execute("select count(*) from entity_alias").fetchone()[0],
                 con.execute("select count(*) from merge_event").fetchone()[0],
                 con.execute("select count(*) from review_pair").fetchone()[0]))
    return groups, order, info, review


def version():
    return hashlib.sha1(io.open(__file__, "rb").read()).hexdigest()[:8]


def _demo():
    # folding must not be a Latin-only operation
    assert fold("Bharat Forge Limited") == fold("BHARAT FORGE Ltd.") == "bharat forge"
    assert fold("Paramount Group (Pty) Ltd") == "paramount"
    assert fold("Ростех") == "ростех", "Cyrillic must survive folding"
    assert fold("한화시스템") == "한화시스템", "Hangul must survive folding"
    assert fold("Safran S.A.") == "safran"

    # THE case this layer exists to get right: one shared word is not one company
    for a, b in (("Bharat Forge", "Bharat Electronics"),
                 ("Bharat Forge", "Bharat Dynamics"),
                 ("Paramount Group", "Paramount Pictures")):
        j = jaccard(grams(a), grams(b))
        assert j < 0.75, "%s vs %s scores %.2f on surface alone -- needs another signal" % (a, b, j)

    # ...and the case it exists to catch
    assert jaccard(grams("Bharat Forge Limited"), grams("Bharat Forge")) > 0.9

    # an identifier clash must forbid a link no matter how alike the names are
    assert identifiers("Foo Ltd 1994/002123/07") == {"1994/002123/07"}
    assert not (identifiers("A 1994/002123/07") & identifiers("B 2001/118822/07"))

    # 3-grams are script-agnostic: the function must produce grams for a caseless script
    assert len(grams("한화시스템")) >= 4 and len(grams("中国船舶集团")) >= 4

    # A name that is ONLY a legal suffix must not fold to nothing, because every empty string
    # matches every other one. On the first run this merged AS, A.S., company, corporation and
    # group into a single ten-member entity.
    for bare in ("AS", "A.Ş.", "company", "group", "Corporation", "Ltd"):
        assert fold(bare), "%r folded away to nothing" % bare
    assert fold("AS") != fold("group"), "two different bare suffixes must not collide"

    # script comparability: a zero surface score across scripts is "not applicable", not "different"
    assert comparable_scripts("Paramount Group", "Paramount Group (Pty) Ltd")
    assert not comparable_scripts("Paramount Group", "帕拉蒙集团")
    assert not comparable_scripts("Hanwha Systems", "한화시스템")
    assert comparable_scripts("Rostec", "Ростех") is False
    # Japanese mixes kanji and kana, so two ordinary Japanese names DO share a script...
    assert comparable_scripts("三菱重工業の艦艇", "川崎重工業の潜水艦")
    # ...but a name written purely in kanji and the same name in pure katakana share none, and
    # treating that zero as evidence of difference is exactly the bug this guards.
    assert not comparable_scripts("三菱重工業", "パラマウント")
    # The renormalisation lifts a cross-script pair out of the 0.45 dead zone so it can at least be
    # SEEN...
    w_embed, w_cooc = 0.30, 0.15
    assert (w_embed + w_cooc) < 0.93 <= (w_embed + w_cooc) / (w_embed + w_cooc), \
        "renormalising must lift cross-script pairs out of the unreachable band"
    # ...and the cap then holds them in review, on purpose. Both rules are needed: without the
    # first they are invisible, without the second they merge six media outlets into one.

    # ---- human verdicts must actually decide, in BOTH directions -------------------------
    # A constraint table that is written but never read is not adjudication, it is data entry:
    # the next run re-derives the same answer and the week's work is gone. So the override is
    # tested here rather than assumed, and it is tested in both directions -- forcing a merge the
    # score would refuse, and refusing one the score would force.
    assert _ckey("b", "a") == _ckey("a", "b") == ("a", "b"), \
        "constraints are unordered: adjudicating (a,b) must settle (b,a) too"

    class _FakeInfo(dict):
        pass

    def _run(constraints):
        # Two surfaces that are string-identical after folding, so the scorer would auto-merge.
        order_ = [("acme ltd", "Organization"), ("acme limited", "Organization")]
        info_ = [{"text": "Acme Ltd", "langs": collections.Counter({"en": 3}),
                  "docs": {"d1"}, "n": 3},
                 {"text": "Acme Limited", "langs": collections.Counter({"en": 2}),
                  "docs": {"d1"}, "n": 2}]
        v = np.ones((2, 8), dtype=np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        return resolve(v, order_, info_, verbose=False, constraints=constraints)

    auto0, _rev0, ledger0, _d0 = _run(None)
    assert ledger0, "the fixture must merge on its own, or the override test proves nothing"

    _a1, _r1, ledger1, _d1 = _run({_ckey("acme ltd", "acme limited"): "must_not_link"})
    assert not ledger1, "must_not_link has to BLOCK a merge the score would have made"

    order_rev = [("zzz widget", "Organization"), ("qqq gadget", "Organization")]
    info_rev = [{"text": "Zzz Widget", "langs": collections.Counter({"en": 1}),
                 "docs": {"d9"}, "n": 1},
                {"text": "Qqq Gadget", "langs": collections.Counter({"en": 1}),
                 "docs": {"d8"}, "n": 1}]
    vr = np.zeros((2, 8), dtype=np.float32)
    vr[0, 0] = 1.0
    vr[1, 1] = 1.0
    _a2, _r2, ledger_no, _d2 = resolve(vr, order_rev, info_rev, verbose=False)
    assert not ledger_no, "two unrelated names must not merge unaided"
    _a3, _r3, ledger_yes, _d3 = resolve(
        vr, order_rev, info_rev, verbose=False,
        constraints={_ckey("zzz widget", "qqq gadget"): "must_link"})
    assert ledger_yes, "must_link has to FORCE a merge the score would have refused"

    # A shell heredoc has collapsed a backslash escape into a real control byte in this project
    # three times now. The byte is invisible, the file still looks right, and Python refuses to
    # import it. Cheap to check, so check it.
    src = io.open(__file__, encoding="utf-8").read()
    ctrl = {c for c in src if ord(c) < 32 and c not in "\n\t"}
    assert not ctrl, "control characters in the source: %r" % [hex(ord(c)) for c in ctrl]
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--set", dest="sset", default=None,
                    help="population prefix under data/ (default: bench)")
    ap.add_argument("--db", default=None, help="output store name (default: layer_b.db)")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        main(write=a.write, sset=a.sset, db_name=a.db)
