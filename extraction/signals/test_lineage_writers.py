# -*- coding: utf-8 -*-
"""The provenance a writer records must be correct, and never guessed.

Pure-function tests for the lineage the two writers attach:
  serving_fill.card_lineage  -- per-document card: doc, single run, prop indices
  enrich_serving.tie_doc_ids -- multi-document tie: every contributing document

Run: python extraction/signals/test_lineage_writers.py
"""
import os
import sys

os.environ.setdefault("KSSL_DSN", "postgresql://unused/unused")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serving_fill  # noqa: E402
import enrich_serving  # noqa: E402


def test_card_lineage_single_run():
    doc_ids, run_id, prop_ids = serving_fill.card_lineage(
        "doc_x", [("run-1", 0), ("run-1", 1), ("run-1", 2)])
    assert doc_ids == ["doc_x"], doc_ids
    assert run_id == "run-1", run_id
    assert prop_ids == [0, 1, 2], prop_ids
    print("  ok  card_lineage: one document, one run, its proposition indices")


def test_card_lineage_multi_run_refuses_to_guess():
    # A document whose props span two runs: the run is ambiguous, so it is NULL, never
    # an arbitrary pick. The doc id and prop indices are still honest.
    doc_ids, run_id, prop_ids = serving_fill.card_lineage(
        "doc_y", [("run-1", 0), ("run-2", 1)])
    assert doc_ids == ["doc_y"]
    assert run_id is None, "must not pick one of two runs"
    assert prop_ids == [0, 1]
    print("  ok  card_lineage: multiple runs -> run_id NULL (no fabrication)")


def test_card_lineage_no_props():
    doc_ids, run_id, prop_ids = serving_fill.card_lineage("doc_z", [])
    assert doc_ids == ["doc_z"] and run_id is None and prop_ids == []
    print("  ok  card_lineage: no propositions -> doc only, nothing invented")


def test_tie_doc_ids_preserves_every_contributing_document():
    docs = {"d1": {}, "d2": {}, "d3": {}}
    pr = {"alt_docs": ["d2", "d3"]}
    assert enrich_serving.tie_doc_ids("d1", pr, docs) == ["d1", "d2", "d3"]
    print("  ok  tie_doc_ids: multi-document provenance preserved, not collapsed")


def test_tie_doc_ids_filters_and_dedupes():
    docs = {"d1": {}, "d2": {}}                 # d9 not in corpus
    pr = {"alt_docs": ["d2", "d9", "d1"]}       # d9 absent, d1 duplicates primary
    assert enrich_serving.tie_doc_ids("d1", pr, docs) == ["d1", "d2"]
    print("  ok  tie_doc_ids: unknown docs dropped, duplicates removed, sorted")


def test_tie_doc_ids_single_source():
    docs = {"d1": {}}
    assert enrich_serving.tie_doc_ids("d1", {}, docs) == ["d1"]
    assert enrich_serving.tie_doc_ids("d1", {"alt_docs": None}, docs) == ["d1"]
    print("  ok  tie_doc_ids: a single-source tie records exactly its one document")


if __name__ == "__main__":
    test_card_lineage_single_run()
    test_card_lineage_multi_run_refuses_to_guess()
    test_card_lineage_no_props()
    test_tie_doc_ids_preserves_every_contributing_document()
    test_tie_doc_ids_filters_and_dedupes()
    test_tie_doc_ids_single_source()
    print("ok - writers record correct provenance and never guess")
