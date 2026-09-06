# -*- coding: utf-8 -*-
"""build_lineage reconstructs only recorded provenance, and labels the rest honestly.

Hermetic: a FakeCur answers each stage's SELECT from canned rows shaped like the real
`kssl` database (values taken from the live doc_84bab27259bcdb32 trace). No DB, no writes.

Run: python backend/test_lineage.py
"""
import os
import sys

os.environ.setdefault("KSSL_CORPUS_DSN", "postgresql://unused/unused")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

DID = "doc_84bab27259bcdb32"
CARD_ID = "pl_" + DID
URL = "https://www.analisidifesa.it/2026/09/blindo-centauro-ii-per-lesercito-brasiliano"


def leonardo_rows():
    """Canned {query-substring: result} for the full Leonardo chain."""
    return {
        "FROM public.documents": {"rec": {
            "document_id": DID, "url": URL, "source_id": "analisidifesa.it",
            "language": "it", "published_at": "2026-08-27T00:00:00Z",
            "fetched_at": "2026-09-01T23:17:48Z", "text_len": 2119}},
        "to_regclass('public.extract_queue')": {"t": "public.extract_queue"},
        "FROM public.extract_queue": {"rec": {
            "document_id": DID, "class": 1, "state": "done", "reason": None,
            "attempts": 1, "crawl_ts": "2026-09-01T23:17:48Z"}},
        "FROM extracted.document": {"rec": {
            "document_id": DID, "language": "it", "n_chars": 2119,
            "first_seen": "2026-09-02T00:14:00Z"}},
        "FROM extracted.proposition": [
            {"rec": {"i": 0, "run_id": "run-20260901-235140", "subject": "Leonardo",
                     "predicate": "signed with", "object": "Esercito Brasiliano",
                     "modality": None, "polarity": None, "ev_start": 10, "ev_end": 88,
                     "ev_quote": "Leonardo, attraverso il Consorzio CIO (IDV - OTO Melara)"}},
            {"rec": {"i": 1, "run_id": "run-20260901-235140",
                     "subject": "sette veicoli ruotati 8x8 Centauro II",
                     "predicate": "are", "object": "forniti", "modality": None,
                     "polarity": None, "ev_start": 120, "ev_end": 175,
                     "ev_quote": "Il contratto prevede la fornitura di sette veicoli"}}],
        "count(*) AS n FROM extracted.span": {"n": 30},
        "FROM extracted.extraction_run": {"rec": {
            "run_id": "run-20260901-235140", "pipeline_version": "untracked:2b3c6b8debbb",
            "lexicon_version": "abc123", "model": "text-model",
            "config": {"gliner_threshold": 0.2}, "started_at": "2026-09-01T23:51:40Z"}},
        "FROM serving.signal_card": {"rec": {
            "id": CARD_ID, "lane": "competitive", "company": "Leonardo",
            "title": "Leonardo wins Centauro II contract with Brazilian Army",
            "lens": "Competitive", "sowhat": "New serial order.", "url": URL,
            "origin": "pipeline", "updated_at": "2026-09-02T01:00:00Z"}},
        "FROM serving.signal_detail": {"rec": {
            "id": CARD_ID, "facts": [["Company", "Leonardo"],
                                     ["Category", "Protected & Armoured Vehicles"]],
            "what": "Leonardo signed a production contract with the Brazilian Army.",
            "why": "Expands its armoured-vehicle footprint.",
            "translated": "t1", "updated_at": "2026-09-02T01:00:00Z"}},
    }


class FakeCur:
    """Dispatches each SELECT to a canned result by substring; records every statement."""

    def __init__(self, rows):
        self.rows, self.executed, self._last = rows, [], None

    def execute(self, sql, params=None):
        self.executed.append(sql)
        flat = " ".join(sql.split())
        # to_regclass(%s) is the enrichment table probe -- report every such table absent.
        if "to_regclass(%s)" in flat:
            self._last = {"t": None}
            return
        for key, val in self.rows.items():
            if key in flat:
                self._last = val
                return
        self._last = None

    def fetchone(self):
        r = self._last
        return (r[0] if r else None) if isinstance(r, list) else r

    def fetchall(self):
        r = self._last
        return r if isinstance(r, list) else ([r] if r else [])


