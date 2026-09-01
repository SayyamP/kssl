--
-- PostgreSQL database dump
--

\restrict CsgAsDxtwDbdJmQRdhddFfJUYx3ZhMyWTzvdzwExitbdiWQcrN4fHdxj3d1E4kT

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
-- Name: extracted; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA extracted;


--
-- Name: serving; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA serving;


--
-- Name: char_offset; Type: DOMAIN; Schema: extracted; Owner: -
--

CREATE DOMAIN extracted.char_offset AS integer
	CONSTRAINT char_offset_check CHECK ((VALUE >= 0));


--
-- Name: iso4217; Type: DOMAIN; Schema: extracted; Owner: -
--

CREATE DOMAIN extracted.iso4217 AS character(3)
	CONSTRAINT iso4217_check CHECK ((VALUE ~ '^[A-Z]{3}$'::text));


--
-- Name: iso639; Type: DOMAIN; Schema: extracted; Owner: -
--

CREATE DOMAIN extracted.iso639 AS text
	CONSTRAINT iso639_check CHECK ((VALUE ~ '^[a-z]{2,3}(-[A-Za-z]{2,4})?$'::text));


--
-- Name: sha256; Type: DOMAIN; Schema: extracted; Owner: -
--

CREATE DOMAIN extracted.sha256 AS character(64)
	CONSTRAINT sha256_check CHECK ((VALUE ~ '^[0-9a-f]{64}$'::text));


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: document; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.document (
    document_id text NOT NULL,
    url text,
    source_id text,
    language extracted.iso639,
    title text,
    text text NOT NULL,
    text_sha256 extracted.sha256 NOT NULL,
    n_chars integer NOT NULL,
    n_sentences integer,
    meta jsonb,
    first_seen timestamp with time zone DEFAULT now(),
    CONSTRAINT document_check CHECK ((n_chars = length(text))),
    CONSTRAINT document_document_id_check CHECK ((document_id <> ''::text)),
    CONSTRAINT document_source_id_check CHECK ((source_id <> ''::text)),
    CONSTRAINT document_text_check CHECK ((text <> ''::text)),
    CONSTRAINT document_title_check CHECK ((title <> ''::text)),
    CONSTRAINT document_url_check CHECK ((url <> ''::text))
);


--
-- Name: COLUMN document.document_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.document_id IS 'Stable id, sha256 of the URL truncated to 16 hex chars. The same page fetched twice keeps one id.';


--
-- Name: COLUMN document.url; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.url IS 'Final URL after redirects, as fetched.';


--
-- Name: COLUMN document.source_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.source_id IS 'Publisher host with any leading www. stripped -- the outlet, used for corroboration counting.';


--
-- Name: COLUMN document.language; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.language IS 'ISO code from the extraction pipeline''s own detector, never a second library: two detectors disagreeing about Persian and Arabic is a bug already paid for once.';


--
-- Name: COLUMN document.title; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.title IS 'Headline as published.';


--
-- Name: COLUMN document.text; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.text IS 'Body text after boilerplate removal. All span offsets index into THIS string, so it must never be re-normalised in place.';


--
-- Name: COLUMN document.text_sha256; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.text_sha256 IS 'Hash of text. Two addresses with identical bodies are one syndicated story, not two independent witnesses.';


--
-- Name: COLUMN document.n_chars; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.n_chars IS 'Length of text in characters; the denominator for coverage.';


--
-- Name: COLUMN document.n_sentences; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.n_sentences IS 'Sentence count from segmentation.';


--
-- Name: COLUMN document.meta; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.meta IS 'Provenance blob: which set (kssl/parallax/kssl_demo), how it was found, when fetched.';


--
-- Name: COLUMN document.first_seen; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.document.first_seen IS 'When this document first entered the store; NOT the publication date, which is derived from the document''s own Date spans.';


--
-- Name: entity; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.entity (
    entity_id text NOT NULL,
    entity_type text NOT NULL,
    canonical_name text NOT NULL,
    canonical_lang extracted.iso639,
    ont_node_id text,
    ont_version text,
    redirects_to text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by_run text NOT NULL,
    CONSTRAINT entity_canonical_name_check CHECK ((canonical_name <> ''::text)),
    CONSTRAINT entity_check CHECK ((redirects_to IS DISTINCT FROM entity_id)),
    CONSTRAINT entity_entity_type_check CHECK ((entity_type <> ''::text))
);


--
-- Name: COLUMN entity.entity_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.entity_id IS 'Layer B identity. Hashed from surface AND type, because the same string as an Organization and as a Product are different things.';


--
-- Name: COLUMN entity.entity_type; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.entity_type IS 'Organization, Product, Platform, WeaponSystem, Technology, Program, Facility, Material, Equipment.';


--
-- Name: COLUMN entity.canonical_name; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.canonical_name IS 'The spelling chosen to represent the group of aliases.';


--
-- Name: COLUMN entity.canonical_lang; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.canonical_lang IS 'Language of the canonical spelling.';


--
-- Name: COLUMN entity.ont_node_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.ont_node_id IS 'Ontology sector node this entity classifies to (l2/ontology/ontology.yaml). NULL means unclassified -- the open slot, counted and reported, never force-fitted.';


--
-- Name: COLUMN entity.ont_version; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.ont_version IS 'Ontology semver in force when the classification was made, so a taxonomy change is a re-classification job and not a silent reinterpretation.';


--
-- Name: COLUMN entity.redirects_to; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.redirects_to IS 'Set when this entity was merged into another; the row survives so old references still resolve.';


--
-- Name: COLUMN entity.created_at; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.created_at IS 'When the entity was first created.';


--
-- Name: COLUMN entity.created_by_run; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity.created_by_run IS 'Extraction run that created it; joins extraction_run.';


--
-- Name: entity_alias; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.entity_alias (
    entity_id text NOT NULL,
    surface text NOT NULL,
    surface_folded text NOT NULL,
    lang extracted.iso639 NOT NULL,
    script text NOT NULL,
    alias_kind text NOT NULL,
    n_mentions integer DEFAULT 0 NOT NULL,
    CONSTRAINT entity_alias_alias_kind_check CHECK ((alias_kind = ANY (ARRAY['name'::text, 'legal_variant'::text, 'abbreviation'::text, 'transliteration'::text, 'translation'::text, 'misspelling'::text, 'former_name'::text]))),
    CONSTRAINT entity_alias_surface_check CHECK ((surface <> ''::text)),
    CONSTRAINT entity_alias_surface_folded_check CHECK ((surface_folded <> ''::text))
);


--
-- Name: COLUMN entity_alias.entity_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.entity_id IS 'Entity this spelling belongs to.';


--
-- Name: COLUMN entity_alias.surface; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.surface IS 'The spelling exactly as it appeared in a document.';


