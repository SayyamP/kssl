-- Column documentation, stored where the data is.
--
-- PIPELINE.html renders a "what it holds" column that reads col_description() at
-- build time. Every one of the 270 columns was blank, so the doc promised an
-- explanation and delivered an empty cell. The fix belongs in the database rather
-- than the generator: a COMMENT is visible to psql \d+, to any client, and to
-- anyone querying these tables without the doc open -- and the doc then fills
-- itself from it.
--
-- Rule followed here: describe what the column HOLDS and, where it is not
-- obvious, what makes a value legal. Do not restate the column name.

-- ===========================================================================
-- extracted.*  -- Layer A (spans and statements) and Layer B (entities)
-- ===========================================================================

COMMENT ON COLUMN extracted.document.document_id IS 'Stable id, sha256 of the URL truncated to 16 hex chars. The same page fetched twice keeps one id.';
COMMENT ON COLUMN extracted.document.url IS 'Final URL after redirects, as fetched.';
COMMENT ON COLUMN extracted.document.source_id IS 'Publisher host with any leading www. stripped -- the outlet, used for corroboration counting.';
COMMENT ON COLUMN extracted.document.language IS 'ISO code from the extraction pipeline''s own detector, never a second library: two detectors disagreeing about Persian and Arabic is a bug already paid for once.';
COMMENT ON COLUMN extracted.document.title IS 'Headline as published.';
COMMENT ON COLUMN extracted.document.text IS 'Body text after boilerplate removal. All span offsets index into THIS string, so it must never be re-normalised in place.';
COMMENT ON COLUMN extracted.document.text_sha256 IS 'Hash of text. Two addresses with identical bodies are one syndicated story, not two independent witnesses.';
COMMENT ON COLUMN extracted.document.n_chars IS 'Length of text in characters; the denominator for coverage.';
COMMENT ON COLUMN extracted.document.n_sentences IS 'Sentence count from segmentation.';
COMMENT ON COLUMN extracted.document.meta IS 'Provenance blob: which set (kssl/parallax/kssl_demo), how it was found, when fetched.';
COMMENT ON COLUMN extracted.document.first_seen IS 'When this document first entered the store; NOT the publication date, which is derived from the document''s own Date spans.';

COMMENT ON COLUMN extracted.entity.entity_id IS 'Layer B identity. Hashed from surface AND type, because the same string as an Organization and as a Product are different things.';
COMMENT ON COLUMN extracted.entity.entity_type IS 'Organization, Product, Platform, WeaponSystem, Technology, Program, Facility, Material, Equipment.';
COMMENT ON COLUMN extracted.entity.canonical_name IS 'The spelling chosen to represent the group of aliases.';
COMMENT ON COLUMN extracted.entity.canonical_lang IS 'Language of the canonical spelling.';
COMMENT ON COLUMN extracted.entity.ont_node_id IS 'Ontology sector node this entity classifies to (l2/ontology/ontology.yaml). NULL means unclassified -- the open slot, counted and reported, never force-fitted.';
COMMENT ON COLUMN extracted.entity.ont_version IS 'Ontology semver in force when the classification was made, so a taxonomy change is a re-classification job and not a silent reinterpretation.';
COMMENT ON COLUMN extracted.entity.redirects_to IS 'Set when this entity was merged into another; the row survives so old references still resolve.';
COMMENT ON COLUMN extracted.entity.created_at IS 'When the entity was first created.';
COMMENT ON COLUMN extracted.entity.created_by_run IS 'Extraction run that created it; joins extraction_run.';

COMMENT ON COLUMN extracted.entity_alias.entity_id IS 'Entity this spelling belongs to.';
COMMENT ON COLUMN extracted.entity_alias.surface IS 'The spelling exactly as it appeared in a document.';
COMMENT ON COLUMN extracted.entity_alias.surface_folded IS 'Accent-stripped, case-folded form for matching. Decompose, strip, then recompose NFC -- NFKD alone shatters Hangul into Jamo.';
COMMENT ON COLUMN extracted.entity_alias.lang IS 'Language the spelling occurred in.';
COMMENT ON COLUMN extracted.entity_alias.script IS 'Writing system. Cross-script pairs are never auto-merged whatever they score: six Russian outlets once matched at similarity 1.00 because they share a gloss, not an identity.';
COMMENT ON COLUMN extracted.entity_alias.alias_kind IS 'Closed set, enforced by CHECK: name, legal_variant, abbreviation, transliteration, translation, misspelling, former_name. Not free text.';
COMMENT ON COLUMN extracted.entity_alias.n_mentions IS 'How often this spelling occurred. A count of spellings, not of companies, until identity hygiene has run.';

