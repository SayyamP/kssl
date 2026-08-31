-- ---------------------------------------------------------------------------
-- KSSL_Deploy: schema "extracted"
-- Port of the essentials of the live extraction store (parallax 127.0.0.1:5440,
-- schemas l2 + l4): document, span, proposition, span_value, prop_arg for
-- Layer A, entity + entity_alias for Layer B. Lookup/QA tables (span_type,
-- value_kind, audit, coverage, hole, sentence) are not ported; the demo
-- pipeline writes the core rows only.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS extracted;

-- Domains (same discipline as the l2 store).
CREATE DOMAIN extracted.char_offset AS integer CHECK (VALUE >= 0);
CREATE DOMAIN extracted.iso639 AS text CHECK (VALUE ~ '^[a-z]{2,3}(-[A-Za-z]{2,4})?$');
CREATE DOMAIN extracted.iso4217 AS character(3) CHECK (VALUE ~ '^[A-Z]{3}$');
CREATE DOMAIN extracted.sha256 AS character(64) CHECK (VALUE ~ '^[0-9a-f]{64}$');

-- One row per extraction run; span/proposition rows carry its id.
CREATE TABLE extracted.extraction_run (
    run_id           text PRIMARY KEY CHECK (run_id <> ''),
    started_at       timestamptz,
    pipeline_version text,
    lexicon_version  text,
    model            text,
    config           jsonb,
    note             text,
    loaded_at        timestamptz DEFAULT now()
);

CREATE TABLE extracted.document (
    document_id text PRIMARY KEY CHECK (document_id <> ''),
    url         text CHECK (url <> ''),
    source_id   text CHECK (source_id <> ''),
    language    extracted.iso639,
    title       text CHECK (title <> ''),
    text        text NOT NULL CHECK (text <> ''),
    text_sha256 extracted.sha256 NOT NULL,
    n_chars     integer NOT NULL CHECK (n_chars = length(text)),
    n_sentences integer,
    meta        jsonb,
    first_seen  timestamptz DEFAULT now()
);
CREATE INDEX document_source_idx   ON extracted.document (source_id);
CREATE INDEX document_language_idx ON extracted.document (language);

CREATE TABLE extracted.span (
    document_id text NOT NULL REFERENCES extracted.document (document_id) ON DELETE CASCADE,
    run_id      text NOT NULL REFERENCES extracted.extraction_run (run_id),
    span_id     text NOT NULL CHECK (span_id <> ''),
    start_c     extracted.char_offset NOT NULL,
    end_c       extracted.char_offset NOT NULL,
    text        text NOT NULL CHECK (text <> ''),
    type        text NOT NULL CHECK (type <> ''),
    type_ner    text CHECK (type_ner <> ''),
    gloss       text CHECK (gloss <> ''),
    in_article  text CHECK (in_article <> ''),
    source      text CHECK (source <> ''),
    score       real,
    sent        integer,
    PRIMARY KEY (document_id, run_id, span_id),
    CHECK (end_c::integer > start_c::integer)
);
CREATE INDEX span_type_idx ON extracted.span (type);
CREATE INDEX span_pos_idx  ON extracted.span (document_id, run_id, start_c, end_c);
CREATE INDEX span_text_idx ON extracted.span (lower(text));

CREATE TABLE extracted.proposition (
    document_id text NOT NULL REFERENCES extracted.document (document_id) ON DELETE CASCADE,
    run_id      text NOT NULL REFERENCES extracted.extraction_run (run_id),
    i           integer NOT NULL,
    subject     text NOT NULL CHECK (subject <> ''),
    predicate   text NOT NULL CHECK (predicate <> ''),
    object      text NOT NULL CHECK (object <> ''),
    time_txt    text CHECK (time_txt <> ''),
    place_txt   text CHECK (place_txt <> ''),
    polarity    text CHECK (polarity <> ''),
    modality    text CHECK (modality <> ''),
    ev_start    extracted.char_offset NOT NULL,
    ev_end      extracted.char_offset NOT NULL,
    ev_quote    text NOT NULL CHECK (ev_quote <> ''),
    ev_fragment boolean NOT NULL DEFAULT false,
    PRIMARY KEY (document_id, run_id, i),
    CHECK (ev_end::integer > ev_start::integer)
);
CREATE INDEX prop_subj_idx ON extracted.proposition (lower(subject));
CREATE INDEX prop_ev_idx   ON extracted.proposition (document_id, run_id, ev_start, ev_end);