--
-- Name: COLUMN entity_alias.surface_folded; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.surface_folded IS 'Accent-stripped, case-folded form for matching. Decompose, strip, then recompose NFC -- NFKD alone shatters Hangul into Jamo.';


--
-- Name: COLUMN entity_alias.lang; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.lang IS 'Language the spelling occurred in.';


--
-- Name: COLUMN entity_alias.script; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.script IS 'Writing system. Cross-script pairs are never auto-merged whatever they score: six Russian outlets once matched at similarity 1.00 because they share a gloss, not an identity.';


--
-- Name: COLUMN entity_alias.alias_kind; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.alias_kind IS 'Closed set: name, abbreviation, translit, former. Not free text.';


--
-- Name: COLUMN entity_alias.n_mentions; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.entity_alias.n_mentions IS 'How often this spelling occurred. A count of spellings, not of companies, until identity hygiene has run.';


--
-- Name: extraction_run; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.extraction_run (
    run_id text NOT NULL,
    started_at timestamp with time zone,
    pipeline_version text,
    lexicon_version text,
    model text,
    config jsonb,
    note text,
    loaded_at timestamp with time zone DEFAULT now(),
    CONSTRAINT extraction_run_run_id_check CHECK ((run_id <> ''::text))
);


--
-- Name: COLUMN extraction_run.run_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.run_id IS 'One extraction pass. Every span and statement carries it, so a bad run can be isolated.';


--
-- Name: COLUMN extraction_run.started_at; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.started_at IS 'When the run began.';


--
-- Name: COLUMN extraction_run.pipeline_version; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.pipeline_version IS 'Git revision of the extraction code.';


--
-- Name: COLUMN extraction_run.lexicon_version; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.lexicon_version IS 'Hash of the term lexicon used; a lexicon change alters span typing.';


--
-- Name: COLUMN extraction_run.model; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.model IS 'Extractor model and digest (e.g. qwen2.5:7b + GLiNER).';


--
-- Name: COLUMN extraction_run.config; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.config IS 'Run settings: workers, context, thresholds.';


--
-- Name: COLUMN extraction_run.note; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.note IS 'Free-text label for the run.';


--
-- Name: COLUMN extraction_run.loaded_at; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.extraction_run.loaded_at IS 'When the run was loaded into Postgres from the engine''s SQLite store.';


--
-- Name: prop_arg; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.prop_arg (
    document_id text NOT NULL,
    run_id text NOT NULL,
    prop_i integer NOT NULL,
    role text NOT NULL,
    span_id text,
    method text NOT NULL,
    arg_text text NOT NULL,
    CONSTRAINT prop_arg_check CHECK (((span_id IS NULL) = (method <> 'exact'::text))),
    CONSTRAINT prop_arg_method_check CHECK ((method = ANY (ARRAY['exact'::text, 'in_evidence'::text, 'outside_evidence'::text, 'paraphrase'::text]))),
    CONSTRAINT prop_arg_role_check CHECK ((role = ANY (ARRAY['subject'::text, 'object'::text, 'time'::text, 'place'::text])))
);


--
-- Name: COLUMN prop_arg.document_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.document_id IS 'Document the statement belongs to.';


--
-- Name: COLUMN prop_arg.run_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.run_id IS 'Extraction run.';


--
-- Name: COLUMN prop_arg.prop_i; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.prop_i IS 'Which statement in the document this argument belongs to.';


--
-- Name: COLUMN prop_arg.role; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.role IS 'Which slot the span fills: subject, object, time, place.';


--
-- Name: COLUMN prop_arg.span_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.span_id IS 'The span filling the slot. This is what ties a statement to exact character offsets.';


--
-- Name: COLUMN prop_arg.method; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.method IS 'How the link was made: exact match, offset overlap, or model.';


--
-- Name: COLUMN prop_arg.arg_text; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.prop_arg.arg_text IS 'Text of the argument as the statement phrased it.';


--
-- Name: proposition; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.proposition (
    document_id text NOT NULL,
    run_id text NOT NULL,
    i integer NOT NULL,
    subject text NOT NULL,
    predicate text NOT NULL,
    object text NOT NULL,
    time_txt text,
    place_txt text,
    polarity text,
    modality text,
    ev_start extracted.char_offset NOT NULL,
    ev_end extracted.char_offset NOT NULL,
    ev_quote text NOT NULL,
    ev_fragment boolean DEFAULT false NOT NULL,
    CONSTRAINT proposition_check CHECK (((ev_end)::integer > (ev_start)::integer)),
    CONSTRAINT proposition_ev_quote_check CHECK ((ev_quote <> ''::text)),
    CONSTRAINT proposition_modality_check CHECK ((modality <> ''::text)),
    CONSTRAINT proposition_object_check CHECK ((object <> ''::text)),
    CONSTRAINT proposition_place_txt_check CHECK ((place_txt <> ''::text)),
    CONSTRAINT proposition_polarity_check CHECK ((polarity <> ''::text)),
    CONSTRAINT proposition_predicate_check CHECK ((predicate <> ''::text)),
    CONSTRAINT proposition_subject_check CHECK ((subject <> ''::text)),
    CONSTRAINT proposition_time_txt_check CHECK ((time_txt <> ''::text))
);


--
-- Name: COLUMN proposition.document_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.document_id IS 'Document the statement came from.';


--
-- Name: COLUMN proposition.run_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.run_id IS 'Extraction run that produced it.';


--
-- Name: COLUMN proposition.i; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.i IS 'Position of the statement within the document.';


--
-- Name: COLUMN proposition.subject; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.subject IS 'Who or what the statement is about, as written.';


--
-- Name: COLUMN proposition.predicate; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.predicate IS 'The relation, as the source phrased it -- free text, not a controlled vocabulary. 4,963 distinct surfaces over 17k rows; mapping these onto the ontology''s closed predicates is an unbuilt join.';


--
-- Name: COLUMN proposition.object; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.object IS 'What the subject is related to, as written.';


--
-- Name: COLUMN proposition.time_txt; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.time_txt IS 'Time expression as written, unparsed.';


--
-- Name: COLUMN proposition.place_txt; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.place_txt IS 'Place expression as written, unparsed.';


--
-- Name: COLUMN proposition.polarity; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.polarity IS 'Asserted or negated. A negated statement claims the opposite, so this may never be ignored.';


--
-- Name: COLUMN proposition.modality; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.modality IS 'How strongly it is claimed: asserted, planned, reported, hypothetical. "Plans to deliver" is not "delivered".';


--
-- Name: COLUMN proposition.ev_start; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.ev_start IS 'Start offset of the evidence sentence in document.text.';


