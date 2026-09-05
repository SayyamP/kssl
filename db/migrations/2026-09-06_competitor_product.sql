-- competitor_product: the OTHER side of every comparison, which the schema has never
-- held either.
--
-- 2026-09-05 gave the client's own products a table (serving.client_product) because
-- the corpus holds no document in which KSSL states its own specifications. The
-- competitor side had the mirror-image problem and it was less visible: a competitor
-- value DID appear on screen, it just came from the demo archive, where a number never
-- had to name its source. So the two halves of a matchup were sourced to different
-- standards and only one of them could be checked.
--
-- The source is an audited 50-company workbook: 1,083 product rows, 1,183 URLs,
-- portfolio/Defence_Competitors_50_2026-09-05.xlsx. Cross-checking it before import
-- found three faults this table is shaped to keep out:
--
--   * 134 Nammo rows whose specification cell describes POONGSAN's portfolio
--     verbatim; on 117 of them that sentence was the entire cell. Poongsan's own
--     37 rows do not carry it, which is how we know it was a paste.
--   * 8 Leonardo rows that are IDV vehicles sourced only to idvgroup.com, with IDV
--     also among the 50 -- one vehicle, two makers, counted twice.
--   * 17 rows resting solely on a document-upload host, 16 of them Munitions India.
--
-- 650 of the 1,083 rows survive. What refuses them is engine/source_tiers.publishable,
-- the SAME gate the client side uses, called with product_maker so that a maker's site
-- is official about its own product and a news mention about a rival's -- otherwise one
-- company's marketing would set another's numbers. `evidence` records which branch of
-- that gate admitted each row, so a reader can see whether a value stands on the
-- manufacturer's word or on two independent outlets agreeing.
--
-- origin='pipeline' on purpose, and the opposite of client_product. The client's
-- statement about itself is a reference fact the corpus cannot rebuild. A competitor's
-- catalogue is not: the crawl reaches these companies' sites, so this table is a floor
-- the corpus is expected to grow past, and competitor_portfolio.py --apply replaces the
-- pipeline rows whole on each run.
--
-- No serving_live view: the backend does not read this table. Its consumer is
-- revive_matchups.py, which reads it directly, exactly as it reads client_product.
--
-- Stop extraction-enrich-1 before applying, as for every serving.* change (the pass
-- holds locks across minutes of LLM calls; measured 2m37s wait on 2026-09-02).
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS serving.competitor_product (
    product_id    text PRIMARY KEY,
    ord           integer NOT NULL,
    company       text NOT NULL,
    name          text NOT NULL,
    file_category text NOT NULL,
    cat           text,
    "catKey"      text,
    specs         jsonb NOT NULL DEFAULT '[]'::jsonb,
    features      jsonb NOT NULL DEFAULT '[]'::jsonb,
    sources       jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- {why, tier, independent}: which branch of publishable() admitted this row.
    -- A row on screen whose evidence says 'news' with independent=2 is a different
    -- claim from one whose evidence says 'official', and the UI must be able to say so.
    evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
    origin        text NOT NULL CHECK (origin IN ('reference', 'pipeline')),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS competitor_product_catkey_idx
    ON serving.competitor_product ("catKey");
CREATE INDEX IF NOT EXISTS competitor_product_company_idx
    ON serving.competitor_product (company);
