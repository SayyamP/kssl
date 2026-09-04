-- documents: the corpus subset that lives ON VPS-B so the queue path can run entirely here.
--
-- WHY THIS EXISTS. The extraction queue path (route.py enqueue -> run_node worker -> store_pg)
-- writes spans + the queue done-mark in ONE transaction on ONE connection (KSSL_CORPUS_DSN). That
-- requires the document text, the extract_queue, and extracted.* to be colocated. The crawler's
-- 81 GB `documents` table lives at the data centre; sync_documents.py copies the small, dated,
-- relevance-gated subset we actually extract into THIS table on VPS-B. route.py reads exactly these
-- columns (DOC_COLS + fetched_at, text_len); nothing scans a large column it does not need.
CREATE TABLE IF NOT EXISTS documents (
  document_id  TEXT PRIMARY KEY,
  url          TEXT,
  source_id    TEXT,
  language     TEXT,
  title        TEXT,
  main_text    TEXT NOT NULL,
  published_at TEXT,                 -- the crawler's PROVEN publication date; feeds the serving date-gate
  fetched_at   TEXT NOT NULL,        -- when the crawler fetched it; queue ordering key (crawl_ts)
  text_len     INTEGER NOT NULL,
  synced_at    TIMESTAMPTZ DEFAULT now()
);
-- enqueue selects the newest un-queued rows; this index keeps that scan cheap as the table grows.
CREATE INDEX IF NOT EXISTS documents_fetched_idx ON documents (fetched_at DESC);