COMMENT ON COLUMN extracted.extraction_run.run_id IS 'One extraction pass. Every span and statement carries it, so a bad run can be isolated.';
COMMENT ON COLUMN extracted.extraction_run.started_at IS 'When the run began.';
COMMENT ON COLUMN extracted.extraction_run.pipeline_version IS 'Git revision of the extraction code.';
COMMENT ON COLUMN extracted.extraction_run.lexicon_version IS 'Hash of the term lexicon used; a lexicon change alters span typing.';
COMMENT ON COLUMN extracted.extraction_run.model IS 'Extractor model and digest (e.g. qwen2.5:7b + GLiNER).';
COMMENT ON COLUMN extracted.extraction_run.config IS 'Run settings: workers, context, thresholds.';
COMMENT ON COLUMN extracted.extraction_run.note IS 'Free-text label for the run.';
COMMENT ON COLUMN extracted.extraction_run.loaded_at IS 'When the run was loaded into Postgres from the engine''s SQLite store.';

COMMENT ON COLUMN extracted.span.document_id IS 'Document the span is cut from.';
COMMENT ON COLUMN extracted.span.run_id IS 'Extraction run that produced it.';
COMMENT ON COLUMN extracted.span.span_id IS 'Id unique within the document.';
COMMENT ON COLUMN extracted.span.start_c IS 'Start character offset into document.text, inclusive.';
COMMENT ON COLUMN extracted.span.end_c IS 'End character offset, exclusive. The load step refuses any document where text[start_c:end_c] != text -- a repaired offset would be an invented quote.';
COMMENT ON COLUMN extracted.span.text IS 'The exact substring. Must equal document.text[start_c:end_c].';
COMMENT ON COLUMN extracted.span.type IS 'Semantic type: Organization, Country, Date, Measure, WeaponSystem, Concept, Action and so on.';
COMMENT ON COLUMN extracted.span.type_ner IS 'Raw label from the NER model before reconciliation.';
COMMENT ON COLUMN extracted.span.gloss IS 'Short description of what the span refers to. Answers "same kind of thing", never "same thing".';
COMMENT ON COLUMN extracted.span.in_article IS 'Whether the span sits in article body or in navigation/boilerplate.';
COMMENT ON COLUMN extracted.span.source IS 'Which component proposed it: the model, the lexicon, or a rule.';
COMMENT ON COLUMN extracted.span.score IS 'Extractor confidence, where the component supplies one.';
COMMENT ON COLUMN extracted.span.sent IS 'Index of the sentence containing the span.';

COMMENT ON COLUMN extracted.proposition.document_id IS 'Document the statement came from.';
COMMENT ON COLUMN extracted.proposition.run_id IS 'Extraction run that produced it.';
COMMENT ON COLUMN extracted.proposition.i IS 'Position of the statement within the document.';
COMMENT ON COLUMN extracted.proposition.subject IS 'Who or what the statement is about, as written.';
COMMENT ON COLUMN extracted.proposition.predicate IS 'The relation, as the source phrased it -- free text, not a controlled vocabulary. 4,963 distinct surfaces over 17k rows; mapping these onto the ontology''s closed predicates is an unbuilt join.';
COMMENT ON COLUMN extracted.proposition.object IS 'What the subject is related to, as written.';
COMMENT ON COLUMN extracted.proposition.time_txt IS 'Time expression as written, unparsed.';
COMMENT ON COLUMN extracted.proposition.place_txt IS 'Place expression as written, unparsed.';
COMMENT ON COLUMN extracted.proposition.polarity IS 'Asserted or negated. A negated statement claims the opposite, so this may never be ignored.';
COMMENT ON COLUMN extracted.proposition.modality IS 'How strongly it is claimed: asserted, planned, reported, hypothetical. "Plans to deliver" is not "delivered".';
COMMENT ON COLUMN extracted.proposition.ev_start IS 'Start offset of the evidence sentence in document.text.';
COMMENT ON COLUMN extracted.proposition.ev_end IS 'End offset of the evidence sentence.';
COMMENT ON COLUMN extracted.proposition.ev_quote IS 'The sentence the statement was read from. Existence of a quote is not entailment: it must actually support the claim.';
COMMENT ON COLUMN extracted.proposition.ev_fragment IS 'True when the evidence is a fragment rather than a whole sentence.';

