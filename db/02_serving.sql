-- ---------------------------------------------------------------------------
-- KSSL_Deploy: schema "serving"
-- Tables that DIRECTLY power the UI. Column names follow the dataset field
-- names in contract_shapes.json (camelCase columns are quoted) so the API
-- assembly is mechanical. Arrays the UI consumes as arrays (lens pairs,
-- facts pairs, matchup spec rows, tender matches, ...) are JSONB columns.
--
-- Every pipeline-writable table carries:
--   origin      'reference' (seeded from reference_dataset.json) or 'pipeline'
--   updated_at  last write
-- Ordering columns (ord, comp_ord, ...) preserve the reference display order;
-- the API emits rows in that order.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS serving;

-- Interface vocabulary (CAT_KEY, POS_CATS, FIELDSYN, REL_LABEL, actLabel,
-- chatSuggest, client, overviewConfig, ...): describes the interface, not the
-- world. The pipeline never writes this table.
CREATE TABLE serving.ui_config (
    key   text NOT NULL,
    value jsonb NOT NULL,
    CONSTRAINT ui_config_key_uniq UNIQUE (key)
);

-- Global: competitors (dict keyed by comp id; compOrder is derived from ord).
CREATE TABLE serving.competitors (
    comp_id      text PRIMARY KEY,
    ord          integer NOT NULL,
    name         text NOT NULL,
    dir          text,
    sector       text,
    hq           text,
    threat       text,
    assess       text,
    updates      jsonb,          -- mixed type in the reference: string OR empty list
    center       jsonb,
    partners     jsonb,
    site         text,
    srcs         jsonb,
    products     jsonb,
    "threatNote" text,
    leadership   jsonb,
    facilities   jsonb,
    sales        jsonb,
    -- 2026-09-01. Profile-page facts the corpus can source; before these the page
    -- invented a founding year, a headcount and a revenue line in their place.
    starting_year         integer,
    global_locations      jsonb,
    company_size          text,
    strategic_positioning text,
    origin       text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Per-company news for the Profile / Products / Geo panels. Every row is a signal
-- card the pipeline already produced, dated from the article's own markup and cited;
-- fill_competitor_news.py is the writer. `is_trending` is never set true -- nothing
-- here measures trend, and the UI's top slot is served by the newest row.
--
-- The FK cascades, which is why an ALTER on this table must not run while an enrich
-- pass is mid-transaction: step_companies deletes every pipeline competitor row and
-- then spends minutes on LLM calls before committing, holding a lock on this table
-- for the duration. See db/migrations/2026-09-02_competitor_news_writer.sql.
CREATE TABLE serving.competitor_news (
    id             bigserial PRIMARY KEY,
    comp_id        text NOT NULL REFERENCES serving.competitors(comp_id) ON DELETE CASCADE,
    title          text NOT NULL,
    description    text,
    source         text,
    published_date timestamptz,
    category       text,
    is_trending    boolean NOT NULL DEFAULT false,
    url            text,
    image          text,
    origin         text NOT NULL DEFAULT 'pipeline',
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX competitor_news_comp_idx ON serving.competitor_news (comp_id, published_date DESC);
CREATE INDEX competitor_news_trending_idx ON serving.competitor_news (is_trending, published_date DESC)
    WHERE is_trending;

-- Globals: competitiveCards / marketCards / techCards — one table, lane column.
-- market-lane cards have no company/lens/sec/url; those stay NULL and the API
-- omits them.
CREATE TABLE serving.signal_card (
    id         text PRIMARY KEY,
    lane       text NOT NULL CHECK (lane IN ('competitive', 'market', 'tech')),
    ord        integer NOT NULL,
    dir        text,
    rank       text,
    title      text NOT NULL,
    meta       text,
    company    text,
    lens       text,
    sowhat     text,
    sec        jsonb,
    url        text,
    ago        text,
    tags       text,
    image      text,           -- the article's own picture, resolved from page markup
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signal_card_lane_idx ON serving.signal_card (lane, ord);

-- Global: details (dict keyed by card id).
CREATE TABLE serving.signal_detail (
    id         text PRIMARY KEY,
    ord        integer NOT NULL,
    rank       text,
    dir        text,
    title      text NOT NULL,
    facts      jsonb,
    what       text,
    why        text,
    lens       jsonb,
    actions    jsonb,
    url        text,
    suggest    jsonb,
    kind       text,
    match      jsonb,
    pursue     jsonb,
    image      text,           -- the article's own picture, same value as signal_card.image
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Global: matchups (dict keyed by numeric-string id, emitted in id order).
-- edge is honestly nullable (75 reference rows have edge: null).
CREATE TABLE serving.matchup (
    matchup_id integer PRIMARY KEY,
    cat        text NOT NULL,
    anchor     text,
    "global"   boolean,
    dir        text,
    country    text,
    comp       text,
    "compBy"   text,
    bf         text,
    "bfBy"     text,
    ks_thin    boolean,
    reason     text,
    edge       integer,
    specs      jsonb,
    "advComp"  jsonb,
    "advBf"    jsonb,
    det        jsonb,
    "verdictH" text,
    verdict    text,
    "catKey"   text,
    srcs       jsonb,
    gen        boolean,
    revenue_filter text,
    news_image     text,
    product_news   jsonb,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX matchup_catkey_idx ON serving.matchup ("catKey");

-- Global: tenders (list).
--
-- `id` is text, not integer: fetch_tenders.py writes a source-prefixed stable id
-- ("ted-2026-…") so a tender keeps its identity across refreshes. It converted the
-- column in place at runtime (fetch_tenders.py, one-time ALTER) and this file was
-- never updated to match -- the drift db/schema_snapshot.txt exists to catch.
CREATE TABLE serving.tender (
    id         text PRIMARY KEY,
    ord        integer NOT NULL,
    title      text NOT NULL,
    issuer     text,
    country    text,
    cat        text,
    "value"    text,
    qty        text,
    deadline   text,
    dl         integer,
    "reqNote"  text,
    req        jsonb,
    matches    jsonb,
    lean       text,
    "leanTxt"  text,
    status     text,
    url        text,
    "urlKind"  text,
    srcs       jsonb,
    stage      text,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tender_cat_idx ON serving.tender (cat);

-- Global: PATENTS — stored FLAT, one row per patent. byArea / byAssignee are
-- rollups the API computes: byArea groups rows in ord order, byAssignee in
-- assignee_ord order (the reference dataset orders the two views differently).
-- PATENTS.techAreas and PATENTS._meta live in ui_config.
CREATE TABLE serving.patent (
    ord          integer PRIMARY KEY,
    assignee_ord integer NOT NULL,
    "no"         text NOT NULL UNIQUE,
    title        text,
    assignee     text NOT NULL,
    status       text,
    filed        text,
    granted      text,           -- honestly nullable (16 reference rows)
    country      text,
    ipc          jsonb,
    abstract     text,
    area         text NOT NULL,
    threat       text,
    relev        text,
    url          text,
    p            text,
    origin       text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX patent_area_idx     ON serving.patent (area);
CREATE INDEX patent_assignee_idx ON serving.patent (assignee);

-- Global: geoData (dict comp -> dict country -> list of presence entries).
CREATE TABLE serving.geo_presence (
    comp_id     text NOT NULL,
    comp_ord    integer NOT NULL,
    country     text NOT NULL,
    country_ord integer NOT NULL,
    ord         integer NOT NULL,
    name        text NOT NULL,
    c           text,
    val         text,
    since       text,
    qty         text,
    stage       text,
    note        text,
    src         text,
    srcnote     text,
    geo_news    jsonb,
    origin      text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (comp_id, country, ord)
);
CREATE INDEX geo_presence_comp_idx ON serving.geo_presence (comp_id);

-- Global: geoComps (list of companies shown on the geo tab, incl. KSSL).
CREATE TABLE serving.geo_comp (
    id         text PRIMARY KEY,
    ord        integer NOT NULL,
    name       text NOT NULL,
    dir        text,
    hq         text,
    "isBf"     boolean,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Global: innovations (dict area -> list of items).
CREATE TABLE serving.innovation (
    area        text NOT NULL,
    area_ord    integer NOT NULL,
    ord         integer NOT NULL,
    t           text NOT NULL,
    mat         text,
    gap         text,
    driver      text,
    horizon     text,
    body        text,
    impact      text,
    "whatsNew"  text,
    "compNote"  text,
    action      text,
    sources     text,
    url         text,
    origin      text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area, ord)
);

-- Global: KSSL_PARTNERS (list).
CREATE TABLE serving.partner (
    id         text PRIMARY KEY,
    ord        integer NOT NULL,
    label      text NOT NULL,
    kind       text,
    rel        text,
    sig        integer,
    ptype      text,
    note       text,
    date       text,
    country    text,
    deal       text,
    insight    text,
    mean       text,
    src        text,
    srcnote    text,
    cid        text,
    image      text,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Global: sourceRegistry (list).
CREATE TABLE serving.source_registry (
    ord        integer PRIMARY KEY,
    company    text NOT NULL,
    label      text,
    url        text NOT NULL,
    kind       text,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Global: companySources (dict company -> list of urls).
CREATE TABLE serving.company_source (
    company    text NOT NULL,
    comp_ord   integer NOT NULL,
    ord        integer NOT NULL,
    url        text NOT NULL,
    origin     text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company, ord)
);

-- NOT IN THIS FILE, ON PURPOSE. Two serving tables are created by the process that
-- owns them, with CREATE TABLE IF NOT EXISTS at startup, and never by a migration:
--
--   serving.card        extraction/engine/card_writer.py  (`card_writer.py --init`)
--   serving.signal_seen extraction/signals/serving_fill.py
--
-- Neither is served to the UI, so neither has a serving_live view. Listing them here
-- as well would give each two owners and a drift of its own.