-- Parsed value for a span (numbers, dates, money, ...).
CREATE TABLE extracted.span_value (
    document_id    text NOT NULL,
    run_id         text NOT NULL,
    span_id        text NOT NULL,
    parser_version text NOT NULL,
    status         text NOT NULL CHECK (status IN ('parsed', 'not_a_value', 'failed')),
    kind           text,
    num            numrange,
    dt             daterange,
    unit           text,
    unit_raw       text,
    currency       extracted.iso4217,
    qualifier      text CHECK (qualifier IN ('exact', 'approx', 'min', 'max', 'range', 'relative')),
    "precision"    text CHECK ("precision" IN ('day', 'month', 'quarter', 'year', 'decade')),
    val_text       text,
    extra          jsonb,
    note           text,
    PRIMARY KEY (document_id, run_id, span_id),
    FOREIGN KEY (document_id, run_id, span_id)
        REFERENCES extracted.span (document_id, run_id, span_id) ON DELETE CASCADE,
    CHECK (status <> 'parsed' OR kind IS NOT NULL)
);
CREATE INDEX span_value_kind_idx ON extracted.span_value (kind, status);
CREATE INDEX span_value_num_idx  ON extracted.span_value USING gist (num) WHERE status = 'parsed';
CREATE INDEX span_value_dt_idx   ON extracted.span_value USING gist (dt) WHERE status = 'parsed';

-- Grounding of a proposition argument to a span.
CREATE TABLE extracted.prop_arg (
    document_id text NOT NULL,
    run_id      text NOT NULL,
    prop_i      integer NOT NULL,
    role        text NOT NULL CHECK (role IN ('subject', 'object', 'time', 'place')),
    span_id     text,
    method      text NOT NULL CHECK (method IN ('exact', 'in_evidence', 'outside_evidence', 'paraphrase')),
    arg_text    text NOT NULL,
    PRIMARY KEY (document_id, run_id, prop_i, role),
    FOREIGN KEY (document_id, run_id, prop_i)
        REFERENCES extracted.proposition (document_id, run_id, i) ON DELETE CASCADE,
    FOREIGN KEY (document_id, run_id, span_id)
        REFERENCES extracted.span (document_id, run_id, span_id) ON DELETE CASCADE,
    CHECK ((span_id IS NULL) = (method <> 'exact'))
);
CREATE INDEX prop_arg_span_idx ON extracted.prop_arg (document_id, run_id, span_id);

-- Layer B: canonical entities + surface aliases (port of l4.entity / l4.entity_alias;
-- entity_type is free text here, the l2.span_type lookup is not ported).
CREATE TABLE extracted.entity (
    -- engine-issued id (e.g. 'Ececc...'), not generated here. The comma belongs
    -- BEFORE the comment: with it at the end of the comment text it was commented
    -- out too, and the whole file died with "syntax error at or near entity_type".
    entity_id      text PRIMARY KEY,
    entity_type    text NOT NULL CHECK (entity_type <> ''),
    canonical_name text NOT NULL CHECK (canonical_name <> ''),
    canonical_lang extracted.iso639,
    ont_node_id    text,
    ont_version    text,
    redirects_to   text REFERENCES extracted.entity (entity_id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by_run text NOT NULL,
    CHECK (redirects_to IS DISTINCT FROM entity_id)
);
CREATE INDEX entity_type_idx ON extracted.entity (entity_type);
CREATE INDEX entity_live_idx ON extracted.entity (entity_id) WHERE redirects_to IS NULL;

CREATE TABLE extracted.entity_alias (
    entity_id      text NOT NULL REFERENCES extracted.entity (entity_id) ON DELETE CASCADE,
    surface        text NOT NULL CHECK (surface <> ''),
    surface_folded text NOT NULL CHECK (surface_folded <> ''),
    lang           extracted.iso639 NOT NULL,
    script         text NOT NULL,
    alias_kind     text NOT NULL CHECK (alias_kind IN
        ('name', 'legal_variant', 'abbreviation', 'transliteration',
         'translation', 'misspelling', 'former_name')),
    n_mentions     integer NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, surface_folded, lang)
);
CREATE INDEX entity_alias_folded_idx ON extracted.entity_alias (surface_folded);
