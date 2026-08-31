"""Regression armour for the production audit fixes. Offline: no DB, no network, no GPU.

    python3 test_fixes.py

Each assert pins one fix from the Fable 5 audit so it cannot silently regress. Run in CI or before
any deploy. Exits non-zero on the first failure.
"""
import os
import sys
import time
import unicodedata
from pathlib import Path

ENGINE = Path(__file__).parent / "engine"
sys.path.insert(0, str(ENGINE))
os.environ.setdefault("C_DS_JSON", str(ENGINE / "ds.json"))
os.environ.setdefault("C_TIERS_PATH", str(ENGINE / "source_tiers.py"))

import segment      # noqa: E402
import values       # noqa: E402
import store_pg     # noqa: E402


def test_values_redos_bounded():
    """B7: a long separator-joined digit run must not pin a core (was 267s at 80KB)."""
    run = "1,234" + ",234" * 20000            # ~80KB
    t = time.time(); spans = values.find(run); dt = time.time() - t
    assert dt < 2.0, "values.find ReDoS: %.1fs on 80KB digit run" % dt
    assert spans, "should still find numbers"


def test_cjk_sentence_split():
    """H3: full-width CJK terminators split without trailing whitespace."""
    text = "第一句话在这里。第二句话也在这里。第三句话结束。"
    sents = segment.sentences(text)
    assert len(sents) == 3, "CJK did not split: got %d sentences" % len(sents)
    for s in sents:                            # offset contract holds on CJK
        assert text[s["start"]:s["end"]] == s["text"]


def test_latin_split_unregressed():
    """H3: Latin splitting must be unchanged -- no split on decimals/abbreviations."""
    assert len(segment.sentences("The U.S. Army bought 3.14 tons. It works well.")) == 2


def test_offset_contract_nasty_text():
    """The offset contract holds on CRLF / NFD / RTL / mixed input for tokenise+values."""
    samples = [
        "Rheinmetall\r\ndelivered 12 howitzers.\r\n",
        unicodedata.normalize("NFD", "Türkiye ordered 5 Bayraktar TB2 for €2.3 million."),
        "الجيش اشترى 3 طائرات بدون طيار.",
    ]
    for txt in samples:
        for s in values.find(txt):
            assert txt[s["start"]:s["end"]] == s["text"], "values offset broke on %r" % txt[:30]
        for s in segment.sentences(txt):
            assert txt[s["start"]:s["end"]] == s["text"], "sentence offset broke on %r" % txt[:30]


def test_doc_meta_carries_published_at():
    """B1: store_pg._doc_meta puts the crawler date where the serving date-gate reads it."""
    meta = store_pg._doc_meta({"coverage": {"pct_content": 88}, "published_at": "2026-08-29T00:00:00Z"})
    assert meta.get("published_at") == "2026-08-29T00:00:00Z", "published_at dropped from meta"
    assert meta.get("pct_content") == 88, "coverage stats must stay at top level"
    # absent date -> key omitted, not a null that reads as 'proven no date'
    assert "published_at" not in store_pg._doc_meta({"coverage": {}})


def test_doc_sql_merges_meta():
    """B1: the doc upsert MERGES meta (||), never replaces -- a harvest date must survive re-extract."""
    assert "||" in store_pg.DOC_SQL and "EXCLUDED.meta" in store_pg.DOC_SQL, \
        "DOC_SQL must merge meta, not clobber it"


def test_gliner_sends_texts_key():
    """B3: the GLiNER request must carry the 'texts' key the farm contract requires."""
    src = (ENGINE / "comprehend.py").read_text()
    assert '"texts": _sent_texts' in src, "GLiNER body must send the 'texts' key"


def test_published_at_threaded():
    """B1: route surfaces published_at, comprehend carries it into rec."""
    assert "published_at" in (ENGINE / "route.py").read_text().split("DOC_COLS =")[1][:120]
    assert '"published_at": doc.get("published_at")' in (ENGINE / "comprehend.py").read_text()


def test_num_predict_floored():
    """H4: the reply budget can never go negative (unlimited generation on a huge chunk)."""
    assert "max(256, min(npred" in (ENGINE / "comprehend.py").read_text(), \
        "num_predict must be floored at 256"


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("  ok  %s" % t.__name__)
    print("ALL %d PASS" % len(tests))


if __name__ == "__main__":
    run()
