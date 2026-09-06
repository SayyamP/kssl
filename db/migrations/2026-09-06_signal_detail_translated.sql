-- The translation backfill had no done-marker, so it never advanced.
--
-- serving_fill.py --retranslate selected `ORDER BY d.id LIMIT :limit` with nothing
-- recording which cards it had already done. The entrypoint runs it with --limit 200
-- every signals cycle, so of 949 served cards the same first 200 were re-asked on
-- every pass and cards 201..949 were never visited at all. Each non-English card costs
-- two model calls a cycle (lead-ins, then prose), so roughly 66 cards x 2 calls x ~8s
-- was ~17 minutes of farm time per cycle, per replica, producing no change -- while
-- two thirds of the corpus stayed untranslated for good.
--
-- This column is the marker: it holds the prompt version the row was last translated
-- under. The pass selects rows where it differs from the current version, so the
-- window advances, a finished corpus costs nothing, and bumping PROMPT_VERSION in
-- translate.py re-queues everything for exactly one pass.
--
-- It is not the content-addressed cache table that was argued against and rejected:
-- there is no second copy of any text here, only a version stamp on the row that
-- already holds the translation.
ALTER TABLE serving.signal_detail
    ADD COLUMN IF NOT EXISTS translated text;

COMMENT ON COLUMN serving.signal_detail.translated IS
    'Prompt version (translate.PROMPT_VERSION) this row''s lead-ins were last '
    'translated under; NULL means never. Drives the --retranslate window so it '
    'advances instead of re-asking the same first N cards every cycle.';

CREATE INDEX IF NOT EXISTS signal_detail_translated_idx
    ON serving.signal_detail (translated)
    WHERE origin = 'pipeline';
