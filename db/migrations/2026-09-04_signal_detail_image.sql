-- signal_detail.image: the picture the card already has.
--
-- serving_fill.py resolves an article's lead image once per document and writes it to
-- serving.signal_card.image. The detail panel behind that card -- the full-height read,
-- where a picture is worth more than it is in a list row -- had nowhere to put it, so
-- the column is added and the SAME resolved value is written to both.
--
-- Fail fast rather than queue. serving.competitor_news cascades from serving.competitors,
-- and the enrich pass deletes every pipeline competitor row and then spends minutes on
-- LLM calls before committing. An ALTER that arrives mid-pass waits for ACCESS EXCLUSIVE
-- and blocks every reader that queues behind it -- measured at 2m37s on 2026-09-02.
-- This table is not in that cascade, but the habit is the point: stop the enrich
-- container, or run this when no pass is in flight.
SET lock_timeout = '5s';

ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS image text;

-- The view is SELECT *, so it does not see a new column until it is replaced. The
-- replacement APPENDS image after updated_at, which is the only direction
-- CREATE OR REPLACE VIEW allows: naming it anywhere earlier is read as renaming the
-- column that already sits there, and Postgres refuses.
CREATE OR REPLACE VIEW serving_live.signal_detail AS
  SELECT * FROM serving.signal_detail WHERE origin = 'pipeline';