def _stage(body, name):
    for s in body["stages"]:
        if s["stage"] == name:
            return s
    return None


def test_leonardo_chain():
    code, body = app.build_lineage(FakeCur(leonardo_rows()), DID)
    assert code == 200, code
    assert body["document_id"] == DID
    assert body["read_only"] is True
    assert len(body["known_gaps"]) == 4

    raw = _stage(body, "raw_corpus")
    assert raw["status"] == "recorded" and raw["record"]["url"] == URL

    gate = _stage(body, "gate")
    assert gate["status"] == "recorded" and "class=1" in gate["reason"] and "state=done" in gate["reason"]

    run = _stage(body, "extraction_run")
    assert run["status"] == "recorded" and run["model"]["model"] == "text-model"
    assert run["model"]["pipeline_version"] == "untracked:2b3c6b8debbb"

    props = _stage(body, "propositions")
    assert props["status"] == "recorded" and len(props["evidence"]) == 2
    assert props["evidence"][0]["ev_quote"].startswith("Leonardo, attraverso")

    card = _stage(body, "signal_card")
    assert card["status"] == "recorded" and card["record"]["company"] == "Leonardo"
    assert card["record"]["lane"] == "competitive"

    detail = _stage(body, "signal_detail")
    assert detail["status"] == "recorded" and "translated=t1" in detail["reason"]

    api = _stage(body, "api_destination")
    assert api["status"] == "reconstructed" and "signal_card[competitive]" in api["identifier"]
    ui = _stage(body, "ui_destination")
    assert ui["status"] == "reconstructed" and "competitive" in ui["identifier"].lower()
    print("  ok  Leonardo document returns the full recorded chain")


def test_prop_to_card_is_reconstructed_not_recorded():
    # The card text is English (translated); the propositions are Italian. The link must
    # come back reconstructed with NO match -- never asserted as recorded, never invented.
    code, body = app.build_lineage(FakeCur(leonardo_rows()), DID)
    link = _stage(body, "prop_to_card_link")
    assert link["status"] == "reconstructed", link
    assert link["matched_proposition_indices"] == [], link
    assert "not" in link["note"].lower()
    print("  ok  prop->card link is reconstructed + honestly empty (translated text)")


def test_nonexistent_returns_404():
    code, body = app.build_lineage(FakeCur({}), "doc_does_not_exist")
    assert code == 404, code
    assert body["document_id"] == "doc_does_not_exist"
    assert "error" in body and "checked" in body
    print("  ok  unknown document -> clean 404, nothing fabricated")


def test_missing_lineage_is_explicit_not_invented():
    # Raw doc + card exist, but extract_queue table is absent on this DB. The gate stage
    # must say provenance_unavailable with a note, and must NOT invent a reason/state.
    rows = leonardo_rows()
    rows["to_regclass('public.extract_queue')"] = {"t": None}
    code, body = app.build_lineage(FakeCur(rows), DID)
    assert code == 200
    gate = _stage(body, "gate")
    assert gate["status"] == "provenance_unavailable", gate
    assert "reason" not in gate, "must not fabricate a gate reason when unrecorded"
    assert "absent" in gate["note"].lower()
    print("  ok  missing stage -> provenance_unavailable, no fabricated reason")


def test_endpoint_is_read_only():
    fake = FakeCur(leonardo_rows())
    app.build_lineage(fake, DID)
    for sql in fake.executed:
        head = sql.strip().split(None, 1)[0].upper()
        assert head == "SELECT", "non-SELECT issued: %r" % sql[:60]
    joined = " ".join(fake.executed).upper()
    for w in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "DROP", "CREATE"):
        assert w not in joined, "write keyword %s present" % w
    print("  ok  every statement is a SELECT; endpoint performs no writes")


if __name__ == "__main__":
    test_leonardo_chain()
    test_prop_to_card_is_reconstructed_not_recorded()
    test_nonexistent_returns_404()
    test_missing_lineage_is_explicit_not_invented()
    test_endpoint_is_read_only()
    print("ok - lineage POC: recorded chain traced, gaps explicit, read-only")
