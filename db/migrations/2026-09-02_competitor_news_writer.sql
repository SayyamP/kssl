-- competitor_news: the two columns its writer needs.
--
-- The table shipped on 2026-09-01 with a serving_live view and no writer, so the
-- dashboard's four news panels read from a hard-coded template instead. Wiring
-- fill_competitor_news.py to it needs:
--
--   image   the article's own picture, which signal_card already resolves from the
--           page markup. Without it the panels fall back to the Unsplash stock
--           photos the fabricated version used.
--   origin  every other serving table carries it, and serving_live filters on it.
--           Without it this view is the one place a seeded row could reach the UI,
--           and the writer has no safe subset to delete.

-- Fail fast instead of queueing. competitor_news has an ON DELETE CASCADE foreign
-- key to serving.competitors, so the enrich pass's `DELETE FROM serving.competitors
-- WHERE origin='pipeline'` holds a lock on THIS table for the rest of its
-- transaction -- which spans LLM calls and runs for minutes. Without a timeout this
-- ALTER waits for ACCESS EXCLUSIVE behind it and, while waiting, blocks every reader
-- that arrives after it. Measured: it stalled the table for 2m37s before being
-- cancelled by hand. Run this when no enrich pass is mid-flight.
SET lock_timeout = '5s';

ALTER TABLE serving.competitor_news
  ADD COLUMN IF NOT EXISTS image  text,
  ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'pipeline';

-- Views fix their column list at creation, so a new column is invisible until the
-- view is replaced -- and the filter has to be added here too.
--
-- `image` goes LAST, after updated_at. CREATE OR REPLACE VIEW may only APPEND
-- columns: putting image in its natural place before updated_at is read as
-- renaming updated_at, and Postgres refuses with "cannot change name of view
-- column updated_at to image". Column order in a view is not cosmetic once the
-- view exists.
CREATE OR REPLACE VIEW serving_live.competitor_news AS
  SELECT id, comp_id, title, description, source, published_date, category,
         is_trending, url, updated_at, image
    FROM serving.competitor_news
   WHERE origin = 'pipeline';

-- ui_config had 44 rows for 22 keys -- every key stored twice, values currently
-- identical. The loader takes whichever row comes back last, so this is silent
-- today and silent corruption the day the two copies differ.
DELETE FROM serving.ui_config a
 USING serving.ui_config b
 WHERE a.key = b.key AND a.ctid > b.ctid;

ALTER TABLE serving.ui_config
  ADD CONSTRAINT ui_config_key_uniq UNIQUE (key);
