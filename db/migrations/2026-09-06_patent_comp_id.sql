-- Which competitor a patent belongs to, decided once, by the thing that knows.
--
-- fetch_patents_wipo.py resolves every applicant of record against an explicit
-- allow-list -- "주식회사 풍산" to poongsan, "Krauss-Maffei Wegmann GmbH & Co. KG" to
-- knds, "Giat Industries" to nexter -- and then threw that answer away, because
-- serving.patent had no column for it. The dashboard re-derived it by matching
-- Latin word tokens between the legal assignee and the competitor's trading name.
--
-- On 26 curated reference rows that worked. On 1,157 harvested ones it loses 56:
-- 49 Korean applicants (한화에어로스페이스 주식회사, 주식회사 풍산, 주식회사 한화)
-- share no Latin token with "Hanwha Aerospace" or "Poongsan", and Krauss-Maffei
-- Wegmann shares none with "KNDS". A word-token matcher over a multilingual
-- register is a language detector, which is a mistake this repo has now paid for
-- four times.
--
-- Storing the resolved id is not a new rule. It is the removal of a second one.

ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS comp_id text;

-- serving_live.patent enumerates its columns -- the star was expanded once, at
-- creation -- so ALTER TABLE alone leaves the backend reading a view that cannot
-- see the column. Appended at the end: CREATE OR REPLACE VIEW may add a column but
-- never reorder or retype one.
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
       comp_id
  FROM serving.patent
 WHERE origin = 'pipeline'::text;
