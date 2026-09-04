-- competitor_structure: ownership, which the schema has never held.
--
-- Profile.jsx carries a comment explaining that its corporate-structure graph was fed
-- an if-chain of hand-typed strings for about six firms ("BDL Kanchanbagh Guided
-- Missile Complex" and the like), that 95f781c replaced all of it with null, and that
-- the graph now draws competitors.partners under the heading "Partner Network" --
-- because there is no parent, sister or subsidiary column anywhere and no writer that
-- could fill one. This is that column, and enrich_serving.step_structure is that writer.
--
-- Two departures from the spec in KSSL VPS_DB.docx, both deliberate:
--
--   origin      the doc omits it. Every other serving table carries it, serving_live
--               filters on it, and without it there is no safe subset for a writer to
--               delete on rebuild -- the exact gap the 2026-09-02 competitor_news
--               migration was written to close.
--   source_url  the doc has it nullable. NOT NULL puts this project's no-fabrication
--               rule in the database rather than in a reviewer's memory: an ownership
--               claim nobody can cite cannot be stored, so it cannot reach the graph.
--
-- Fail fast rather than queue. The FK cascades from serving.competitors, and the enrich
-- pass deletes every pipeline competitor row and then spends minutes on LLM calls before
-- committing -- an ALTER arriving mid-pass waits for ACCESS EXCLUSIVE and blocks every
-- reader behind it, measured at 2m37s on 2026-09-02. Stop extraction-enrich-1 first.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS serving.competitor_structure (
    id                bigserial PRIMARY KEY,
    comp_id           text NOT NULL REFERENCES serving.competitors(comp_id) ON DELETE CASCADE,
    entity_id         text,
    entity_name       text NOT NULL,
    -- 'sister' is allowed and nothing writes it yet: no single statement asserts one,
    -- it is derived from two companies sharing a stated parent.
    relationship_type text NOT NULL
        CHECK (relationship_type IN ('parent', 'subsidiary', 'sister', 'division')),
    ownership_pct     numeric CHECK (ownership_pct > 0 AND ownership_pct <= 100),
    description       text,
    source_url        text NOT NULL,
    source_note       text,
    origin            text NOT NULL DEFAULT 'pipeline',
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS competitor_structure_comp_idx
    ON serving.competitor_structure (comp_id, relationship_type);
-- One edge per direction. The same ownership stated in three articles is one row,
-- not three nodes with the same label on the graph.
CREATE UNIQUE INDEX IF NOT EXISTS competitor_structure_edge_idx
    ON serving.competitor_structure (comp_id, entity_id, relationship_type);

CREATE OR REPLACE VIEW serving_live.competitor_structure AS
  SELECT id, comp_id, entity_id, entity_name, relationship_type, ownership_pct,
         description, source_url, source_note, updated_at
    FROM serving.competitor_structure WHERE origin = 'pipeline';
