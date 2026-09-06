-- Four competitor `site` values that pointed at news publishers, not the company.
-- Each replacement was fetched and confirmed on 2026-09-06; see company_sites.OFFICIAL.
BEGIN;
UPDATE serving.competitors SET site='https://www.gd.com/'         WHERE comp_id='general-dynamics'            AND origin='pipeline';
UPDATE serving.competitors SET site='https://bdl-india.in/'       WHERE comp_id='bharat-dynamics'             AND origin='pipeline';
UPDATE serving.competitors SET site='https://www.iai.co.il/'      WHERE comp_id='israel-aerospace-industries' AND origin='pipeline';
UPDATE serving.competitors SET site='https://www.sssdefence.com/' WHERE comp_id='sss-defence'                 AND origin='pipeline';
COMMIT;
