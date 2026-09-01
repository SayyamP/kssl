--
-- PostgreSQL database dump
--

\restrict 3lxm77QqxCQ2Tz5sGz2j4Db6lFClYHEOBPik7hQKZbK80McPyKuKopCYBMztxFX

-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: metrics; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA metrics;


--
-- Name: serving_live; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA serving_live;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: adhoc_job; Type: TABLE; Schema: metrics; Owner: -
--

CREATE TABLE metrics.adhoc_job (
    run_id text NOT NULL,
    submitted timestamp with time zone DEFAULT now() NOT NULL,
    claimed_at timestamp with time zone,
    finished_at timestamp with time zone,
    status text DEFAULT 'queued'::text NOT NULL,
    worker text,
    stage text,
    url text,
    raw_text text,
    title text,
    document_id text,
    layer_b boolean DEFAULT false NOT NULL,
    card_id text,
    outcome text,
    detail jsonb,
    CONSTRAINT adhoc_job_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'done'::text, 'failed'::text])))
);


--
-- Name: stage_run; Type: TABLE; Schema: metrics; Owner: -
--

CREATE TABLE metrics.stage_run (
    id bigint NOT NULL,
    run_id text NOT NULL,
    stage text NOT NULL,
    doc_id text,
    host text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    ms bigint,
    n_items integer,
    n_tokens integer,
    ok boolean,
    note text,
    meta jsonb
);


--
-- Name: adhoc_summary; Type: VIEW; Schema: metrics; Owner: -
--

CREATE VIEW metrics.adhoc_summary AS
 SELECT run_id,
    submitted,
    status,
    stage,
    url,
    title,
    document_id,
    card_id,
    outcome,
    worker,
    round(EXTRACT(epoch FROM (COALESCE(finished_at, now()) - COALESCE(claimed_at, submitted))), 1) AS total_s,
    round(EXTRACT(epoch FROM (COALESCE(finished_at, now()) - submitted)), 1) AS since_submitted_s,
    ( SELECT count(*) AS count
           FROM metrics.stage_run r
          WHERE (r.run_id = j.run_id)) AS stages_done,
    ( SELECT sum(r.ms) AS sum
           FROM metrics.stage_run r
          WHERE (r.run_id = j.run_id)) AS worked_ms,
    ( SELECT sum(r.n_tokens) AS sum
           FROM metrics.stage_run r
          WHERE (r.run_id = j.run_id)) AS tokens
   FROM metrics.adhoc_job j;


--
-- Name: doc_journey; Type: VIEW; Schema: metrics; Owner: -
--

CREATE VIEW metrics.doc_journey AS
 SELECT doc_id,
    min(started_at) AS entered,
    max(ended_at) AS surfaced,
    round(EXTRACT(epoch FROM (max(ended_at) - min(started_at))), 1) AS end_to_end_s,
    sum(ms) FILTER (WHERE (stage = ANY (ARRAY['crawl'::text, 'corpus'::text]))) AS crawl_ms,
    sum(ms) FILTER (WHERE (stage = 'select'::text)) AS select_ms,
    sum(ms) FILTER (WHERE (stage = 'extract_a'::text)) AS extract_a_ms,
    sum(ms) FILTER (WHERE (stage = 'extract_b'::text)) AS extract_b_ms,
    sum(ms) FILTER (WHERE (stage = 'llm'::text)) AS llm_ms,
    sum(ms) FILTER (WHERE (stage = 'serving'::text)) AS serving_ms,
    count(DISTINCT stage) AS stages_seen,
    bool_and(COALESCE(ok, true)) AS all_ok
   FROM metrics.stage_run r
  WHERE (doc_id IS NOT NULL)
  GROUP BY doc_id;


--
-- Name: stage_order; Type: TABLE; Schema: metrics; Owner: -
--

CREATE TABLE metrics.stage_order (
    stage text NOT NULL,
    ord integer NOT NULL,
    label text NOT NULL,
    runs_on text NOT NULL,
    unit text NOT NULL
);


--
-- Name: stage_run_id_seq; Type: SEQUENCE; Schema: metrics; Owner: -
--

CREATE SEQUENCE metrics.stage_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stage_run_id_seq; Type: SEQUENCE OWNED BY; Schema: metrics; Owner: -
--

