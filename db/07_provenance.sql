-- Append-only provenance events: what happened to a document as it moved through the
-- pipeline. Written by extraction/signals/provenance.py from live pipeline calls; read
-- by the future Backend Intelligence dashboard and by anyone asking "why didn't this
-- document appear?". NOT in the serving/serving_live snapshot scope on purpose -- this is
-- observability, not served data.
--
-- APPEND-ONLY: the writer only ever INSERTs. There is no backfill, so every row is a real
-- observed event and a document predating instrumentation simply has none.
CREATE SCHEMA IF NOT EXISTS provenance;

CREATE TABLE provenance.event (
    event_id    bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    stage       text NOT NULL,          -- 'gate','extraction','signals','enrich',...
    component   text NOT NULL,          -- the module: 'route.py','serving_fill.py',...
    document_id text,                   -- null where an event is not about one document
    run_id      text,                   -- extraction_run.run_id, or the process RUN_ID
    ref_table   text,                   -- the row this event is about, e.g. 'serving.signal_card'
    ref_id      text,                   -- its id, e.g. 'pl_doc_...'
    action      text NOT NULL CHECK (action IN (
                  'selected', 'gated', 'extracted', 'record_rejected', 'transformed',
                  'card_written', 'enriched', 'served', 'error', 'retry')),
    reason      text,                   -- WHY: 'stale','offtopic','deferred:no-live-node',...
    evidence    jsonb,                  -- safe telemetry only: model/run/version, counts
    input_hash  text,                   -- optional content hashes for correlation
    output_hash text
);
-- The three questions the dashboard asks: this document's timeline; everything of one
-- kind (e.g. all record_rejected); and everything a run touched.
CREATE INDEX event_doc_idx    ON provenance.event (document_id, ts);
CREATE INDEX event_action_idx ON provenance.event (action, ts);
CREATE INDEX event_run_idx    ON provenance.event (run_id);
