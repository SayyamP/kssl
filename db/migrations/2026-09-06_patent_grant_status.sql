-- Grant status, the real filing date, and a link that resolves.
--
-- serving.patent has held `status` and `filed` since it was created, and neither was
-- ever measured. fetch_patents_wipo.py's gate wrote the constants status='filed' and
-- granted=NULL for every record it saw -- all 1,157 of them -- and put the
-- PUBLICATION date into `filed`, which the tab renders as "Filed <date>".
--
-- Both were wrong, and provably so. PATENTSCOPE's result list does not print a kind
-- code, but every result row carries the record's docId in the href of its number,
-- and detail.jsf?docId= (in a cookie session) answers with Application Date,
-- Publication Date, Publication Kind, Grant Number and Grant Date. Three records
-- sampled from a live page on 2026-09-06 were ALL granted:
--
--   US 20180364015  -> grant 10254091,      kind B2
--   KR 1020180041275 -> grant 1019195030000, kind B1
--   PH 1/2018/000299 -> grant 1/2018/000299, granted 28.04.2023, kind B1
--
-- and the same PH record was filed 05.10.2018 and published 09.03.2020, so the
-- stored "Filed 2020-03-09" overstated the invention's age by seventeen months.
-- Elsewhere the gap reaches two and a half years. So "granted: 0" was not a finding.
-- It was the absence of one request.
--
-- THREE STATES, NOT TWO. status is now one of:
--
--   'granted'  detail.jsf named a grant; granted holds its DATE and grant_no its
--              number.
--   'filed'    detail.jsf was read and named no grant. This is a measurement.
--   'unknown'  detail.jsf was not read -- the harvest ran with --no-detail, or the
--              registry served a challenge instead of the record. filed is NULL.
--
-- 'unknown' is the honest answer for every row harvested before this, and the
-- frontend must render it as its own thing. It is NOT 'filed' and it is NOT zero.
--
-- WHAT WAS CLAIMED AND IS NOT TRUE. db/migrations/2026-09-06_patent_comp_id.sql says
-- the harvest loses "56: ... and Krauss-Maffei Wegmann". It does not lose them at the
-- comp_id step: all 56 KMW rows failed ATTRIBUTION and were never stored at all --
-- WIPO's applicant index truncates at 30 characters ('KRAUSS MAFFEI WEGMANN GMBH &
-- C') and no alias could equal a cut-off string. That migration is already applied
-- and is left as it stands; the resolver fix is in the pipeline, not here.

ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS published text;
ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS grant_no  text;
ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS pub_kind  text;
ALTER TABLE serving.patent ADD COLUMN IF NOT EXISTS doc_id    text;

COMMENT ON COLUMN serving.patent.status IS
  'granted / filed / unknown. granted and filed are measurements from the registry''s '
  'detail record; unknown means the record was never asked about and must not render '
  'as either of the other two.';
COMMENT ON COLUMN serving.patent.filed IS
  'Application date as the registry states it. NULL when unknown -- it is not the '
  'publication date, which is what it silently held until 2026-09-06.';
COMMENT ON COLUMN serving.patent.granted IS
  'Grant date. NULL when the record is not granted AND when it was never asked about; '
  'status says which.';
COMMENT ON COLUMN serving.patent.published IS
  'Publication date of this particular publication. Always known: it is on the result '
  'row. Publications of one invention are years apart across offices.';
COMMENT ON COLUMN serving.patent.grant_no IS 'Grant number, where one was granted.';
COMMENT ON COLUMN serving.patent.pub_kind IS
  'Publication kind code (A1, B1, B2 ...) from the detail record. The result list does '
  'not print one, which is why it could never be inferred from "no".';
COMMENT ON COLUMN serving.patent.doc_id IS
  'PATENTSCOPE record id. The only durable handle the registry prints, and what makes '
  'url a link to the record instead of a full-text search for a bare number.';
COMMENT ON COLUMN serving.patent.url IS
  'The registry record: detail.jsf?docId=. NULL when no docId was captured. It used to '
  'be result.jsf?query=FP:(<number>), a full-text search for a number with no country '
  'prefix and no kind code -- 12 of 14 sampled did not return the record.';

-- serving_live.patent enumerates its columns -- the star was expanded once, at
-- creation -- so ALTER TABLE alone leaves the backend reading a view that cannot see
-- the new columns. Appended at the end, after comp_id: CREATE OR REPLACE VIEW may add
-- a column but never reorder or retype one.
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
       doc_id
  FROM serving.patent
 WHERE origin = 'pipeline'::text;