--
-- Name: COLUMN proposition.ev_end; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.ev_end IS 'End offset of the evidence sentence.';


--
-- Name: COLUMN proposition.ev_quote; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.ev_quote IS 'The sentence the statement was read from. Existence of a quote is not entailment: it must actually support the claim.';


--
-- Name: COLUMN proposition.ev_fragment; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.proposition.ev_fragment IS 'True when the evidence is a fragment rather than a whole sentence.';


--
-- Name: span; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.span (
    document_id text NOT NULL,
    run_id text NOT NULL,
    span_id text NOT NULL,
    start_c extracted.char_offset NOT NULL,
    end_c extracted.char_offset NOT NULL,
    text text NOT NULL,
    type text NOT NULL,
    type_ner text,
    gloss text,
    in_article text,
    source text,
    score real,
    sent integer,
    CONSTRAINT span_check CHECK (((end_c)::integer > (start_c)::integer)),
    CONSTRAINT span_gloss_check CHECK ((gloss <> ''::text)),
    CONSTRAINT span_in_article_check CHECK ((in_article <> ''::text)),
    CONSTRAINT span_source_check CHECK ((source <> ''::text)),
    CONSTRAINT span_span_id_check CHECK ((span_id <> ''::text)),
    CONSTRAINT span_text_check CHECK ((text <> ''::text)),
    CONSTRAINT span_type_check CHECK ((type <> ''::text)),
    CONSTRAINT span_type_ner_check CHECK ((type_ner <> ''::text))
);


--
-- Name: COLUMN span.document_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.document_id IS 'Document the span is cut from.';


--
-- Name: COLUMN span.run_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.run_id IS 'Extraction run that produced it.';


--
-- Name: COLUMN span.span_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.span_id IS 'Id unique within the document.';


--
-- Name: COLUMN span.start_c; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.start_c IS 'Start character offset into document.text, inclusive.';


--
-- Name: COLUMN span.end_c; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.end_c IS 'End character offset, exclusive. The load step refuses any document where text[start_c:end_c] != text -- a repaired offset would be an invented quote.';


--
-- Name: COLUMN span.text; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.text IS 'The exact substring. Must equal document.text[start_c:end_c].';


--
-- Name: COLUMN span.type; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.type IS 'Semantic type: Organization, Country, Date, Measure, WeaponSystem, Concept, Action and so on.';


--
-- Name: COLUMN span.type_ner; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.type_ner IS 'Raw label from the NER model before reconciliation.';


--
-- Name: COLUMN span.gloss; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.gloss IS 'Short description of what the span refers to. Answers "same kind of thing", never "same thing".';


--
-- Name: COLUMN span.in_article; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.in_article IS 'Whether the span sits in article body or in navigation/boilerplate.';


--
-- Name: COLUMN span.source; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.source IS 'Which component proposed it: the model, the lexicon, or a rule.';


--
-- Name: COLUMN span.score; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.score IS 'Extractor confidence, where the component supplies one.';


--
-- Name: COLUMN span.sent; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span.sent IS 'Index of the sentence containing the span.';


--
-- Name: span_value; Type: TABLE; Schema: extracted; Owner: -
--

CREATE TABLE extracted.span_value (
    document_id text NOT NULL,
    run_id text NOT NULL,
    span_id text NOT NULL,
    parser_version text NOT NULL,
    status text NOT NULL,
    kind text,
    num numrange,
    dt daterange,
    unit text,
    unit_raw text,
    currency extracted.iso4217,
    qualifier text,
    "precision" text,
    val_text text,
    extra jsonb,
    note text,
    CONSTRAINT span_value_check CHECK (((status <> 'parsed'::text) OR (kind IS NOT NULL))),
    CONSTRAINT span_value_precision_check CHECK (("precision" = ANY (ARRAY['day'::text, 'month'::text, 'quarter'::text, 'year'::text, 'decade'::text]))),
    CONSTRAINT span_value_qualifier_check CHECK ((qualifier = ANY (ARRAY['exact'::text, 'approx'::text, 'min'::text, 'max'::text, 'range'::text, 'relative'::text]))),
    CONSTRAINT span_value_status_check CHECK ((status = ANY (ARRAY['parsed'::text, 'not_a_value'::text, 'failed'::text])))
);


--
-- Name: COLUMN span_value.document_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.document_id IS 'Document the measured span belongs to.';


--
-- Name: COLUMN span_value.run_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.run_id IS 'Extraction run.';


--
-- Name: COLUMN span_value.span_id; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.span_id IS 'The Measure/Date/Count span this value was parsed from.';


--
-- Name: COLUMN span_value.parser_version; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.parser_version IS 'Value parser version; a reparse is a new version, not an edit.';


--
-- Name: COLUMN span_value.status; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.status IS 'parsed, ambiguous or refused. Refused is a recorded outcome, not a gap.';


--
-- Name: COLUMN span_value.kind; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.kind IS 'What kind of quantity: length, mass, money, count, date, speed, power.';


--
-- Name: COLUMN span_value.num; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.num IS 'Numeric value as a RANGE, so "24-30 km" and "over 40" stay honest instead of collapsing to a point.';


--
-- Name: COLUMN span_value.dt; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.dt IS 'Date value as a range, for the same reason: "2026" is a year, not a day.';


--
-- Name: COLUMN span_value.unit; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.unit IS 'SI unit after normalisation. Two values may only be compared when their dimensions match.';


--
-- Name: COLUMN span_value.unit_raw; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.unit_raw IS 'Unit exactly as written in the source.';


--
-- Name: COLUMN span_value.currency; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.currency IS 'ISO currency code where the value is money.';


--
-- Name: COLUMN span_value.qualifier; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.qualifier IS 'Hedge attached to the number: about, up to, more than, at least.';


--
-- Name: COLUMN span_value."precision"; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value."precision" IS 'How exact the source was: exact, rounded, approximate.';


--
-- Name: COLUMN span_value.val_text; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.val_text IS 'The original text of the value, kept so the parse can always be audited against it.';


--
-- Name: COLUMN span_value.extra; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.extra IS 'Parser detail that does not fit a column.';


--
-- Name: COLUMN span_value.note; Type: COMMENT; Schema: extracted; Owner: -
--

COMMENT ON COLUMN extracted.span_value.note IS 'Why a value was refused or marked ambiguous.';


