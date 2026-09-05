-- Origin for the six companies the dashboard holds under a shorter name.
--
-- 2026-09-06_competitor_country_backfill.sql matched on a normalised name and left
-- eight of forty-four reading "Origin not established". The join is not wrong; the two
-- sides simply spell six of these companies differently, and one carries an HTML
-- entity:
--
--   dashboard                 workbook                            key that was emitted
--   Hanwha Aerospace          Hanwha (Aerospace/Group)            hanwha
--   Israel Aerospace Indust.  Israel Aerospace Industries (IAI)   iai
--   Iveco                     IDV (Iveco Defence)                 idv
--   Kalashnikov               Kalashnikov Concern                 kalashnikovconcern
--   Larsen &amp; Toubro       Larsen & Toubro (L&T)               larsentoubro
--   Raytheon                  RTX (Raytheon)                      rtx
--
-- The normaliser strips a parenthetical before anything else, so "Nexter (KNDS
-- France)" reduces to "nexter" and never reaches the alias map that was meant to catch
-- it. `Larsen &amp; Toubro` is a second, unrelated fault: the stored name carries an
-- HTML entity, so the normaliser reads a-m-p as letters of the name and produces
-- "larsenamptoubro". Both keys are listed below; whichever the row has, it matches.
--
-- TWO COMPANIES ARE DELIBERATELY LEFT WITHOUT AN ORIGIN.
--
--   KNDS   The workbook has "Nexter (KNDS France)" as France and "KNDS Germany" as
--          Germany. The dashboard tracks the merged Franco-German group under the bare
--          name. Picking one of its two halves would be a guess, and picking both is
--          what the union filter did that started all of this.
--
--   IWI    The only workbook row naming IWI is "PLR Systems (IWI+Adani)", India --
--          which is the Indian joint venture, not Israel Weapon Industries. Reading a
--          JV's country onto its foreign parent is exactly the fault that put Bharat
--          Dynamics under France.
--
-- "Origin not established" is the right answer for both, and the filter already has a
-- place to put them. Adding a company to the audited workbook under the name the
-- dashboard uses is how these get resolved, not a rule in here.
--
-- Fill a blank only, same as the backfill it follows.
SET lock_timeout = '5s';

UPDATE serving.competitors c
   SET country = o.country, updated_at = now()
  FROM (VALUES
    ('hanwhaaerospace',        'Hanwha Aerospace',            'South Korea'),
    ('israelaerospaceindustries', 'Israel Aerospace Industries', 'Israel'),
    ('iveco',                  'Iveco',                       'Italy'),
    ('kalashnikov',            'Kalashnikov',                 'Russia'),
    ('larsenamptoubro',        'Larsen &amp; Toubro',         'India'),
    ('larsentoubro',           'Larsen & Toubro',             'India'),
    ('raytheon',               'Raytheon',                    'US')
       ) AS o(k, company, country)
 -- the same normalisation the backfill uses, computed here so this file can be
 -- checked by reading it rather than by trusting the script that wrote it
 WHERE o.k = regexp_replace(
               regexp_replace(
                 regexp_replace(lower(c.name), '\(.*?\)', ' ', 'g'),
                 '\y(ltd|limited|inc|corp|corporation|plc|gmbh|sa|ag|as|oyj|private|pvt|group|holdings|company|co)\y',
                 ' ', 'g'),
               '[^a-z0-9]+', '', 'g')
   AND c.origin = 'pipeline'
   AND (c.country IS NULL OR c.country = '');
