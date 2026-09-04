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
    -- NULL when the previous window is empty: no baseline, no percentage. A change of
    -- "+100%" against zero is a division dressed up as a trend.
    mentions_change_pct numeric,
    window_days         integer NOT NULL CHECK (window_days > 0),
    as_of               timestamptz NOT NULL,
    origin              text NOT NULL DEFAULT 'pipeline',
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW serving_live.competitor_metrics AS
  SELECT comp_id, mentions_window, mentions_previous, mentions_change_pct,
         window_days, as_of, updated_at
    FROM serving.competitor_metrics WHERE origin = 'pipeline';
