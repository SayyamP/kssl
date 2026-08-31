"""Layer B on Postgres — canonical entities from the extracted spans, written back to Postgres.

    python3 layer_b_pg.py                 # resolve all entity mentions, write entity/entity_alias
    python3 layer_b_pg.py --write=false   # dry run: report clusters, write nothing
    python3 layer_b_pg.py --demo          # offline self-check (no DB)

WHAT THIS DOES
--------------
Reads every REFERENTIAL span (Organization, Person, Location, Country, ...) from `extracted.span`,
clusters the surfaces that name the same thing, and writes one `extracted.entity` per cluster with
its surfaces as `extracted.entity_alias`. A mention keeps its own text and offsets for ever; this
layer only ADDS the cross-reference, exactly as `layer_b.py` (the SQLite original) designed it.

THE BLOCKERS (reused verbatim from layer_b.py)
----------------------------------------------
  1. identical folded surface   "Rheinmetall AG" / "RHEINMETALL"         -> merge
  2. shared character 3-grams    typos, word order, legal-suffix variants -> merge if similar enough
  3. embedding neighbours        the ONLY cross-script blocker            -> NOT run here

Blocker 3 needs a served embedder (layer_b.py loads it from a precomputed population). Until one is
wired on VPS-B this port does SAME-SCRIPT canonicalisation only -- which covers the large majority of
merges -- and never guesses across scripts (a Chinese and an English name are left as two entities,
the honest outcome without embeddings). That is the single documented limitation of this port.

Idempotent: entity_id is a deterministic hash of (folded canonical, type), so re-running updates in
place rather than duplicating. Safe on a timer.
"""
import argparse
import collections
import hashlib
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "engine"))
os.environ.setdefault("C_DS_JSON", str(HERE / "engine" / "ds.json"))
os.environ.setdefault("C_TIERS_PATH", str(HERE / "engine" / "source_tiers.py"))
import layer_b  # noqa: E402  (pure helpers: fold, grams, jaccard, DSU, scripts_of, comparable_scripts, identifiers)


def _load_env():
    for p in (HERE / ".env", HERE.parent / ".env"):
        if p.exists():
            import io
            for line in io.open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