--
-- Name: card; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.card (
    document_id text NOT NULL,
    run_id text NOT NULL,
    title text,
    source_id text,
    language text,
    url text,
    n_chars integer NOT NULL,
    n_spans integer NOT NULL,
    n_props integer NOT NULL,
    card_text text NOT NULL,
    spans jsonb NOT NULL,
    statements jsonb NOT NULL,
    built_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: company_source; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.company_source (
    company text NOT NULL,
    comp_ord integer NOT NULL,
    ord integer NOT NULL,
    url text NOT NULL,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT company_source_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN company_source.company; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.company IS 'Company the source belongs to, by display name so it joins the roster.';


--
-- Name: COLUMN company_source.comp_ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.comp_ord IS 'Sort position of the company.';


--
-- Name: COLUMN company_source.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.ord IS 'Sort position of the source.';


--
-- Name: COLUMN company_source.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.url IS 'The source document.';


--
-- Name: COLUMN company_source.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.origin IS 'pipeline or reference.';


--
-- Name: COLUMN company_source.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.company_source.updated_at IS 'When the row was last written.';


--
-- Name: competitors; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.competitors (
    comp_id text NOT NULL,
    ord integer NOT NULL,
    name text NOT NULL,
    dir text,
    sector text,
    hq text,
    threat text,
    assess text,
    updates jsonb,
    center jsonb,
    partners jsonb,
    site text,
    srcs jsonb,
    products jsonb,
    "threatNote" text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    leadership jsonb,
    facilities jsonb,
    sales jsonb,
    CONSTRAINT competitors_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN competitors.comp_id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.comp_id IS 'Slug identity for the company, shared across serving tables.';


--
-- Name: COLUMN competitors.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.ord IS 'Sort position in the roster; pipeline rows start at 1001 so reference rows keep the low range.';


--
-- Name: COLUMN competitors.name; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.name IS 'Display name, canonicalised. Never a bare country and never two organisations joined by a conjunction.';


--
-- Name: COLUMN competitors.dir; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.dir IS 'rival, client or other. The client group is never a rival.';


--
-- Name: COLUMN competitors.sector; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.sector IS 'What the company sells. Refused when it merely echoes the prompt''s own portfolio list back.';


--
-- Name: COLUMN competitors.hq; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.hq IS 'Headquarters country.';


--
-- Name: COLUMN competitors.threat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.threat IS 'high, medium or low -- derived from countable inputs, not asserted by a model. NULL when nothing measurable places the company in a KSSL category.';


--
-- Name: COLUMN competitors.assess; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.assess IS 'Prose assessment. Every sentence must be traceable to the company''s own extracted statements; a row with no surviving sentence is refused.';


--
-- Name: COLUMN competitors.updates; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.updates IS 'Recent moves. Listing pages and careers pages are filtered out.';


--
-- Name: COLUMN competitors.center; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.center IS 'Map centre for the company view.';


--
-- Name: COLUMN competitors.partners; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.partners IS 'Named partners.';


--
-- Name: COLUMN competitors.site; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.site IS 'Official website.';


--
-- Name: COLUMN competitors.srcs; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.srcs IS 'Documents the profile was built from.';


--
-- Name: COLUMN competitors.products; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.products IS 'Named products. Generic nouns are not product names.';


--
-- Name: COLUMN competitors."threatNote"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors."threatNote" IS 'The measurement behind the threat rating, stated so the rating can be checked.';


--
-- Name: COLUMN competitors.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.origin IS 'pipeline or reference.';


--
-- Name: COLUMN competitors.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.competitors.updated_at IS 'When the row was last written.';


--
-- Name: geo_comp; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.geo_comp (
    id text NOT NULL,
    ord integer NOT NULL,
    name text NOT NULL,
    dir text,
    hq text,
    "isBf" boolean,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT geo_comp_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN geo_comp.id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.id IS 'Company id, matching geo_presence.comp_id.';


--
-- Name: COLUMN geo_comp.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.ord IS 'Sort position.';


--
-- Name: COLUMN geo_comp.name; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.name IS 'Display name.';


--
-- Name: COLUMN geo_comp.dir; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.dir IS 'rival, client or other.';


--
-- Name: COLUMN geo_comp.hq; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.hq IS 'Headquarters country.';


--
-- Name: COLUMN geo_comp."isBf"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp."isBf" IS 'True for the client group (Kalyani / KSSL / Bharat Forge), which is never rendered as a rival.';


--
-- Name: COLUMN geo_comp.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.origin IS 'pipeline or reference.';


--
-- Name: COLUMN geo_comp.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_comp.updated_at IS 'When the row was last written.';


--
-- Name: geo_presence; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.geo_presence (
    comp_id text NOT NULL,
    comp_ord integer NOT NULL,
    country text NOT NULL,
    country_ord integer NOT NULL,
    ord integer NOT NULL,
    name text NOT NULL,
    c text,
    val text,
    since text,
    qty text,
    stage text,
    note text,
    src text,
    srcnote text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT geo_presence_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN geo_presence.comp_id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.comp_id IS 'Company the presence belongs to; keyed the same as geo_comp.id so the two actually join.';


--
-- Name: COLUMN geo_presence.comp_ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.comp_ord IS 'Sort position of the company.';


--
-- Name: COLUMN geo_presence.country; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.country IS 'Country of the presence.';


--
-- Name: COLUMN geo_presence.country_ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.country_ord IS 'Sort position of the country.';


--
-- Name: COLUMN geo_presence.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.ord IS 'Sort position within the country.';


--
-- Name: COLUMN geo_presence.name; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.name IS 'What the presence is called.';


--
-- Name: COLUMN geo_presence.c; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.c IS 'Country code.';


--
-- Name: COLUMN geo_presence.val; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.val IS 'Stated value of the activity.';


--
-- Name: COLUMN geo_presence.since; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.since IS 'When the presence began.';


--
-- Name: COLUMN geo_presence.qty; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.qty IS 'Stated quantity.';


--
-- Name: COLUMN geo_presence.stage; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.stage IS 'Procurement stage: in talks, bidding, offered, in production, in delivery, inducted.';


--
-- Name: COLUMN geo_presence.note; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.note IS 'What is happening there. An activity is only written when its own verb is stated: a supplier procurement is not local production.';


--
-- Name: COLUMN geo_presence.src; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.src IS 'URL of the statement actually used -- not the first statement in the group, which cited documents that never mentioned the claim.';


--
-- Name: COLUMN geo_presence.srcnote; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.srcnote IS 'Label for the source.';


--
-- Name: COLUMN geo_presence.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.origin IS 'pipeline or reference.';


--
-- Name: COLUMN geo_presence.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.geo_presence.updated_at IS 'When the row was last written.';


--
-- Name: innovation; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.innovation (
    area text NOT NULL,
    area_ord integer NOT NULL,
    ord integer NOT NULL,
    t text NOT NULL,
    mat text,
    gap text,
    driver text,
    horizon text,
    body text,
    impact text,
    "whatsNew" text,
    "compNote" text,
    action text,
    sources text,
    url text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT innovation_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN innovation.area; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.area IS 'Technology area.';


--
-- Name: COLUMN innovation.area_ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.area_ord IS 'Sort position of the area.';


--
-- Name: COLUMN innovation.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.ord IS 'Sort position within the area.';


--
-- Name: COLUMN innovation.t; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.t IS 'Title of the development.';


--
-- Name: COLUMN innovation.mat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.mat IS 'Maturity: concept, dev, prod or fielded. Capped at dev when the source only shows an unveiling or a trade-show display.';


--
-- Name: COLUMN innovation.gap; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.gap IS 'Where KSSL stands against it.';


--
-- Name: COLUMN innovation.driver; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.driver IS 'Company driving it, canonicalised.';


--
-- Name: COLUMN innovation.horizon; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.horizon IS 'Expected timeframe.';


--
-- Name: COLUMN innovation.body; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.body IS 'What the development is.';


--
-- Name: COLUMN innovation.impact; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.impact IS 'Effect on KSSL.';


--
-- Name: COLUMN innovation."whatsNew"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation."whatsNew" IS 'What changed relative to what was known before.';


--
-- Name: COLUMN innovation."compNote"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation."compNote" IS 'Note on the competitor.';


--
-- Name: COLUMN innovation.action; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.action IS 'Recommended response.';


--
-- Name: COLUMN innovation.sources; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.sources IS 'Source labels.';


--
-- Name: COLUMN innovation.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.url IS 'Source article.';


--
-- Name: COLUMN innovation.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.origin IS 'pipeline or reference.';


--
-- Name: COLUMN innovation.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.innovation.updated_at IS 'When the row was last written.';


--
-- Name: matchup; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.matchup (
    matchup_id integer NOT NULL,
    cat text NOT NULL,
    anchor text,
    global boolean,
    dir text,
    country text,
    comp text,
    "compBy" text,
    bf text,
    "bfBy" text,
    ks_thin boolean,
    reason text,
    edge integer,
    specs jsonb,
    "advComp" jsonb,
    "advBf" jsonb,
    det jsonb,
    "verdictH" text,
    verdict text,
    "catKey" text,
    srcs jsonb,
    gen boolean,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT matchup_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN matchup.matchup_id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.matchup_id IS 'Integer key. Id ranges separate the writers: enrich_serving owns below 20000, revive_matchups owns 20000+, and each deletes only its own range.';


--
-- Name: COLUMN matchup.cat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.cat IS 'KSSL product category the comparison sits in.';


--
-- Name: COLUMN matchup.anchor; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.anchor IS 'The KSSL product the category is anchored on.';


--
-- Name: COLUMN matchup.global; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.global IS 'True when the pairing is a global rather than India-specific comparison.';


--
-- Name: COLUMN matchup.dir; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.dir IS 'threat or watch.';


--
-- Name: COLUMN matchup.country; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.country IS 'Origin country of the competitor product.';


--
-- Name: COLUMN matchup.comp; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.comp IS 'Competitor product, written "Maker - Product". The maker is not the product: grounding on the maker''s name once sourced CAESAR''s calibre to an article about a different gun.';


--
-- Name: COLUMN matchup."compBy"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."compBy" IS 'Company that makes the competitor product.';


--
-- Name: COLUMN matchup.bf; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.bf IS 'The KSSL product being compared.';


--
-- Name: COLUMN matchup."bfBy"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."bfBy" IS 'KSSL entity that makes it.';


--
-- Name: COLUMN matchup.ks_thin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.ks_thin IS 'True when no specification could be sourced for this pairing; the row still shows, with nothing asserted.';


--
-- Name: COLUMN matchup.reason; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.reason IS 'Why these two are compared, and how many specs were sourced versus dropped.';


--
-- Name: COLUMN matchup.edge; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.edge IS 'Percent of comparable fields the competitor leads on. NULL when nothing is comparable -- an edge of 0 would read as "leads on nothing", which is a different claim.';


--
-- Name: COLUMN matchup.specs; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.specs IS 'Spec rows. Each carries the rival value, the KSSL value, and srcC/srcK: the URL of the document that states each number next to the product it describes.';


--
-- Name: COLUMN matchup."advComp"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."advComp" IS 'Competitor advantages, each grounded in stated text.';


--
-- Name: COLUMN matchup."advBf"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."advBf" IS 'KSSL advantages, same rule.';


--
-- Name: COLUMN matchup.det; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.det IS 'Detail table: maker, origin, counterpart, how many specs were sourced, and provenance.';


--
-- Name: COLUMN matchup."verdictH"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."verdictH" IS 'Heading above the verdict.';


--
-- Name: COLUMN matchup.verdict; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.verdict IS 'Recomputed from surviving specs only. Copying a verdict written about ten specs onto the two that could be sourced would be worse than showing none.';


--
-- Name: COLUMN matchup."catKey"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup."catKey" IS 'Short category key used by the UI filters.';


--
-- Name: COLUMN matchup.srcs; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.srcs IS 'Documents actually used to ground this row.';


--
-- Name: COLUMN matchup.gen; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.gen IS 'True when the pairing was generated rather than authored.';


--
-- Name: COLUMN matchup.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.origin IS 'pipeline or reference.';


--
-- Name: COLUMN matchup.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.matchup.updated_at IS 'When the row was last written.';


--
-- Name: partner; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.partner (
    id text NOT NULL,
    ord integer NOT NULL,
    label text NOT NULL,
    kind text,
    rel text,
    sig integer,
    ptype text,
    note text,
    date text,
    country text,
    deal text,
    insight text,
    mean text,
    src text,
    srcnote text,
    cid text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT partner_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN partner.id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.id IS 'Partnership id.';


--
-- Name: COLUMN partner.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.ord IS 'Sort position.';


--
-- Name: COLUMN partner.label; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.label IS 'The two sides of the tie. Each side must be a named organisation, not a country or an armed force.';


--
-- Name: COLUMN partner.kind; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.kind IS 'Kind of tie: joint venture, MoU, supply, licence.';


--
-- Name: COLUMN partner.rel; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.rel IS 'Relationship direction.';


--
-- Name: COLUMN partner.sig; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.sig IS 'Significance score.';


--
-- Name: COLUMN partner.ptype; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.ptype IS 'Partner type.';


--
-- Name: COLUMN partner.note; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.note IS 'What the tie covers.';


--
-- Name: COLUMN partner.date; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.date IS 'When it was announced.';


--
-- Name: COLUMN partner.country; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.country IS 'Country involved.';


--
-- Name: COLUMN partner.deal; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.deal IS 'Deal value or scope where stated.';


--
-- Name: COLUMN partner.insight; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.insight IS 'What it means for KSSL.';


--
-- Name: COLUMN partner.mean; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.mean IS 'Short reading of the tie.';


--
-- Name: COLUMN partner.src; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.src IS 'URL of the document that states the tie. Revived rows carry one; a row without one was never republished.';


--
-- Name: COLUMN partner.srcnote; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.srcnote IS 'Why that source clears the bar: official, or corroborated by N independent domains.';


--
-- Name: COLUMN partner.cid; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.cid IS 'Canonical organisation id, shared with competitor ties so the same company joins across both tables.';


--
-- Name: COLUMN partner.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.origin IS 'pipeline or reference.';


--
-- Name: COLUMN partner.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.partner.updated_at IS 'When the row was last written.';


--
-- Name: patent; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.patent (
    ord integer NOT NULL,
    assignee_ord integer NOT NULL,
    no text NOT NULL,
    title text,
    assignee text NOT NULL,
    status text,
    filed text,
    granted text,
    country text,
    ipc jsonb,
    abstract text,
    area text NOT NULL,
    threat text,
    relev text,
    url text,
    p text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT patent_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN patent.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.ord IS 'Sort position.';


--
-- Name: COLUMN patent.assignee_ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.assignee_ord IS 'Sort position of the assignee group.';


--
-- Name: COLUMN patent.no; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.no IS 'Publication number from the registry. Must be a well-formed identifier: the archived dataset held invented numbers such as IN-2024-EST01 (est), which are refused here.';


--
-- Name: COLUMN patent.title; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.title IS 'Patent title as published.';


--
-- Name: COLUMN patent.assignee; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.assignee IS 'Owner of record.';


--
-- Name: COLUMN patent.status; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.status IS 'granted or filed, from whether a grant date exists.';


--
-- Name: COLUMN patent.filed; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.filed IS 'Filing date.';


--
-- Name: COLUMN patent.granted; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.granted IS 'Grant date, empty when still pending.';


--
-- Name: COLUMN patent.country; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.country IS 'Jurisdiction, from the publication number prefix.';


--
-- Name: COLUMN patent.ipc; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.ipc IS 'IPC/CPC classification codes where the registry supplies them.';


--
-- Name: COLUMN patent.abstract; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.abstract IS 'Abstract as published.';


--
-- Name: COLUMN patent.area; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.area IS 'KSSL category the patent bears on. A diversified forger''s oil-and-gas patents are not defence patents.';


--
-- Name: COLUMN patent.threat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.threat IS 'Threat rating, only where something measurable supports one.';


--
-- Name: COLUMN patent.relev; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.relev IS 'Relevance to KSSL.';


--
-- Name: COLUMN patent.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.url IS 'Link to the registry record itself.';


--
-- Name: COLUMN patent.p; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.p IS 'Short display label.';


--
-- Name: COLUMN patent.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.origin IS 'pipeline or reference.';


--
-- Name: COLUMN patent.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.patent.updated_at IS 'When the row was last written.';


--
-- Name: signal_card; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.signal_card (
    id text NOT NULL,
    lane text NOT NULL,
    ord integer NOT NULL,
    dir text,
    rank text,
    title text NOT NULL,
    meta text,
    company text,
    lens text,
    sowhat text,
    sec jsonb,
    url text,
    ago text,
    tags text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    image text,
    CONSTRAINT signal_card_lane_check CHECK ((lane = ANY (ARRAY['competitive'::text, 'market'::text, 'tech'::text]))),
    CONSTRAINT signal_card_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN signal_card.id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.id IS 'Card id. Pipeline cards are pl_<document_id>, so a card always names the document behind it.';


--
-- Name: COLUMN signal_card.lane; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.lane IS 'Which pillar feed it appears in: competitive, market or tech.';


--
-- Name: COLUMN signal_card.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.ord IS 'Sort position within the lane; renumbered from served position, never from insert order.';


--
-- Name: COLUMN signal_card.dir; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.dir IS 'threat or watch. Client news is never a threat to itself.';


--
-- Name: COLUMN signal_card.rank; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.rank IS 'Rank badge text, derived from the served position so the badge and the row can never disagree.';


--
-- Name: COLUMN signal_card.title; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.title IS 'One-line headline of the signal.';


--
-- Name: COLUMN signal_card.meta; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.meta IS 'Byline: category, company, source outlet.';


--
-- Name: COLUMN signal_card.company; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.company IS 'Canonical company the card is about. Kalyani, KSSL and Bharat Forge fold to one client identity.';


--
-- Name: COLUMN signal_card.lens; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.lens IS 'Analytical lens applied to the move.';


--
-- Name: COLUMN signal_card.sowhat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.sowhat IS 'Why it matters to KSSL. Analyst inference is allowed here; invented facts are not.';


--
-- Name: COLUMN signal_card.sec; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.sec IS 'Sector tags for filtering.';


--
-- Name: COLUMN signal_card.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.url IS 'Link to the article itself, not to the outlet home page.';


--
-- Name: COLUMN signal_card.ago; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.ago IS 'Human-readable age, computed from the publication date proved from the document''s own Date spans -- never the fetch date.';


--
-- Name: COLUMN signal_card.tags; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.tags IS 'Free tags shown on the card.';


--
-- Name: COLUMN signal_card.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.origin IS 'pipeline = produced by this system from the corpus; reference = the archived hand-built dataset. serving_live views expose pipeline only.';


--
-- Name: COLUMN signal_card.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_card.updated_at IS 'When the row was last written.';


--
-- Name: signal_detail; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.signal_detail (
    id text NOT NULL,
    ord integer NOT NULL,
    rank text,
    dir text,
    title text NOT NULL,
    facts jsonb,
    what text,
    why text,
    lens jsonb,
    actions jsonb,
    url text,
    suggest jsonb,
    kind text,
    match jsonb,
    pursue jsonb,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT signal_detail_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN signal_detail.id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.id IS 'Matches signal_card.id.';


--
-- Name: COLUMN signal_detail.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.ord IS 'Sort position.';


--
-- Name: COLUMN signal_detail.rank; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.rank IS 'Rank badge, from served position.';


--
-- Name: COLUMN signal_detail.dir; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.dir IS 'threat or watch, consistent with the card.';


--
-- Name: COLUMN signal_detail.title; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.title IS 'Headline of the detail panel.';


--
-- Name: COLUMN signal_detail.facts; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.facts IS 'The extracted statements behind the card. Each must be entailed by its evidence, not merely mentioned by it.';


--
-- Name: COLUMN signal_detail.what; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.what IS 'What happened, in plain words.';


--
-- Name: COLUMN signal_detail.why; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.why IS 'Why it matters.';


--
-- Name: COLUMN signal_detail.lens; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.lens IS 'Per-lens readings of the same move.';


--
-- Name: COLUMN signal_detail.actions; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.actions IS 'Suggested actions.';


--
-- Name: COLUMN signal_detail.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.url IS 'Source article.';


--
-- Name: COLUMN signal_detail.suggest; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.suggest IS 'Follow-up questions offered to the reader.';


--
-- Name: COLUMN signal_detail.kind; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.kind IS 'Which detail layout to render.';


--
-- Name: COLUMN signal_detail.match; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.match IS 'Matched KSSL capability, where one applies.';


--
-- Name: COLUMN signal_detail.pursue; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.pursue IS 'Pursuit guidance for an opportunity.';


--
-- Name: COLUMN signal_detail.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.origin IS 'pipeline or reference.';


--
-- Name: COLUMN signal_detail.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.signal_detail.updated_at IS 'When the row was last written.';


--
-- Name: source_registry; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.source_registry (
    ord integer NOT NULL,
    company text NOT NULL,
    label text,
    url text NOT NULL,
    kind text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_registry_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN source_registry.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.ord IS 'Sort position.';


--
-- Name: COLUMN source_registry.company; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.company IS 'Company the source is about.';


--
-- Name: COLUMN source_registry.label; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.label IS 'Human label for the source.';


--
-- Name: COLUMN source_registry.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.url IS 'The source document.';


--
-- Name: COLUMN source_registry.kind; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.kind IS 'Kind of source: official, press, registry.';


--
-- Name: COLUMN source_registry.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.origin IS 'pipeline or reference.';


--
-- Name: COLUMN source_registry.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.source_registry.updated_at IS 'When the row was last written.';


--
-- Name: tender; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.tender (
    id text NOT NULL,
    ord integer NOT NULL,
    title text NOT NULL,
    issuer text,
    country text,
    cat text,
    value text,
    qty text,
    deadline text,
    dl integer,
    "reqNote" text,
    req jsonb,
    matches jsonb,
    lean text,
    "leanTxt" text,
    status text,
    url text,
    "urlKind" text,
    srcs jsonb,
    stage text,
    origin text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tender_origin_check CHECK ((origin = ANY (ARRAY['reference'::text, 'pipeline'::text])))
);


--
-- Name: COLUMN tender.id; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.id IS 'Tender id. Text ids (sam_/ted_/gem_) come from the API fetch; numeric ids from the news cross-check. Each writer deletes only its own id space.';


--
-- Name: COLUMN tender.ord; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.ord IS 'Sort position, renumbered by deadline.';


--
-- Name: COLUMN tender.title; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.title IS 'Notice title as published by the issuing portal.';


--
-- Name: COLUMN tender.issuer; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.issuer IS 'Buying authority.';


--
-- Name: COLUMN tender.country; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.country IS 'Country of the buyer.';


--
-- Name: COLUMN tender.cat; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.cat IS 'KSSL category the notice maps to; from the main classification code only, not any secondary code.';


--
-- Name: COLUMN tender.value; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.value IS 'Published value. Absent for most notices -- absent is not zero.';


--
-- Name: COLUMN tender.qty; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.qty IS 'Published quantity, where stated.';


--
-- Name: COLUMN tender.deadline; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.deadline IS 'Submission deadline as published.';


--
-- Name: COLUMN tender.dl; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.dl IS 'Days remaining, for sorting.';


--
-- Name: COLUMN tender."reqNote"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender."reqNote" IS 'Note on the stated requirement.';


--
-- Name: COLUMN tender.req; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.req IS 'Requirement lines extracted from the notice.';


--
-- Name: COLUMN tender.matches; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.matches IS 'KSSL capabilities that match the requirement.';


--
-- Name: COLUMN tender.lean; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.lean IS 'Fit verdict. NULL where no assessment was made -- a constant verdict stamped on every row is not a verdict.';


--
-- Name: COLUMN tender."leanTxt"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender."leanTxt" IS 'Reasoning behind the fit verdict.';


--
-- Name: COLUMN tender.status; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.status IS 'open, awarded or closed. Only open notices are biddable.';


--
-- Name: COLUMN tender.url; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.url IS 'Link to the notice.';


--
-- Name: COLUMN tender."urlKind"; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender."urlKind" IS 'Whether the link reaches the notice itself or only a portal search page.';


--
-- Name: COLUMN tender.srcs; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.srcs IS 'Source portal records.';


--
-- Name: COLUMN tender.stage; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.stage IS 'Procurement stage.';


--
-- Name: COLUMN tender.origin; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.origin IS 'pipeline or reference.';


--
-- Name: COLUMN tender.updated_at; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.tender.updated_at IS 'When the row was last written.';


--
-- Name: ui_config; Type: TABLE; Schema: serving; Owner: -
--

CREATE TABLE serving.ui_config (
    key text NOT NULL,
    value jsonb NOT NULL
);


--
-- Name: COLUMN ui_config.key; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.ui_config.key IS 'Interface vocabulary key: category names, labels, ordering. Not data, so serving_live passes it through unfiltered.';


--
-- Name: COLUMN ui_config.value; Type: COMMENT; Schema: serving; Owner: -
--

COMMENT ON COLUMN serving.ui_config.value IS 'The configuration value.';


--
-- Name: document document_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (document_id);


--
-- Name: entity_alias entity_alias_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.entity_alias
    ADD CONSTRAINT entity_alias_pkey PRIMARY KEY (entity_id, surface_folded, lang);


--
-- Name: entity entity_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.entity
    ADD CONSTRAINT entity_pkey PRIMARY KEY (entity_id);


--
-- Name: extraction_run extraction_run_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.extraction_run
    ADD CONSTRAINT extraction_run_pkey PRIMARY KEY (run_id);


--
-- Name: prop_arg prop_arg_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.prop_arg
    ADD CONSTRAINT prop_arg_pkey PRIMARY KEY (document_id, run_id, prop_i, role);


--
-- Name: proposition proposition_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.proposition
    ADD CONSTRAINT proposition_pkey PRIMARY KEY (document_id, run_id, i);


--
-- Name: span span_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.span
    ADD CONSTRAINT span_pkey PRIMARY KEY (document_id, run_id, span_id);


--
-- Name: span_value span_value_pkey; Type: CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.span_value
    ADD CONSTRAINT span_value_pkey PRIMARY KEY (document_id, run_id, span_id);


--
-- Name: card card_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.card
    ADD CONSTRAINT card_pkey PRIMARY KEY (document_id, run_id);


--
-- Name: company_source company_source_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.company_source
    ADD CONSTRAINT company_source_pkey PRIMARY KEY (company, ord);


--
-- Name: competitors competitors_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.competitors
    ADD CONSTRAINT competitors_pkey PRIMARY KEY (comp_id);


--
-- Name: geo_comp geo_comp_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.geo_comp
    ADD CONSTRAINT geo_comp_pkey PRIMARY KEY (id);


--
-- Name: geo_presence geo_presence_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.geo_presence
    ADD CONSTRAINT geo_presence_pkey PRIMARY KEY (comp_id, country, ord);


--
-- Name: innovation innovation_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.innovation
    ADD CONSTRAINT innovation_pkey PRIMARY KEY (area, ord);


--
-- Name: matchup matchup_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.matchup
    ADD CONSTRAINT matchup_pkey PRIMARY KEY (matchup_id);


--
-- Name: partner partner_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.partner
    ADD CONSTRAINT partner_pkey PRIMARY KEY (id);


--
-- Name: patent patent_no_key; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.patent
    ADD CONSTRAINT patent_no_key UNIQUE (no);


--
-- Name: patent patent_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.patent
    ADD CONSTRAINT patent_pkey PRIMARY KEY (ord);


--
-- Name: signal_card signal_card_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.signal_card
    ADD CONSTRAINT signal_card_pkey PRIMARY KEY (id);


--
-- Name: signal_detail signal_detail_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.signal_detail
    ADD CONSTRAINT signal_detail_pkey PRIMARY KEY (id);


--
-- Name: source_registry source_registry_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.source_registry
    ADD CONSTRAINT source_registry_pkey PRIMARY KEY (ord);


--
-- Name: tender tender_pkey; Type: CONSTRAINT; Schema: serving; Owner: -
--

ALTER TABLE ONLY serving.tender
    ADD CONSTRAINT tender_pkey PRIMARY KEY (id);


--
-- Name: document_language_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX document_language_idx ON extracted.document USING btree (language);


--
-- Name: document_source_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX document_source_idx ON extracted.document USING btree (source_id);


--
-- Name: entity_alias_folded_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX entity_alias_folded_idx ON extracted.entity_alias USING btree (surface_folded);


--
-- Name: entity_live_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX entity_live_idx ON extracted.entity USING btree (entity_id) WHERE (redirects_to IS NULL);


--
-- Name: entity_type_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX entity_type_idx ON extracted.entity USING btree (entity_type);


--
-- Name: prop_arg_span_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX prop_arg_span_idx ON extracted.prop_arg USING btree (document_id, run_id, span_id);


--
-- Name: prop_ev_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX prop_ev_idx ON extracted.proposition USING btree (document_id, run_id, ev_start, ev_end);


--
-- Name: prop_subj_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX prop_subj_idx ON extracted.proposition USING btree (lower(subject));


--
-- Name: span_pos_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_pos_idx ON extracted.span USING btree (document_id, run_id, start_c, end_c);


--
-- Name: span_text_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_text_idx ON extracted.span USING btree (lower(text));


--
-- Name: span_type_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_type_idx ON extracted.span USING btree (type);


--
-- Name: span_value_dt_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_value_dt_idx ON extracted.span_value USING gist (dt) WHERE (status = 'parsed'::text);


--
-- Name: span_value_kind_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_value_kind_idx ON extracted.span_value USING btree (kind, status);


--
-- Name: span_value_num_idx; Type: INDEX; Schema: extracted; Owner: -
--

CREATE INDEX span_value_num_idx ON extracted.span_value USING gist (num) WHERE (status = 'parsed'::text);


--
-- Name: card_built_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX card_built_idx ON serving.card USING btree (built_at DESC);


--
-- Name: card_source_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX card_source_idx ON serving.card USING btree (source_id);


--
-- Name: card_spans_gin; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX card_spans_gin ON serving.card USING gin (spans jsonb_path_ops);


--
-- Name: card_stmts_gin; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX card_stmts_gin ON serving.card USING gin (statements jsonb_path_ops);


--
-- Name: geo_presence_comp_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX geo_presence_comp_idx ON serving.geo_presence USING btree (comp_id);


--
-- Name: matchup_catkey_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX matchup_catkey_idx ON serving.matchup USING btree ("catKey");


--
-- Name: patent_area_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX patent_area_idx ON serving.patent USING btree (area);


--
-- Name: patent_assignee_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX patent_assignee_idx ON serving.patent USING btree (assignee);


--
-- Name: signal_card_lane_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX signal_card_lane_idx ON serving.signal_card USING btree (lane, ord);


--
-- Name: tender_cat_idx; Type: INDEX; Schema: serving; Owner: -
--

CREATE INDEX tender_cat_idx ON serving.tender USING btree (cat);


--
-- Name: entity_alias entity_alias_entity_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.entity_alias
    ADD CONSTRAINT entity_alias_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES extracted.entity(entity_id) ON DELETE CASCADE;


--
-- Name: entity entity_redirects_to_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.entity
    ADD CONSTRAINT entity_redirects_to_fkey FOREIGN KEY (redirects_to) REFERENCES extracted.entity(entity_id);


--
-- Name: prop_arg prop_arg_document_id_run_id_prop_i_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.prop_arg
    ADD CONSTRAINT prop_arg_document_id_run_id_prop_i_fkey FOREIGN KEY (document_id, run_id, prop_i) REFERENCES extracted.proposition(document_id, run_id, i) ON DELETE CASCADE;


--
-- Name: prop_arg prop_arg_document_id_run_id_span_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.prop_arg
    ADD CONSTRAINT prop_arg_document_id_run_id_span_id_fkey FOREIGN KEY (document_id, run_id, span_id) REFERENCES extracted.span(document_id, run_id, span_id) ON DELETE CASCADE;


--
-- Name: proposition proposition_document_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.proposition
    ADD CONSTRAINT proposition_document_id_fkey FOREIGN KEY (document_id) REFERENCES extracted.document(document_id) ON DELETE CASCADE;


--
-- Name: proposition proposition_run_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.proposition
    ADD CONSTRAINT proposition_run_id_fkey FOREIGN KEY (run_id) REFERENCES extracted.extraction_run(run_id);


--
-- Name: span span_document_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.span
    ADD CONSTRAINT span_document_id_fkey FOREIGN KEY (document_id) REFERENCES extracted.document(document_id) ON DELETE CASCADE;


--
-- Name: span span_run_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.span
    ADD CONSTRAINT span_run_id_fkey FOREIGN KEY (run_id) REFERENCES extracted.extraction_run(run_id);


--
-- Name: span_value span_value_document_id_run_id_span_id_fkey; Type: FK CONSTRAINT; Schema: extracted; Owner: -
--

ALTER TABLE ONLY extracted.span_value
    ADD CONSTRAINT span_value_document_id_run_id_span_id_fkey FOREIGN KEY (document_id, run_id, span_id) REFERENCES extracted.span(document_id, run_id, span_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict CsgAsDxtwDbdJmQRdhddFfJUYx3ZhMyWTzvdzwExitbdiWQcrN4fHdxj3d1E4kT

