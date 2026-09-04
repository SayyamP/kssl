-- competitor_metrics: how much the corpus is talking about a company, and nothing else.
--
-- KSSL VPS_DB.docx specifies this table with share_price, currency, price_change and
-- price_change_pct beside the mention counts. Those four are NOT here, and adding them
-- later needs a data source, not a migration.
--
-- Profile.jsx records what happened the last time they existed: MARKET IMPACT printed a
-- share price of 1,428.50 INR and "-42.35 (-2.88%) Today" for EVERY company on the
-- roster -- including the private ones and the state arsenals with no listed equity at
-- all -- beside a sparkline drawn from a fixed path. This system has no market-data feed
-- of any kind. Nullable columns "for later" would hand the next person something that
-- looks fillable and is not, which is how those figures got there the first time.
--
-- WHAT IS HERE IS MEASURED. company_mentions() resolves a company's aliases to the
-- documents that name it, and the crawler dates those documents. That is a real count
-- over a real corpus.
--
-- NOT "24h", though the doc asks for it. Measured on VPS-B: 23,657 of the 23,701 dated
-- documents carry a midnight-padded timestamp, so the corpus has DAY granularity and
-- nothing finer. A rolling 24-hour window over day-stamped data drifts with the hour you
-- look at it -- an article stamped 00:00 yesterday leaves the window at 00:01 today --
-- so the number would measure the clock as much as the news. The window is whole days,
-- and window_days is stored beside the count so the figure describes itself rather than
-- relying on a label to be right.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS serving.competitor_metrics (
    comp_id             text PRIMARY KEY
                          REFERENCES serving.competitors(comp_id) ON DELETE CASCADE,
    mentions_window     integer NOT NULL CHECK (mentions_window >= 0),
    mentions_previous   integer NOT NULL CHECK (mentions_previous >= 0),
    -- How many DATED DOCUMENTS the whole corpus held in each window. Without these the
    -- percentage below is uninterpretable, which real data proved rather than theory:
    -- measured 2026-09-04, the crawler put 847 documents in the current window against
    -- 423 in the previous, so every company's raw count rose and the roster read as an
    -- industry-wide surge. It was the crawler, not the news. (547 of those 847 survive
    -- the fetch-stamp filter and are what these columns count -- the filter does its
    -- heaviest work on exactly the recent days where the crawler guesses most.)
    corpus_window       integer NOT NULL CHECK (corpus_window >= 0),
    corpus_previous     integer NOT NULL CHECK (corpus_previous >= 0),
    -- Change in SHARE OF THE CORPUS, not in raw count -- mentions/corpus this window
    -- against mentions/corpus last window. That is the only form of this number that
    -- survives the crawl doubling. NULL when the previous window held nothing: no
    -- baseline, no percentage, and "+100%" against zero is a division in a trend's
    -- clothes.
    mentions_change_pct numeric,
    window_days         integer NOT NULL CHECK (window_days > 0),
    -- The last day the window covers, which is NOT today. The crawl runs behind
    -- publication: measured on 2026-09-04, the corpus held 322 documents for 1 Sep and
    -- then 16, 19 and 1 for the three days after it. A window ending today therefore
    -- always includes two or three near-empty days, and every company on the roster
    -- reads as collapsing -- the tile would be measuring ingestion lag, not news.
    -- step_metrics anchors the window to the corpus instead, and stores where it landed.
    window_end          date NOT NULL,
    as_of               timestamptz NOT NULL,
    origin              text NOT NULL DEFAULT 'pipeline',
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW serving_live.competitor_metrics AS
  SELECT comp_id, mentions_window, mentions_previous, corpus_window,
         corpus_previous, mentions_change_pct, window_days, window_end, as_of, updated_at
    FROM serving.competitor_metrics WHERE origin = 'pipeline';