COMMENT ON COLUMN extracted.span_value.document_id IS 'Document the measured span belongs to.';
COMMENT ON COLUMN extracted.span_value.run_id IS 'Extraction run.';
COMMENT ON COLUMN extracted.span_value.span_id IS 'The Measure/Date/Count span this value was parsed from.';
COMMENT ON COLUMN extracted.span_value.parser_version IS 'Value parser version; a reparse is a new version, not an edit.';
COMMENT ON COLUMN extracted.span_value.status IS 'Enforced by CHECK: parsed, not_a_value, failed. A refusal (not_a_value) is a recorded outcome, not a gap.';
COMMENT ON COLUMN extracted.span_value.kind IS 'What kind of quantity: length, mass, money, count, date, speed, power.';
COMMENT ON COLUMN extracted.span_value.num IS 'Numeric value as a RANGE, so "24-30 km" and "over 40" stay honest instead of collapsing to a point.';
COMMENT ON COLUMN extracted.span_value.dt IS 'Date value as a range, for the same reason: "2026" is a year, not a day.';
COMMENT ON COLUMN extracted.span_value.unit IS 'SI unit after normalisation. Two values may only be compared when their dimensions match.';
COMMENT ON COLUMN extracted.span_value.unit_raw IS 'Unit exactly as written in the source.';
COMMENT ON COLUMN extracted.span_value.currency IS 'ISO currency code where the value is money.';
COMMENT ON COLUMN extracted.span_value.qualifier IS 'Hedge attached to the number: about, up to, more than, at least.';
COMMENT ON COLUMN extracted.span_value.precision IS 'How exact the source was: exact, rounded, approximate.';
COMMENT ON COLUMN extracted.span_value.val_text IS 'The original text of the value, kept so the parse can always be audited against it.';
COMMENT ON COLUMN extracted.span_value.extra IS 'Parser detail that does not fit a column.';
COMMENT ON COLUMN extracted.span_value.note IS 'Why a value was refused or marked ambiguous.';

COMMENT ON COLUMN extracted.prop_arg.document_id IS 'Document the statement belongs to.';
COMMENT ON COLUMN extracted.prop_arg.run_id IS 'Extraction run.';
COMMENT ON COLUMN extracted.prop_arg.prop_i IS 'Which statement in the document this argument belongs to.';
COMMENT ON COLUMN extracted.prop_arg.role IS 'Which slot the span fills: subject, object, time, place.';
COMMENT ON COLUMN extracted.prop_arg.span_id IS 'The span filling the slot. This is what ties a statement to exact character offsets.';
COMMENT ON COLUMN extracted.prop_arg.method IS 'How the link was made, enforced by CHECK: exact, in_evidence, outside_evidence, paraphrase.';
COMMENT ON COLUMN extracted.prop_arg.arg_text IS 'Text of the argument as the statement phrased it.';

-- ===========================================================================
-- serving.*  -- what the UI reads. Every table carries `origin`.
-- ===========================================================================