ALTER SEQUENCE metrics.stage_run_id_seq OWNED BY metrics.stage_run.id;


--
-- Name: stage_summary; Type: VIEW; Schema: metrics; Owner: -
--

CREATE VIEW metrics.stage_summary AS
 SELECT o.ord,
    o.stage,
    o.label,
    o.runs_on,
    o.unit,
    count(r.id) AS runs,
    count(*) FILTER (WHERE (r.ok IS FALSE)) AS failures,
    round((avg(r.ms) / (1000)::numeric), 2) AS mean_s,
    round(((percentile_cont((0.5)::double precision) WITHIN GROUP (ORDER BY ((r.ms)::double precision)))::numeric / (1000)::numeric), 2) AS median_s,
    round(((percentile_cont((0.95)::double precision) WITHIN GROUP (ORDER BY ((r.ms)::double precision)))::numeric / (1000)::numeric), 2) AS p95_s,
    sum(r.n_items) AS items,
    sum(r.n_tokens) AS tokens,
        CASE
            WHEN ((sum(r.n_tokens) > 0) AND (sum(r.ms) > (0)::numeric)) THEN round((((sum(r.n_tokens))::numeric * (1000)::numeric) / sum(r.ms)), 2)
            ELSE NULL::numeric
        END AS tok_per_s,
    max(r.ended_at) AS last_run
   FROM (metrics.stage_order o
     LEFT JOIN metrics.stage_run r ON (((r.stage = o.stage) AND (r.ended_at IS NOT NULL))))
  GROUP BY o.ord, o.stage, o.label, o.runs_on, o.unit
  ORDER BY o.ord;


--
-- Name: company_source; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.company_source AS
 SELECT company,
    comp_ord,
    ord,
    url,
    origin,
    updated_at
   FROM serving.company_source
  WHERE (origin = 'pipeline'::text);


--
-- Name: competitors; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.competitors AS
 SELECT comp_id,
    ord,
    name,
    dir,
    sector,
    hq,
    threat,
    assess,
    updates,
    center,
    partners,
    site,
    srcs,
    products,
    "threatNote",
    origin,
    updated_at,
    leadership,
    facilities,
    sales
   FROM serving.competitors
  WHERE (origin = 'pipeline'::text);


--
-- Name: geo_comp; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.geo_comp AS
 SELECT id,
    ord,
    name,
    dir,
    hq,
    "isBf",
    origin,
    updated_at
   FROM serving.geo_comp
  WHERE (origin = 'pipeline'::text);


--
-- Name: geo_presence; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.geo_presence AS
 SELECT comp_id,
    comp_ord,
    country,
    country_ord,
    ord,
    name,
    c,
    val,
    since,
    qty,
    stage,
    note,
    src,
    srcnote,
    origin,
    updated_at
   FROM serving.geo_presence
  WHERE (origin = 'pipeline'::text);


--
-- Name: innovation; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.innovation AS
 SELECT area,
    area_ord,
    ord,
    t,
    mat,
    gap,
    driver,
    horizon,
    body,
    impact,
    "whatsNew",
    "compNote",
    action,
    sources,
    url,
    origin,
    updated_at
   FROM serving.innovation
  WHERE (origin = 'pipeline'::text);


--
-- Name: matchup; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.matchup AS
 SELECT matchup_id,
    cat,
    anchor,
    global,
    dir,
    country,
    comp,
    "compBy",
    bf,
    "bfBy",
    ks_thin,
    reason,
    edge,
    specs,
    "advComp",
    "advBf",
    det,
    "verdictH",
    verdict,
    "catKey",
    srcs,
    gen,
    origin,
    updated_at
   FROM serving.matchup
  WHERE (origin = 'pipeline'::text);


--
-- Name: partner; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.partner AS
 SELECT id,
    ord,
    label,
    kind,
    rel,
    sig,
    ptype,
    note,
    date,
    country,
    deal,
    insight,
    mean,
    src,
    srcnote,
    cid,
    origin,
    updated_at
   FROM serving.partner
  WHERE (origin = 'pipeline'::text);


