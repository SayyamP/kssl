"""Roundtrip check against a RUNNING stack (starts nothing).

Asserts GET /api/dataset returns all 35 globals with the right top-level kinds
(dict/list) per contract_shapes.json, and at least 28 competitors, 507
matchups, 22 tenders. Plain asserts, no framework.

If reference_dataset.json is readable it ALSO deep-compares every global
against the reference (informational by default — pipeline rows legitimately
diverge; set KSSL_STRICT=1 to make any difference fatal, e.g. right after a
fresh seed).

Usage:  python db/test_roundtrip.py
Env:    KSSL_API (default http://127.0.0.1:8600)
        KSSL_STRICT=1  -> deep equality with the reference dataset is asserted
"""

import json
import os
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("KSSL_API", "http://127.0.0.1:8600").rstrip("/")
SHAPES = os.path.join(HERE, "..", "contract_shapes.json")
REFERENCE = os.path.join(HERE, "..", "reference_dataset.json")

KIND_TYPES = {"dict": dict, "list": list, "str": str, "int": int, "bool": bool}


def get_json(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    with open(SHAPES, encoding="utf-8") as f:
        shapes = json.load(f)

    health = get_json(API + "/healthz")
    assert health.get("ok") is True, "healthz not ok: %r" % (health,)

    ds = get_json(API + "/api/dataset")

    # All 35 globals present, nothing extra.
    missing = sorted(set(shapes) - set(ds))
    extra = sorted(set(ds) - set(shapes))
    assert not missing, "missing globals: %s" % missing
    assert not extra, "unexpected globals: %s" % extra
    assert len(ds) == 35, "expected 35 globals, got %d" % len(ds)

    # Top-level kind per contract.
    for name, spec in shapes.items():
        kind = spec["shape"]["kind"]
        want = KIND_TYPES[kind]
        got = ds[name]
        assert isinstance(got, want), (
            "%s: expected %s, got %s" % (name, kind, type(got).__name__))

    # Minimum row counts after seeding.
    assert len(ds["competitors"]) >= 28, (
        "competitors: %d < 28" % len(ds["competitors"]))
    assert len(ds["matchups"]) >= 507, "matchups: %d < 507" % len(ds["matchups"])
    assert len(ds["tenders"]) >= 22, "tenders: %d < 22" % len(ds["tenders"])

    # Usable-shape spot checks (an empty groups list or a string where a list
    # belongs blanks the whole app).
    assert isinstance(ds["PATENTS"], dict) and set(ds["PATENTS"]) >= {
        "techAreas", "byArea", "byAssignee", "_meta"}, "PATENTS pieces missing"
    for lane in ("competitive", "market", "technology"):
        oc = ds["overviewConfig"].get(lane, {})
        assert isinstance(oc.get("groups"), list), (
            "overviewConfig.%s.groups is not a list" % lane)

    print("PASS shape check: 35 globals, kinds match, counts "
          "competitors=%d matchups=%d tenders=%d"
          % (len(ds["competitors"]), len(ds["matchups"]), len(ds["tenders"])))

    # Deep comparison with the reference dataset (exact-assembly proof).
    if os.path.exists(REFERENCE):
        with open(REFERENCE, encoding="utf-8") as f:
            ref = json.load(f)
        diffs = [k for k in shapes if ds.get(k) != ref.get(k)]
        if diffs:
            msg = ("deep-compare: %d/35 globals differ from reference: %s"
                   % (len(diffs), diffs))
            if os.environ.get("KSSL_STRICT") == "1":
                raise AssertionError(msg)
            print("NOTE " + msg + " (pipeline rows? set KSSL_STRICT=1 to fail)")
        else:
            print("PASS deep-compare: all 35 globals byte-equivalent "
                  "to reference_dataset.json")


if __name__ == "__main__":
    main()
