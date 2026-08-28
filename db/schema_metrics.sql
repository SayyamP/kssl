-- One place every stage reports into, so "how long does each step take" has a
-- single answer instead of seven log files.
--
-- The unit of measurement is a DOCUMENT's journey: a page lands in the corpus,
-- and some time later a card built from it appears in the UI. Each stage that
-- touches it writes one row here. End-to-end latency is then a query, not an
-- estimate.
--
-- Written by pipeline/stage_timer.py. Lives in the KSSL Postgres (the VPS one),
-- so stages running on the data centre write here through the SSH tunnel and
-- every number ends up in the same table.

CREATE SCHEMA IF NOT EXISTS metrics;

CREATE TABLE IF NOT EXISTS metrics.stage_run (
    id          bigserial PRIMARY KEY,
    run_id      text        NOT NULL,   -- groups one pass of the pipeline
    stage       text        NOT NULL,   -- see metrics.stage_order below
    doc_id      text,                   -- corpus document, when the unit is one doc
    host        text        NOT NULL,   -- 'datacentre' | 'vps' | 'workstation'
    started_at  timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz,
    ms          bigint,                 -- wall clock, written on finish
    n_items     integer,                -- docs / spans / cards produced
    n_tokens    integer,                -- LLM stages only: tokens generated
    ok          boolean,
    note        text,
    meta        jsonb
);

-- The two questions actually asked of this table: "how did stage X do" and
-- "where is document Y". Both want an index.
CREATE INDEX IF NOT EXISTS stage_run_stage_idx  ON metrics.stage_run (stage, started_at DESC);
CREATE INDEX IF NOT EXISTS stage_run_doc_idx    ON metrics.stage_run (doc_id) WHERE doc_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS stage_run_run_idx    ON metrics.stage_run (run_id);

-- Canonical stage names and their order. A stage not in this table is a typo:
-- the timer refuses to write one, which is the whole reason the table exists.
CREATE TABLE IF NOT EXISTS metrics.stage_order (
    stage       text PRIMARY KEY,
    ord         integer NOT NULL,
    label       text    NOT NULL,
    runs_on     text    NOT NULL,
    unit        text    NOT NULL
);

INSERT INTO metrics.stage_order (stage, ord, label, runs_on, unit) VALUES
    ('crawl',     1, 'Crawler fetches the page',        'datacentre', 'page'),
    ('corpus',    2, 'Page stored in the corpus',       'datacentre', 'document'),
    ('select',    3, 'Defence relevance gate',          'datacentre', 'document'),
    ('extract_a', 4, 'Layer A: spans and entities',     'datacentre', 'document'),
    ('extract_b', 5, 'Layer B: canonical + derived',    'datacentre', 'document'),
    ('llm',       6, 'LLM writes signals and cards',    'vps',        'card'),
    ('serving',   7, 'Serving tables rebuilt',          'vps',        'row'),
    ('frontend',  8, 'Dashboard renders the dataset',   'vps',        'request')
ON CONFLICT (stage) DO UPDATE
    SET ord = EXCLUDED.ord, label = EXCLUDED.label,
        runs_on = EXCLUDED.runs_on, unit = EXCLUDED.unit;

-- Per-stage summary. Median matters more than mean here: one 40-minute outlier
-- from a wedged host should not become "the extraction stage takes 40 minutes".
CREATE OR REPLACE VIEW metrics.stage_summary AS
SELECT  o.ord,
        o.stage,
        o.label,
        o.runs_on,
        o.unit,
        count(r.id)                                             AS runs,
        count(*) FILTER (WHERE r.ok IS FALSE)                    AS failures,
        round(avg(r.ms)::numeric / 1000, 2)                      AS mean_s,
        round((percentile_cont(0.5) WITHIN GROUP (ORDER BY r.ms))::numeric / 1000, 2) AS median_s,
        round((percentile_cont(0.95) WITHIN GROUP (ORDER BY r.ms))::numeric / 1000, 2) AS p95_s,
        sum(r.n_items)                                           AS items,
        sum(r.n_tokens)                                          AS tokens,
        -- tokens/sec for the LLM stages; NULL where no tokens were counted
        CASE WHEN sum(r.n_tokens) > 0 AND sum(r.ms) > 0
             THEN round(sum(r.n_tokens)::numeric * 1000 / sum(r.ms), 2) END AS tok_per_s,
        max(r.ended_at)                                          AS last_run
FROM        metrics.stage_order o
LEFT JOIN   metrics.stage_run   r ON r.stage = o.stage AND r.ended_at IS NOT NULL
GROUP BY o.ord, o.stage, o.label, o.runs_on, o.unit
ORDER BY o.ord;

-- One document's whole journey. This is the number the goal actually asks for:
-- corpus-to-screen, and where the time went.
CREATE OR REPLACE VIEW metrics.doc_journey AS
SELECT  r.doc_id,
        min(r.started_at)                                        AS entered,
        max(r.ended_at)                                          AS surfaced,
        round(EXTRACT(EPOCH FROM (max(r.ended_at) - min(r.started_at)))::numeric, 1) AS end_to_end_s,
        sum(r.ms) FILTER (WHERE r.stage IN ('crawl','corpus'))    AS crawl_ms,
        sum(r.ms) FILTER (WHERE r.stage IN ('select'))            AS select_ms,
        sum(r.ms) FILTER (WHERE r.stage IN ('extract_a'))         AS extract_a_ms,
        sum(r.ms) FILTER (WHERE r.stage IN ('extract_b'))         AS extract_b_ms,
        sum(r.ms) FILTER (WHERE r.stage IN ('llm'))               AS llm_ms,
        sum(r.ms) FILTER (WHERE r.stage IN ('serving'))           AS serving_ms,
        count(DISTINCT r.stage)                                   AS stages_seen,
        bool_and(coalesce(r.ok, true))                            AS all_ok
FROM metrics.stage_run r
WHERE r.doc_id IS NOT NULL
GROUP BY r.doc_id;