--
-- Name: patent; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.patent AS
 SELECT ord,
    assignee_ord,
    no,
    title,
    assignee,
    status,
    filed,
    granted,
    country,
    ipc,
    abstract,
    area,
    threat,
    relev,
    url,
    p,
    origin,
    updated_at
   FROM serving.patent
  WHERE (origin = 'pipeline'::text);


--
-- Name: signal_card; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.signal_card AS
 SELECT id,
    lane,
    ord,
    dir,
    rank,
    title,
    meta,
    company,
    lens,
    sowhat,
    sec,
    url,
    ago,
    tags,
    origin,
    updated_at,
    image
   FROM serving.signal_card
  WHERE (origin = 'pipeline'::text);


--
-- Name: signal_detail; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.signal_detail AS
 SELECT id,
    ord,
    rank,
    dir,
    title,
    facts,
    what,
    why,
    lens,
    actions,
    url,
    suggest,
    kind,
    match,
    pursue,
    origin,
    updated_at
   FROM serving.signal_detail
  WHERE (origin = 'pipeline'::text);


--
-- Name: source_registry; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.source_registry AS
 SELECT ord,
    company,
    label,
    url,
    kind,
    origin,
    updated_at
   FROM serving.source_registry
  WHERE (origin = 'pipeline'::text);


--
-- Name: tender; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.tender AS
 SELECT id,
    ord,
    title,
    issuer,
    country,
    cat,
    value,
    qty,
    deadline,
    dl,
    "reqNote",
    req,
    matches,
    lean,
    "leanTxt",
    status,
    url,
    "urlKind",
    srcs,
    stage,
    origin,
    updated_at
   FROM serving.tender
  WHERE (origin = 'pipeline'::text);


--
-- Name: ui_config; Type: VIEW; Schema: serving_live; Owner: -
--

CREATE VIEW serving_live.ui_config AS
 SELECT key,
    value
   FROM serving.ui_config;


--
-- Name: stage_run id; Type: DEFAULT; Schema: metrics; Owner: -
--

ALTER TABLE ONLY metrics.stage_run ALTER COLUMN id SET DEFAULT nextval('metrics.stage_run_id_seq'::regclass);


--
-- Name: adhoc_job adhoc_job_pkey; Type: CONSTRAINT; Schema: metrics; Owner: -
--

ALTER TABLE ONLY metrics.adhoc_job
    ADD CONSTRAINT adhoc_job_pkey PRIMARY KEY (run_id);


--
-- Name: stage_order stage_order_pkey; Type: CONSTRAINT; Schema: metrics; Owner: -
--

ALTER TABLE ONLY metrics.stage_order
    ADD CONSTRAINT stage_order_pkey PRIMARY KEY (stage);


--
-- Name: stage_run stage_run_pkey; Type: CONSTRAINT; Schema: metrics; Owner: -
--

ALTER TABLE ONLY metrics.stage_run
    ADD CONSTRAINT stage_run_pkey PRIMARY KEY (id);


--
-- Name: adhoc_job_queue_idx; Type: INDEX; Schema: metrics; Owner: -
--

CREATE INDEX adhoc_job_queue_idx ON metrics.adhoc_job USING btree (status, submitted) WHERE (status = 'queued'::text);


--
-- Name: adhoc_job_recent_idx; Type: INDEX; Schema: metrics; Owner: -
--

CREATE INDEX adhoc_job_recent_idx ON metrics.adhoc_job USING btree (submitted DESC);


--
-- Name: stage_run_doc_idx; Type: INDEX; Schema: metrics; Owner: -
--

CREATE INDEX stage_run_doc_idx ON metrics.stage_run USING btree (doc_id) WHERE (doc_id IS NOT NULL);


--
-- Name: stage_run_run_idx; Type: INDEX; Schema: metrics; Owner: -
--

CREATE INDEX stage_run_run_idx ON metrics.stage_run USING btree (run_id);


--
-- Name: stage_run_stage_idx; Type: INDEX; Schema: metrics; Owner: -
--

CREATE INDEX stage_run_stage_idx ON metrics.stage_run USING btree (stage, started_at DESC);


--
-- PostgreSQL database dump complete
--

\unrestrict 3lxm77QqxCQ2Tz5sGz2j4Db6lFClYHEOBPik7hQKZbK80McPyKuKopCYBMztxFX