DSN = os.environ.get("KSSL_CORPUS_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
# The referential span types Layer B canonicalises. Non-referential types (Date, Money, Action...)
# are not entities and are skipped.
ENTITY_TYPES = ("Person", "Organization", "Location", "Country", "Facility", "Platform",
                "WeaponSystem", "Vehicle", "Aircraft", "Vessel", "Programme", "Product")
TAU = float(os.environ.get("LAYERB_TAU", "0.62"))          # 3-gram jaccard needed to merge
MAX_BUCKET = int(os.environ.get("LAYERB_MAX_BUCKET", "400"))  # skip ubiquitous grams (cost guard)


def _connect(dsn=DSN):
    import psycopg2
    return psycopg2.connect(dsn, connect_timeout=15, keepalives=1, keepalives_idle=60,
                            keepalives_interval=10, keepalives_count=3)


def read_mentions(conn):
    """Distinct (surface, type, lang) with mention counts. One row per surface spelling."""
    with conn.cursor() as c:
        c.execute("SET statement_timeout='120s'")
        c.execute(
            "SELECT s.text, s.type, coalesce(d.language,'und'), count(*) "
            "FROM extracted.span s JOIN extracted.document d USING (document_id) "
            "WHERE s.type = ANY(%s) AND length(s.text) BETWEEN 2 AND 120 "
            "GROUP BY s.text, s.type, coalesce(d.language,'und')",
            (list(ENTITY_TYPES),))
        rows = c.fetchall()
    info = []
    for text, typ, lang, n in rows:
        info.append({"text": text, "type": typ, "lang": (lang or "und")[:8],
                     "n": int(n), "folded": layer_b.fold(text)})
    return info


def cluster(info, verbose=True):
    """DSU over blockers 1 (folded surface) and 2 (3-gram jaccard, same script, no id clash).
    -> {root_index: [member_indices]}. Blocker 3 (embeddings/cross-script) is intentionally absent."""
    n = len(info)
    dsu = layer_b.DSU(n)
    t0 = time.time()

    # Blocker 1: identical folded surface AND identical type name the same thing.
    by_fold = collections.defaultdict(list)
    for i, m in enumerate(info):
        by_fold[(m["folded"], m["type"])].append(i)
    b1 = 0
    for members in by_fold.values():
        for j in members[1:]:
            if dsu.union(members[0], j):
                b1 += 1

    # Blocker 2: candidate pairs share a 3-gram; merge when similar enough, same type, comparable
    # script, and no hard-identifier clash. An inverted gram index keeps this near-linear; a gram
    # shared by more than MAX_BUCKET surfaces is too generic to be evidence and is skipped.
    grams_of = [layer_b.grams(m["text"]) for m in info]
    ids_of = [layer_b.identifiers(m["text"]) for m in info]
    inv = collections.defaultdict(list)
    for i, gs in enumerate(grams_of):
        for g in gs:
            inv[g].append(i)
    seen = set()
    b2 = 0
    for g, members in inv.items():
        if len(members) > MAX_BUCKET:
            continue
        for a_idx in range(len(members)):
            for b_idx in range(a_idx + 1, len(members)):
                i, j = members[a_idx], members[b_idx]
                if dsu.find(i) == dsu.find(j):
                    continue
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                if info[i]["type"] != info[j]["type"]:
                    continue
                if ids_of[i] and ids_of[j] and not (ids_of[i] & ids_of[j]):
                    continue                       # different registration numbers: forbidden
                if not layer_b.comparable_scripts(info[i]["text"], info[j]["text"]):
                    continue                       # cross-script: not this blocker's job
                if layer_b.jaccard(grams_of[i], grams_of[j]) >= TAU:
                    if dsu.union(i, j):
                        b2 += 1

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[dsu.find(i)].append(i)
    if verbose:
        print("  clustered %d surfaces -> %d entities (blocker1 %d, blocker2 %d) %.1fs"
              % (n, len(groups), b1, b2, time.time() - t0), flush=True)
    return groups


def entity_id_for(canonical_folded, typ):
    return "E" + hashlib.sha1(("%s|%s" % (canonical_folded, typ)).encode("utf-8")).hexdigest()[:16]


ENT_SQL = """
INSERT INTO extracted.entity (entity_id, entity_type, canonical_name, canonical_lang, created_by_run)
VALUES %s
ON CONFLICT (entity_id) DO UPDATE SET
  canonical_name = EXCLUDED.canonical_name, canonical_lang = EXCLUDED.canonical_lang;
"""
ALIAS_SQL = """
INSERT INTO extracted.entity_alias
  (entity_id, surface, surface_folded, lang, script, alias_kind, n_mentions)
VALUES %s
ON CONFLICT (entity_id, surface_folded, lang) DO UPDATE SET n_mentions = EXCLUDED.n_mentions;
"""


def write_entities(conn, info, groups, run_id):
    """Batched writes: 50k+ rows one-at-a-time is one network round-trip each -- minutes over a
    tunnel. execute_values sends them in pages, seconds even remotely."""
    from psycopg2.extras import execute_values
    ent_rows, alias_rows, seen_alias = [], [], set()
    for members in groups.values():
        ms = [info[i] for i in members]
        canon = max(ms, key=lambda m: (m["n"], len(m["text"])))   # most-mentioned, ties -> longer
        typ = canon["type"]
        eid = entity_id_for(canon["folded"], typ)
        ent_rows.append((eid, typ, canon["text"], canon["lang"][:3], run_id))
        for m in ms:
            key = (eid, m["folded"], m["lang"][:3])               # matches the alias PK; dedupe
            if key in seen_alias:
                continue
            seen_alias.add(key)
            script = next(iter(layer_b.scripts_of(m["text"])), "Latin")
            kind = "name"
            if m["folded"] != canon["folded"]:
                kind = "abbreviation" if len(m["text"]) < len(canon["text"]) else "legal_variant"
            alias_rows.append((eid, m["text"], m["folded"], m["lang"][:3], script, kind, m["n"]))
    with conn.cursor() as c:
        execute_values(c, ENT_SQL, ent_rows, page_size=1000)
        execute_values(c, ALIAS_SQL, alias_rows, page_size=1000)
    conn.commit()
    return len(ent_rows), len(alias_rows)


def run(write=True):
    conn = _connect()
    run_id = "layerb-" + time.strftime("%Y%m%dT%H%M%S")
    info = read_mentions(conn)
    print("read %d distinct entity surfaces" % len(info), flush=True)
    groups = cluster(info)
    if not write:
        print("dry run: %d entities would be written (no DB writes)" % len(groups), flush=True)
        conn.close()
        return len(groups), 0
    ent, alias = write_entities(conn, info, groups, run_id)
    conn.close()
    print("wrote %d entities, %d aliases (run %s)" % (ent, alias, run_id), flush=True)
    return ent, alias


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", default="true")
    a = ap.parse_args()
    run(write=str(a.write).lower() not in ("false", "0", "no"))


def _demo():
    # Offline: the blocking logic must merge legal-suffix/abbreviation variants of one company and
    # keep three different companies sharing a word apart -- the exact case layer_b.py is built for.
    info = [
        {"text": "Rheinmetall AG", "type": "Organization", "lang": "en", "n": 5, "folded": layer_b.fold("Rheinmetall AG")},
        {"text": "RHEINMETALL",    "type": "Organization", "lang": "en", "n": 3, "folded": layer_b.fold("RHEINMETALL")},
        {"text": "Rheinmetall",    "type": "Organization", "lang": "de", "n": 9, "folded": layer_b.fold("Rheinmetall")},
        {"text": "Bharat Forge",   "type": "Organization", "lang": "en", "n": 4, "folded": layer_b.fold("Bharat Forge")},
        {"text": "Bharat Dynamics","type": "Organization", "lang": "en", "n": 2, "folded": layer_b.fold("Bharat Dynamics")},
        {"text": "Bharat Electronics","type": "Organization","lang":"en","n":2,"folded": layer_b.fold("Bharat Electronics")},
    ]
    groups = cluster(info, verbose=False)
    clusters = [sorted(info[i]["text"] for i in g) for g in groups.values()]
    # the three Rheinmetall spellings collapse to one entity
    rh = [c for c in clusters if any("heinmetall" in x for x in c)]
    assert len(rh) == 1 and len(rh[0]) == 3, "Rheinmetall variants must merge: %s" % rh
    # the three different Bharat companies stay separate (share a word, not an identity)
    bh = [c for c in clusters if any("Bharat" in x for x in c)]
    assert len(bh) == 3, "different Bharat companies must NOT merge: %s" % bh
    assert entity_id_for("rheinmetall", "Organization") == entity_id_for("rheinmetall", "Organization")
    print("ok  folded+3-gram blocking merges variants, keeps distinct companies apart; ids stable")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        main()
