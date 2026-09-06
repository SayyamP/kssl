-- Append-only provenance.event, for existing databases. Folded into db/07_provenance.sql
-- for fresh ones. Idempotent. See db/07_provenance.sql for the design.
CREATE SCHEMA IF NOT EXISTS provenance;

CREATE TABLE IF NOT EXISTS provenance.event (
    event_id    bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    stage       text NOT NULL,
    component   text NOT NULL,
    document_id text,
    run_id      text,
    ref_table   text,
    ref_id      text,
    action      text NOT NULL CHECK (action IN (
                  'selected', 'gated', 'extracted', 'record_rejected', 'transformed',
                  'card_written', 'enriched', 'served', 'error', 'retry')),
    reason      text,
    evidence    jsonb,
    input_hash  text,
    output_hash text
);
CREATE INDEX IF NOT EXISTS event_doc_idx    ON provenance.event (document_id, ts);
CREATE INDEX IF NOT EXISTS event_action_idx ON provenance.event (action, ts);
CREATE INDEX IF NOT EXISTS event_run_idx    ON provenance.event (run_id);
