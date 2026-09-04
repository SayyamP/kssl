-- The "give it an article and watch" queue.
--
-- The dashboard lives on the VPS; the extraction it triggers must happen at the
-- data centre. Rather than open an inbound path from one to the other, the VPS
-- writes a job row here and a data-centre worker polls for it. The only network
-- direction that already exists (data centre -> VPS database) is the only one
-- used, so this needs no firewall change and no reverse tunnel.
--
-- Per-stage timings are NOT duplicated here. Every stage already writes to
-- metrics.stage_run with a run_id; the dashboard reads them back by that id.
-- One table decides what a timing means, and it is that one.

CREATE TABLE IF NOT EXISTS metrics.adhoc_job (
    run_id      text PRIMARY KEY,
    submitted   timestamptz NOT NULL DEFAULT now(),
    claimed_at  timestamptz,
    finished_at timestamptz,
    -- queued -> running -> done | failed. A worker claims by moving queued to
    -- running in one UPDATE, so two workers cannot take the same job.
    status      text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','done','failed')),
    worker      text,
    stage       text,                   -- what it is doing right now
    url         text,
    raw_text    text,                   -- when the article was pasted, not fetched
    title       text,
    document_id text,
    layer_b     boolean NOT NULL DEFAULT false,
    card_id     text,                   -- the serving.signal_card it produced
    outcome     text,                   -- 'card' | 'refused: <reason>' | error
    detail      jsonb
);

CREATE INDEX IF NOT EXISTS adhoc_job_queue_idx
    ON metrics.adhoc_job (status, submitted)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS adhoc_job_recent_idx
    ON metrics.adhoc_job (submitted DESC);

-- One row per submitted article, with its stage timings folded in. The
-- dashboard polls this rather than assembling it client-side, so the numbers on
-- screen and the numbers in the database cannot drift apart.
CREATE OR REPLACE VIEW metrics.adhoc_summary AS
SELECT  j.run_id,
        j.submitted,
        j.status,
        j.stage,
        j.url,
        j.title,
        j.document_id,
        j.card_id,
        j.outcome,
        j.worker,
        -- How long THIS attempt has taken. Measured from the claim, not from
        -- the submission: a job that sat in the queue -- or was requeued after
        -- a fix -- would otherwise report the wait as if it were work, and the
        -- table would show 1993s for an article that had been running two
        -- minutes. Same definition whether it is running or finished, so the
        -- number does not change meaning as you watch it.
        round(EXTRACT(EPOCH FROM (
            coalesce(j.finished_at, now())
            - coalesce(j.claimed_at, j.submitted)))::numeric, 1) AS total_s,
        -- kept separately, because "how long since I asked for this" is a fair
        -- question too -- it is just not the same question.
        round(EXTRACT(EPOCH FROM (
            coalesce(j.finished_at, now()) - j.submitted))::numeric, 1) AS since_submitted_s,
        (SELECT count(*) FROM metrics.stage_run r WHERE r.run_id = j.run_id)  AS stages_done,
        (SELECT sum(r.ms) FROM metrics.stage_run r WHERE r.run_id = j.run_id) AS worked_ms,
        (SELECT sum(r.n_tokens) FROM metrics.stage_run r WHERE r.run_id = j.run_id) AS tokens
FROM metrics.adhoc_job j;
