-- competitors.country: where a company IS FROM, as one word.
--
-- The Competitor sidebar's country filter listed Bharat Dynamics, Iveco, Lockheed
-- Martin and MBDA under "France (6)". It was not broken: companyCountries() unions
-- the geo footprint, global_locations and the country-parts of the hq string, so the
-- control meant "recorded in France" while its label read "from France". Beside a
-- HEADQUARTERS field saying "Bethesda, Md, USA" there is only one way to read that.
--
-- Bharat Dynamics earned its France row from this sentence:
--     "Bharat Dynamics Limited produces MILAN-2T under license from
--      MBDA Missile Systems, France"
-- France is the LICENSOR's country; BDL builds MILAN-2T in India. (fill_geo_footprint's
-- entailment gate refuses that sentence today, so the row predates the gate.)
--
-- Origin cannot be derived from hq. Measured on the live dataset: 37 of 155 competitors
-- carry an hq at all, and the strings are "Bethesda, Md, USA", "Hyderabad, Telangana",
-- "Arlington, Virginia" -- a comma-tail yields "USA" for one and "Telangana" for the
-- next. Guessing a country from a region name is how "Virginia" became a country the
-- last time this was attempted, so origin gets its own column and is FILLED FROM A
-- SOURCE: the audited 50-company workbook's Country / Region column.
--
-- NULL means "not established", and the filter must show such a company under
-- "unknown" rather than inventing an origin for it.
--
-- Stop extraction-enrich-1 before applying, as for every serving.* change.
SET lock_timeout = '5s';

ALTER TABLE serving.competitors ADD COLUMN IF NOT EXISTS country text;
CREATE INDEX IF NOT EXISTS competitors_country_idx ON serving.competitors (country);
