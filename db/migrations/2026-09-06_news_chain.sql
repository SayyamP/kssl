-- The running story an article belongs to, and how it relates to the one before it.
--
-- Written by extraction/signals/news_chain.py from spans the extraction layer already
-- typed. story_key is the designator two articles share; continues_url points at the
-- article this one develops; duplicate_of_url points at the article this one merely
-- reprints elsewhere. All three are null on an article that stands alone, and null is
-- the honest answer -- an unthreaded article is not a thread of one.
--
-- The URLs are the join, not the ids. serving.competitor_news is rebuilt by
-- fill_competitor_news.py with a DELETE and re-INSERT, so `id` changes under a row
-- that has not; `url` is what identifies the article across a rebuild.

ALTER TABLE serving.competitor_news ADD COLUMN IF NOT EXISTS story_key text;
ALTER TABLE serving.competitor_news ADD COLUMN IF NOT EXISTS continues_url text;
ALTER TABLE serving.competitor_news ADD COLUMN IF NOT EXISTS duplicate_of_url text;
ALTER TABLE serving.competitor_news ADD COLUMN IF NOT EXISTS chain_evidence jsonb;

-- serving_live.competitor_news was created as SELECT * and Postgres expanded the star
-- ONCE, at creation. ALTER TABLE does not reach a view, so without this the backend
-- would read serving_live, not find the columns, and take the whole dashboard down --
-- which is exactly what the `country` column did on 2026-09-06. New columns go at the
-- END: CREATE OR REPLACE VIEW may append but never reorder or retype.
CREATE OR REPLACE VIEW serving_live.competitor_news AS
SELECT id,
       comp_id,
       title,
       description,
       source,
       published_date,
       category,
       is_trending,
       url,
       updated_at,
       image,
       story_key,
       continues_url,
       duplicate_of_url,
       chain_evidence
  FROM serving.competitor_news
 WHERE origin = 'pipeline'::text;
