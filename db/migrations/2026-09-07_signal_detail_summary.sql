-- The article, read for the reader.
--
-- serving.signal_detail.what is ONE SENTENCE written by a prompt that was never shown
-- the article -- serving_fill's card prompt is fed the extracted propositions, so `what`
-- is a summary of a summary. Beside it the panel listed six STATEMENT rows: a six-word
-- paraphrase and the publisher's own sentence in the publisher's own language. The
-- reader got fragments in two languages and still had to open the source.
--
-- `summary` holds the English write-up extraction/signals/summarize.py builds from
-- extracted.document.text: a short paragraph, then the specifics (quantities, sums,
-- dates, programme names, people). Escaped <p>/<ul> HTML, the same contract as `what`.
--
-- NULL means "not written yet" -- every row stored before this migration, and any row
-- whose article yielded nothing worth showing. The panel falls back to `what` plus the
-- statement rows on a NULL, so this is additive and no row is ever left blank.
--
ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS summary text;

-- AND THE VIEW, WHICH DOES NOT FOLLOW ON ITS OWN.
--
-- serving_live.signal_detail is `SELECT * FROM serving.signal_detail`, and Postgres
-- expands that `*` at CREATE time into a fixed column list. Adding a column to the base
-- table does NOT add it to an existing view. This file previously claimed the opposite.
--
-- CI could not catch it: the schema job builds every object from scratch, so the view is
-- created after the column exists and picks it up. Only a database where the view already
-- exists -- staging and production, the two that matter -- would have kept serving the
-- old column list, and backend/app.py reads serving_live, not serving. The column would
-- have existed, been filled, and never reached the browser.
CREATE OR REPLACE VIEW serving_live.signal_detail AS
    SELECT * FROM serving.signal_detail WHERE origin = 'pipeline';
