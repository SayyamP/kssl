-- client_product: the client's OWN products and specifications, which the schema has
-- never held.
--
-- Every KSSL-side value in serving.matchup.specs (the `kv` column of each spec row) was
-- either copied unsourced from the demo archive or left null by revive_matchups.py,
-- because the corpus holds no document in which KSSL states its own specifications.
-- Measured on production 2026-09-05: 160 served matchups, 90 with any KSSL value, and
-- the acceptance list carried "specification comparison data is unavailable from the
-- KSSL side" (MD 11) and "KSSL advantages information is missing" (MD 10).
--
-- On 2026-09-05 the client supplied their master product-specification workbook, 59
-- products across seven headings of THEIR OWN, with a Sources column per row. This
-- table is that workbook, row for row, bullet for bullet: `specs` and `features` are
-- the cell's bullets as written ([{k, v, note, ctx}], where ctx is the sub-heading a
-- bullet sat under), `sources` the URLs the row cites, `file_category` the client's
-- heading verbatim. The dashboard's category (`cat`, `catKey`) is a SEPARATE column
-- filled from an explicit map in extraction/signals/client_portfolio.py -- never from the
-- label -- and is NULL where no dashboard category exists (a ground rover filed under
-- "UAVs & Drones").
--
-- Sixteen rows have an em dash for specifications. They are stored with specs = '[]'
-- and stay that way: an empty row is the client saying "nothing published", and no
-- sibling product's figure may be inferred into it.
--
-- origin is 'reference' on purpose. The two-hourly enrich pass deletes and rebuilds
-- only origin='pipeline'; the client's statement of their own products is not
-- something the corpus can rebuild, so it must survive every pass.
-- client_portfolio.py --apply is the only writer and replaces the reference rows whole.
--
-- No serving_live view: the backend does not read this table. Its consumer is
-- revive_matchups.py, which reads it directly when it rebuilds the served matchups.
--
-- Stop extraction-enrich-1 before applying, as for every serving.* change (the pass
-- holds locks across minutes of LLM calls; measured 2m37s wait on 2026-09-02).
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS serving.client_product (
    product_id    text PRIMARY KEY,
    ord           integer NOT NULL,
    name          text NOT NULL,
    file_category text NOT NULL,
    cat           text,
    "catKey"      text,
    specs         jsonb NOT NULL DEFAULT '[]'::jsonb,
    features      jsonb NOT NULL DEFAULT '[]'::jsonb,
    sources       jsonb NOT NULL DEFAULT '[]'::jsonb,
    origin        text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_product_catkey_idx ON serving.client_product ("catKey");
