-- One country, one key. 'India' and 'IN' are the same patent office.
--
-- MEASURED ON PRODUCTION 2026-09-06. serving.patent holds 22 distinct `country` values
-- and two pairs of them are the same office written two ways:
--
--     India   21 rows      IN    10 rows
--     US     354 rows      USA    2 rows
--
-- Nothing downstream knows that. dataset.js keys its per-holder country set on the raw
-- string, so a holder that filed in Bengaluru under both spellings is reported as
-- present in two jurisdictions; the Patents tab's country chips count the same office
-- twice; and any future filter, facet or map join splits 31 Indian filings into a 21
-- and a 10 that never meet. It is the same class of fault as the client keyed "KSSL" in
-- one place and by slug everywhere else: a display label used as a join key.
--
-- ISO 3166 alpha-2 IS THE CANONICAL FORM, because 20 of the 22 values already are one
-- and it is what the registry itself prints. So the minority spellings move, not the
-- majority: 21 rows and 2 rows are rewritten, 364 are left alone.
--
-- NOTHING IS INVENTED. Only the aliases actually observed in this corpus are touched.
-- An unrecognised country string is left exactly as it is -- a guessed code would
-- publish a jurisdiction nobody recorded, which is worse than a duplicate key.
--
-- THE UI DOES NOT DEPEND ON THIS HAVING RUN. patents.js normCountry() folds the same
-- aliases in the display layer, so the tab is correct before this is applied and this
-- costs nothing after. That is deliberate: deploy.sh runs no migrations, and a fix that
-- is only in a migration is a fix that reaches production whenever someone remembers.
-- After this runs, normCountry() still earns its place by catching the next alias the
-- harvest invents.
--
-- NOT RUN. Two UPDATEs, 23 rows, no schema change; reversible only in the sense that
-- the rows can be written back if the original spelling mattered to anything, which it
-- does not -- no row's identity is its country, and "no" is the unique key.

BEGIN;

-- Say what will move before moving it, so the apply log records the counts.
SELECT country, count(*) AS rows
  FROM serving.patent
 WHERE country IN ('India', 'USA', 'IN', 'US')
 GROUP BY country
 ORDER BY country;

UPDATE serving.patent SET country = 'IN', updated_at = now()
 WHERE country = 'India';

UPDATE serving.patent SET country = 'US', updated_at = now()
 WHERE country = 'USA';

-- The check that this file's whole claim rests on: after it, no two rows describe the
-- same office under different names. Fails the transaction if an alias survived.
DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM serving.patent
   WHERE country IN ('India', 'USA', 'United States', 'UK', 'Korea');
  IF n > 0 THEN
    RAISE EXCEPTION 'country vocabulary still holds % aliased row(s)', n;
  END IF;
END $$;

COMMENT ON COLUMN serving.patent.country IS
  'Patent office, ISO 3166 alpha-2 as the registry prints it. Held India/IN and US/USA '
  'as four values for two offices until 2026-09-06; patents.js normCountry() folds any '
  'that come back.';

COMMIT;
