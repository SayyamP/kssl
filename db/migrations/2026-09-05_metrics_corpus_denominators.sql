-- competitor_metrics: window_end and the two corpus denominators.
--
-- These belong in 2026-09-04_competitor_metrics.sql, and I put them there -- by editing
-- that file after it had already been applied to production. It cannot work: the runner
-- keys the ledger on FILENAME, so an edited migration is invisible to every database that
-- already recorded it. Production ran the original at 09:09 UTC on 4 Sep and would have
-- carried the old six-column table into a deploy whose code writes nine, failing
-- step_metrics on every pass with "column does not exist".
--
-- The rule the ledger implies, stated plainly: once a migration has run anywhere, it is
-- history. Corrections are new files. The original has been restored to exactly what
-- production applied, and this is the correction.
--
-- WHY THE COLUMNS EXIST, measured on the real corpus rather than reasoned about:
--
--   window_end        The crawl runs behind publication. The corpus held 322 documents
--                     for 1 Sep and then 16, 19 and 1, so a window ending TODAY always
--                     covered days the crawler had barely reached and every company on
--                     the roster read as collapsing -- BAE -88%, Saab -73%. The window
--                     now ends where the corpus does, and stores where that was.
--   corpus_window     With the window fixed the roster flipped to a uniform surge:
--   corpus_previous   Boeing +104%, Airbus +105%. The crawler had put 847 documents in
--                     the current window against 423 in the previous, so every raw count
--                     roughly doubled. The percentage now compares SHARE of the corpus,
--                     and both denominators are stored so a reader can check it.
--
-- Existing rows carry counts taken against a calendar window with no denominators. There
-- is nothing to backfill them from, and a made-up denominator is worse than none, so the
-- defaults are 0 and the next enrich pass overwrites every row -- step_metrics rebuilds
-- the whole table each time. The NOT NULL is added after the default has filled them.
SET lock_timeout = '5s';

ALTER TABLE serving.competitor_metrics
  ADD COLUMN IF NOT EXISTS corpus_window   integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS corpus_previous integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS window_end      date;

-- window_end has no sane default, so it is filled from the row's own as_of before the
-- NOT NULL goes on. That is the day the pass ran, which is what the old rows meant.
UPDATE serving.competitor_metrics SET window_end = as_of::date WHERE window_end IS NULL;

DO $$
BEGIN
  ALTER TABLE serving.competitor_metrics ALTER COLUMN window_end SET NOT NULL;
EXCEPTION WHEN others THEN
  RAISE NOTICE 'window_end already NOT NULL';
END $$;

-- The DEFAULT was only a device to satisfy NOT NULL while the column was being added to
-- rows that already existed; the writer always supplies a value. Leaving it on makes a
-- migrated database differ from one built out of db/*.sql, which db/schema_snapshot.txt
-- compares -- and it caught exactly that here.
ALTER TABLE serving.competitor_metrics
  ALTER COLUMN corpus_window   DROP DEFAULT,
  ALTER COLUMN corpus_previous DROP DEFAULT;

ALTER TABLE serving.competitor_metrics
  DROP CONSTRAINT IF EXISTS competitor_metrics_corpus_window_check,
  ADD  CONSTRAINT competitor_metrics_corpus_window_check   CHECK (corpus_window >= 0);
ALTER TABLE serving.competitor_metrics
  DROP CONSTRAINT IF EXISTS competitor_metrics_corpus_previous_check,
  ADD  CONSTRAINT competitor_metrics_corpus_previous_check CHECK (corpus_previous >= 0);

-- The view fixes its column list at creation; the new columns are invisible until it is
-- replaced, and CREATE OR REPLACE VIEW may only APPEND, so they go last.
CREATE OR REPLACE VIEW serving_live.competitor_metrics AS
  SELECT comp_id, mentions_window, mentions_previous, mentions_change_pct,
         window_days, as_of, updated_at, corpus_window, corpus_previous, window_end
    FROM serving.competitor_metrics WHERE origin = 'pipeline';
