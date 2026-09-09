-- The cursor that lets the summary pass advance.
--
-- serving.signal_detail.summary was added on 2026-09-07 and is written only inside the
-- INSERT that creates a card, so the 2,190 details that existed before it have no code
-- path that would ever fill them. serving_fill.py --resummarise is that path; this column
-- is what stops it re-billing the same rows for ever.
--
-- `summary IS NULL` cannot be the cursor. NULL is also what a legitimate refusal writes:
-- an article under 200 characters, or a summary that came back in the source language
-- after a retry. Those rows would be re-asked every 120 seconds by six replicas. That is
-- precisely the defect 9dee205 fixed for translation, where the same first 200 of 949
-- cards were re-asked every cycle -- roughly 17 minutes of farm time per replica, for no
-- change -- and the rest were never reached at all.
--
-- So this holds the PROMPT VERSION the row was last summarised under, exactly as
-- `translated` does. A refusal is recorded. Bumping summarize.PROMPT_VERSION re-queues
-- the corpus for exactly one pass.
ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS summarised text;

-- AND THE VIEW, WHICH DOES NOT FOLLOW ON ITS OWN.
--
-- Postgres expands `SELECT *` at CREATE VIEW time into a fixed column list, so
-- serving_live.signal_detail does not gain a column because serving.signal_detail did.
-- CI cannot catch this -- the schema job builds every object from scratch, so its view is
-- created after the ALTER -- and only a database where the view already exists, which is
-- both real environments, keeps serving the old list. The 2026-09-07 migration shipped
-- claiming the opposite and was corrected before it reached either box.
CREATE OR REPLACE VIEW serving_live.signal_detail AS
    SELECT * FROM serving.signal_detail WHERE origin = 'pipeline';
