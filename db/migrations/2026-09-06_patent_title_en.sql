-- An English patent title, WITHOUT throwing away the one the office published.
--
-- 169 of the 1,183 rows in serving.patent carry a title that is not in English --
-- German, French, Spanish and Korean -- because a patent office publishes a title in
-- its own language and the harvest stores what it is given. The Patents tab is read in
-- English, and the title is the only field on the card that says WHAT the filing is:
-- assignee, date, country and IPC code say who, when and where. So a sixth of the tab
-- was rows a reader could not judge.
--
-- TWO COLUMNS, NOT ONE, AND THE ORIGINAL IS NEVER OVERWRITTEN. `title` is the legal
-- name the office published the invention under and the string that finds the record
-- again in that office's register; a translation written over it cannot be undone and
-- cannot be checked against its own source. The English rendering therefore gets its
-- own column and the card shows both -- translated line first, the office's own title
-- underneath.
--
-- WHY THE SECOND COLUMN IS A VERSION AND NOT A BOOLEAN. This is the same marker
-- 2026-09-06_signal_detail_translated.sql added, for the same reason and with the same
-- rule. That backfill selected `ORDER BY d.id LIMIT 200` with nothing recording what it
-- had already done, and the entrypoint ran it every cycle: the same first 200 of 949
-- cards were re-asked for ever, cards 201..949 were never visited, and roughly 17
-- minutes of farm time per cycle produced no change at all. `title_en_v` holds the
-- prompt version (translate.PROMPT_VERSION) the row was last examined under, so:
--
--   * the pass selects rows whose stamp differs from the current version -- the window
--     ADVANCES instead of restarting;
--   * a row is stamped even when nothing was written (the title was already English, or
--     the translation was refused), or the English rows would be re-examined for ever;
--   * a finished corpus costs nothing;
--   * bumping PROMPT_VERSION re-queues all 1,183 rows for exactly one pass.
--
-- WHAT NULL MEANS IN EACH. title_en NULL = there is no translation to show, and the UI
-- falls back to `title`. That covers three different situations, and title_en_v is what
-- tells them apart: never looked at (title_en_v NULL), looked at and found already
-- English, and looked at and the translation refused. The UI does not need to tell them
-- apart -- it shows the source title in all three -- but an operator does, and a
-- boolean could not have said.
--
-- NOT RUN. Apply with the two 2026-09-06 patent migrations already applied: the view
-- below enumerates comp_id, published, grant_no, pub_kind and doc_id, which those two
-- added. On a database that has neither, the CREATE OR REPLACE VIEW is what will fail,
-- loudly, before anything is written.

ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS title_en   text;
ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS title_en_v text;

COMMENT ON COLUMN serving.patent.title IS
  'The title exactly as the office published it, in the language it published it in. '
  'Never translated in place: it is the legal name of the invention and the string that '
  'finds the record in that office''s register. 169 of 1,183 are not English.';
COMMENT ON COLUMN serving.patent.title_en IS
  'English rendering of title, written by extraction/signals/patent_titles.py. NULL '
  'means there is nothing to show and the UI falls back to title -- which covers "never '
  'examined", "already English" and "translation refused" alike; title_en_v says which.';
COMMENT ON COLUMN serving.patent.title_en_v IS
  'Prompt version (translate.PROMPT_VERSION) this row''s title was last examined under; '
  'NULL means never. Drives the pass''s window so it advances instead of re-asking the '
  'same rows every cycle. Bookkeeping: not served to the browser.';

-- The window's own index: the pass reads WHERE title_en_v IS DISTINCT FROM <version>
-- over the pipeline rows only (the 26 curated reference rows are not the harvest's).
CREATE INDEX IF NOT EXISTS patent_title_en_v_idx
    ON serving.patent (title_en_v)
    WHERE origin = 'pipeline';

-- serving_live.patent ENUMERATES ITS COLUMNS -- the star was expanded once, at creation
-- -- so ALTER TABLE alone leaves the backend reading a view that cannot see the new
-- column, and the backend reads the VIEW (app.SCHEMA is serving_live unless
-- KSSL_SERVE_ORIGIN=all). Appended at the end: CREATE OR REPLACE VIEW may add a column
-- but never reorder or retype one.
--
-- title_en_v is deliberately NOT exposed. It is bookkeeping for the pass, like
-- serving.signal_detail.translated, which is likewise not in the backend's field list.
-- What the dashboard can read is decided here; what may be written is decided by the
-- table above.
CREATE OR REPLACE VIEW serving_live.patent AS
SELECT ord,
       assignee_ord,
       no,
       title,
       assignee,
       status,
       filed,
       granted,
       country,
       ipc,
       abstract,
       area,
       threat,
       relev,
       url,
       p,
       origin,
       updated_at,
       comp_id,
       published,
       grant_no,
       pub_kind,
       doc_id,
       title_en
  FROM serving.patent
 WHERE origin = 'pipeline'::text;