COMMENT ON COLUMN serving.signal_card.id IS 'Card id. Pipeline cards are pl_<document_id>, so a card always names the document behind it.';
COMMENT ON COLUMN serving.signal_card.lane IS 'Which pillar feed it appears in: competitive, market or tech.';
COMMENT ON COLUMN serving.signal_card.ord IS 'Sort position within the lane; renumbered from served position, never from insert order.';
COMMENT ON COLUMN serving.signal_card.dir IS 'threat or watch. Client news is never a threat to itself.';
COMMENT ON COLUMN serving.signal_card.rank IS 'Rank badge text, derived from the served position so the badge and the row can never disagree.';
COMMENT ON COLUMN serving.signal_card.title IS 'One-line headline of the signal.';
COMMENT ON COLUMN serving.signal_card.meta IS 'Byline: category, company, source outlet.';
COMMENT ON COLUMN serving.signal_card.company IS 'Canonical company the card is about. Kalyani, KSSL and Bharat Forge fold to one client identity.';
COMMENT ON COLUMN serving.signal_card.lens IS 'Analytical lens applied to the move.';
COMMENT ON COLUMN serving.signal_card.sowhat IS 'Why it matters to KSSL. Analyst inference is allowed here; invented facts are not.';
COMMENT ON COLUMN serving.signal_card.sec IS 'Sector tags for filtering.';
COMMENT ON COLUMN serving.signal_card.url IS 'Link to the article itself, not to the outlet home page.';
COMMENT ON COLUMN serving.signal_card.ago IS 'Human-readable age, computed from the publication date proved from the document''s own Date spans -- never the fetch date.';
COMMENT ON COLUMN serving.signal_card.tags IS 'Free tags shown on the card.';
COMMENT ON COLUMN serving.signal_card.origin IS 'pipeline = produced by this system from the corpus; reference = the archived hand-built dataset. serving_live views expose pipeline only.';
COMMENT ON COLUMN serving.signal_card.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.signal_detail.id IS 'Matches signal_card.id.';
COMMENT ON COLUMN serving.signal_detail.ord IS 'Sort position.';
COMMENT ON COLUMN serving.signal_detail.rank IS 'Rank badge, from served position.';
COMMENT ON COLUMN serving.signal_detail.dir IS 'threat or watch, consistent with the card.';
COMMENT ON COLUMN serving.signal_detail.title IS 'Headline of the detail panel.';
COMMENT ON COLUMN serving.signal_detail.facts IS 'The extracted statements behind the card. Each must be entailed by its evidence, not merely mentioned by it.';
COMMENT ON COLUMN serving.signal_detail.what IS 'What happened, in plain words.';
COMMENT ON COLUMN serving.signal_detail.why IS 'Why it matters.';
COMMENT ON COLUMN serving.signal_detail.lens IS 'Per-lens readings of the same move.';
COMMENT ON COLUMN serving.signal_detail.actions IS 'Suggested actions.';
COMMENT ON COLUMN serving.signal_detail.url IS 'Source article.';
COMMENT ON COLUMN serving.signal_detail.suggest IS 'Follow-up questions offered to the reader.';
COMMENT ON COLUMN serving.signal_detail.kind IS 'Which detail layout to render.';
COMMENT ON COLUMN serving.signal_detail.match IS 'Matched KSSL capability, where one applies.';
COMMENT ON COLUMN serving.signal_detail.pursue IS 'Pursuit guidance for an opportunity.';
COMMENT ON COLUMN serving.signal_detail.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.signal_detail.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.competitors.comp_id IS 'Slug identity for the company, shared across serving tables.';
COMMENT ON COLUMN serving.competitors.ord IS 'Sort position in the roster; pipeline rows start at 1001 so reference rows keep the low range.';
COMMENT ON COLUMN serving.competitors.name IS 'Display name, canonicalised. Never a bare country and never two organisations joined by a conjunction.';
COMMENT ON COLUMN serving.competitors.dir IS 'rival, client or other. The client group is never a rival.';
COMMENT ON COLUMN serving.competitors.sector IS 'What the company sells. Refused when it merely echoes the prompt''s own portfolio list back.';
COMMENT ON COLUMN serving.competitors.hq IS 'Headquarters country.';
COMMENT ON COLUMN serving.competitors.threat IS 'high, medium or low -- derived from countable inputs, not asserted by a model. NULL when nothing measurable places the company in a KSSL category.';
COMMENT ON COLUMN serving.competitors.assess IS 'Prose assessment. Every sentence must be traceable to the company''s own extracted statements; a row with no surviving sentence is refused.';
COMMENT ON COLUMN serving.competitors.updates IS 'Recent moves. Listing pages and careers pages are filtered out.';
COMMENT ON COLUMN serving.competitors.center IS 'Map centre for the company view.';
COMMENT ON COLUMN serving.competitors.partners IS 'Named partners.';
COMMENT ON COLUMN serving.competitors.site IS 'Official website.';
COMMENT ON COLUMN serving.competitors.srcs IS 'Documents the profile was built from.';
COMMENT ON COLUMN serving.competitors.products IS 'Named products. Generic nouns are not product names.';
COMMENT ON COLUMN serving.competitors."threatNote" IS 'The measurement behind the threat rating, stated so the rating can be checked.';
COMMENT ON COLUMN serving.competitors.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.competitors.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.matchup.matchup_id IS 'Integer key. Id ranges separate the writers: enrich_serving owns below 20000, revive_matchups owns 20000+, and each deletes only its own range.';
COMMENT ON COLUMN serving.matchup.cat IS 'KSSL product category the comparison sits in.';
COMMENT ON COLUMN serving.matchup.anchor IS 'The KSSL product the category is anchored on.';
COMMENT ON COLUMN serving.matchup."global" IS 'True when the pairing is a global rather than India-specific comparison.';
COMMENT ON COLUMN serving.matchup.dir IS 'threat or watch.';
COMMENT ON COLUMN serving.matchup.country IS 'Origin country of the competitor product.';
COMMENT ON COLUMN serving.matchup.comp IS 'Competitor product, written "Maker - Product". The maker is not the product: grounding on the maker''s name once sourced CAESAR''s calibre to an article about a different gun.';
COMMENT ON COLUMN serving.matchup."compBy" IS 'Company that makes the competitor product.';
COMMENT ON COLUMN serving.matchup.bf IS 'The KSSL product being compared.';
COMMENT ON COLUMN serving.matchup."bfBy" IS 'KSSL entity that makes it.';
COMMENT ON COLUMN serving.matchup.ks_thin IS 'True when no specification could be sourced for this pairing; the row still shows, with nothing asserted.';
COMMENT ON COLUMN serving.matchup.reason IS 'Why these two are compared, and how many specs were sourced versus dropped.';
COMMENT ON COLUMN serving.matchup.edge IS 'Percent of comparable fields the competitor leads on. NULL when nothing is comparable -- an edge of 0 would read as "leads on nothing", which is a different claim.';
COMMENT ON COLUMN serving.matchup.specs IS 'Spec rows. Each carries the rival value, the KSSL value, and srcC/srcK: the URL of the document that states each number next to the product it describes.';
COMMENT ON COLUMN serving.matchup."advComp" IS 'Competitor advantages, each grounded in stated text.';
COMMENT ON COLUMN serving.matchup."advBf" IS 'KSSL advantages, same rule.';
COMMENT ON COLUMN serving.matchup.det IS 'Detail table: maker, origin, counterpart, how many specs were sourced, and provenance.';
COMMENT ON COLUMN serving.matchup."verdictH" IS 'Heading above the verdict.';
COMMENT ON COLUMN serving.matchup.verdict IS 'Recomputed from surviving specs only. Copying a verdict written about ten specs onto the two that could be sourced would be worse than showing none.';
COMMENT ON COLUMN serving.matchup."catKey" IS 'Short category key used by the UI filters.';
COMMENT ON COLUMN serving.matchup.srcs IS 'Documents actually used to ground this row.';
COMMENT ON COLUMN serving.matchup.gen IS 'True when the pairing was generated rather than authored.';
COMMENT ON COLUMN serving.matchup.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.matchup.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.tender.id IS 'Tender id. Text ids (sam_/ted_/gem_) come from the API fetch; numeric ids from the news cross-check. Each writer deletes only its own id space.';
COMMENT ON COLUMN serving.tender.ord IS 'Sort position, renumbered by deadline.';
COMMENT ON COLUMN serving.tender.title IS 'Notice title as published by the issuing portal.';
COMMENT ON COLUMN serving.tender.issuer IS 'Buying authority.';
COMMENT ON COLUMN serving.tender.country IS 'Country of the buyer.';
COMMENT ON COLUMN serving.tender.cat IS 'KSSL category the notice maps to; from the main classification code only, not any secondary code.';
COMMENT ON COLUMN serving.tender.value IS 'Published value. Absent for most notices -- absent is not zero.';
COMMENT ON COLUMN serving.tender.qty IS 'Published quantity, where stated.';
COMMENT ON COLUMN serving.tender.deadline IS 'Submission deadline as published.';
COMMENT ON COLUMN serving.tender.dl IS 'Days remaining, for sorting.';
COMMENT ON COLUMN serving.tender."reqNote" IS 'Note on the stated requirement.';
COMMENT ON COLUMN serving.tender.req IS 'Requirement lines extracted from the notice.';
COMMENT ON COLUMN serving.tender.matches IS 'KSSL capabilities that match the requirement.';
COMMENT ON COLUMN serving.tender.lean IS 'Fit verdict. NULL where no assessment was made -- a constant verdict stamped on every row is not a verdict.';
COMMENT ON COLUMN serving.tender."leanTxt" IS 'Reasoning behind the fit verdict.';
COMMENT ON COLUMN serving.tender.status IS 'open, awarded or closed. Only open notices are biddable.';
COMMENT ON COLUMN serving.tender.url IS 'Link to the notice.';
COMMENT ON COLUMN serving.tender."urlKind" IS 'Whether the link reaches the notice itself or only a portal search page.';
COMMENT ON COLUMN serving.tender.srcs IS 'Source portal records.';
COMMENT ON COLUMN serving.tender.stage IS 'Procurement stage.';
COMMENT ON COLUMN serving.tender.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.tender.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.innovation.area IS 'Technology area.';
COMMENT ON COLUMN serving.innovation.area_ord IS 'Sort position of the area.';
COMMENT ON COLUMN serving.innovation.ord IS 'Sort position within the area.';
COMMENT ON COLUMN serving.innovation.t IS 'Title of the development.';
COMMENT ON COLUMN serving.innovation.mat IS 'Maturity: concept, dev, prod or fielded. Capped at dev when the source only shows an unveiling or a trade-show display.';
COMMENT ON COLUMN serving.innovation.gap IS 'Where KSSL stands against it.';
COMMENT ON COLUMN serving.innovation.driver IS 'Company driving it, canonicalised.';
COMMENT ON COLUMN serving.innovation.horizon IS 'Expected timeframe.';
COMMENT ON COLUMN serving.innovation.body IS 'What the development is.';
COMMENT ON COLUMN serving.innovation.impact IS 'Effect on KSSL.';
COMMENT ON COLUMN serving.innovation."whatsNew" IS 'What changed relative to what was known before.';
COMMENT ON COLUMN serving.innovation."compNote" IS 'Note on the competitor.';
COMMENT ON COLUMN serving.innovation.action IS 'Recommended response.';
COMMENT ON COLUMN serving.innovation.sources IS 'Source labels.';
COMMENT ON COLUMN serving.innovation.url IS 'Source article.';
COMMENT ON COLUMN serving.innovation.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.innovation.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.patent.ord IS 'Sort position.';
COMMENT ON COLUMN serving.patent.assignee_ord IS 'Sort position of the assignee group.';
COMMENT ON COLUMN serving.patent.no IS 'Publication number from the registry. Must be a well-formed identifier: the archived dataset held invented numbers such as IN-2024-EST01 (est), which are refused here.';
COMMENT ON COLUMN serving.patent.title IS 'Patent title as published.';
COMMENT ON COLUMN serving.patent.assignee IS 'Owner of record.';
COMMENT ON COLUMN serving.patent.status IS 'granted or filed, from whether a grant date exists.';
COMMENT ON COLUMN serving.patent.filed IS 'Filing date.';
COMMENT ON COLUMN serving.patent.granted IS 'Grant date, empty when still pending.';
COMMENT ON COLUMN serving.patent.country IS 'Jurisdiction, from the publication number prefix.';
COMMENT ON COLUMN serving.patent.ipc IS 'IPC/CPC classification codes where the registry supplies them.';
COMMENT ON COLUMN serving.patent.abstract IS 'Abstract as published.';
COMMENT ON COLUMN serving.patent.area IS 'KSSL category the patent bears on. A diversified forger''s oil-and-gas patents are not defence patents.';
COMMENT ON COLUMN serving.patent.threat IS 'Threat rating, only where something measurable supports one.';
COMMENT ON COLUMN serving.patent.relev IS 'Relevance to KSSL.';
COMMENT ON COLUMN serving.patent.url IS 'Link to the registry record itself.';
COMMENT ON COLUMN serving.patent.p IS 'Short display label.';
COMMENT ON COLUMN serving.patent.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.patent.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.geo_presence.comp_id IS 'Company the presence belongs to; keyed the same as geo_comp.id so the two actually join.';
COMMENT ON COLUMN serving.geo_presence.comp_ord IS 'Sort position of the company.';
COMMENT ON COLUMN serving.geo_presence.country IS 'Country of the presence.';
COMMENT ON COLUMN serving.geo_presence.country_ord IS 'Sort position of the country.';
COMMENT ON COLUMN serving.geo_presence.ord IS 'Sort position within the country.';
COMMENT ON COLUMN serving.geo_presence.name IS 'What the presence is called.';
COMMENT ON COLUMN serving.geo_presence.c IS 'Country code.';
COMMENT ON COLUMN serving.geo_presence.val IS 'Stated value of the activity.';
COMMENT ON COLUMN serving.geo_presence.since IS 'When the presence began.';
COMMENT ON COLUMN serving.geo_presence.qty IS 'Stated quantity.';
COMMENT ON COLUMN serving.geo_presence.stage IS 'Procurement stage: in talks, bidding, offered, in production, in delivery, inducted.';
COMMENT ON COLUMN serving.geo_presence.note IS 'What is happening there. An activity is only written when its own verb is stated: a supplier procurement is not local production.';
COMMENT ON COLUMN serving.geo_presence.src IS 'URL of the statement actually used -- not the first statement in the group, which cited documents that never mentioned the claim.';
COMMENT ON COLUMN serving.geo_presence.srcnote IS 'Label for the source.';
COMMENT ON COLUMN serving.geo_presence.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.geo_presence.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.geo_comp.id IS 'Company id, matching geo_presence.comp_id.';
COMMENT ON COLUMN serving.geo_comp.ord IS 'Sort position.';
COMMENT ON COLUMN serving.geo_comp.name IS 'Display name.';
COMMENT ON COLUMN serving.geo_comp.dir IS 'rival, client or other.';
COMMENT ON COLUMN serving.geo_comp.hq IS 'Headquarters country.';
COMMENT ON COLUMN serving.geo_comp."isBf" IS 'True for the client group (Kalyani / KSSL / Bharat Forge), which is never rendered as a rival.';
COMMENT ON COLUMN serving.geo_comp.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.geo_comp.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.partner.id IS 'Partnership id.';
COMMENT ON COLUMN serving.partner.ord IS 'Sort position.';
COMMENT ON COLUMN serving.partner.label IS 'The two sides of the tie. Each side must be a named organisation, not a country or an armed force.';
COMMENT ON COLUMN serving.partner.kind IS 'Kind of tie: joint venture, MoU, supply, licence.';
COMMENT ON COLUMN serving.partner.rel IS 'Relationship direction.';
COMMENT ON COLUMN serving.partner.sig IS 'Significance score.';
COMMENT ON COLUMN serving.partner.ptype IS 'Partner type.';
COMMENT ON COLUMN serving.partner.note IS 'What the tie covers.';
COMMENT ON COLUMN serving.partner.date IS 'When it was announced.';
COMMENT ON COLUMN serving.partner.country IS 'Country involved.';
COMMENT ON COLUMN serving.partner.deal IS 'Deal value or scope where stated.';
COMMENT ON COLUMN serving.partner.insight IS 'What it means for KSSL.';
COMMENT ON COLUMN serving.partner.mean IS 'Short reading of the tie.';
COMMENT ON COLUMN serving.partner.src IS 'URL of the document that states the tie. Revived rows carry one; a row without one was never republished.';
COMMENT ON COLUMN serving.partner.srcnote IS 'Why that source clears the bar: official, or corroborated by N independent domains.';
COMMENT ON COLUMN serving.partner.cid IS 'Canonical organisation id, shared with competitor ties so the same company joins across both tables.';
COMMENT ON COLUMN serving.partner.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.partner.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.company_source.company IS 'Company the source belongs to, by display name so it joins the roster.';
COMMENT ON COLUMN serving.company_source.comp_ord IS 'Sort position of the company.';
COMMENT ON COLUMN serving.company_source.ord IS 'Sort position of the source.';
COMMENT ON COLUMN serving.company_source.url IS 'The source document.';
COMMENT ON COLUMN serving.company_source.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.company_source.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.source_registry.ord IS 'Sort position.';
COMMENT ON COLUMN serving.source_registry.company IS 'Company the source is about.';
COMMENT ON COLUMN serving.source_registry.label IS 'Human label for the source.';
COMMENT ON COLUMN serving.source_registry.url IS 'The source document.';
COMMENT ON COLUMN serving.source_registry.kind IS 'Kind of source: official, press, registry.';
COMMENT ON COLUMN serving.source_registry.origin IS 'pipeline or reference.';
COMMENT ON COLUMN serving.source_registry.updated_at IS 'When the row was last written.';

COMMENT ON COLUMN serving.ui_config.key IS 'Interface vocabulary key: category names, labels, ordering. Not data, so serving_live passes it through unfiltered.';
COMMENT ON COLUMN serving.ui_config.value IS 'The configuration value.';
