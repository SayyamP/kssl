-- Origin country: the column, the VIEW, and the values.
--
-- 2026-09-06_competitor_country.sql added serving.competitors.country. The filter
-- still showed "Origin not established (44)" for every company, for two reasons,
-- and only the second is about data.
--
-- THE VIEW. backend/app.py reads serving_live, not serving. serving_live.competitors
-- is `SELECT * FROM serving.competitors WHERE origin = 'pipeline'`, and Postgres
-- expands that star once, when the view is created -- a later ALTER TABLE ... ADD
-- COLUMN does not reach it. So on an existing database the column existed and the
-- backend could not see it. A fresh database never had the problem: db/02 carries the
-- column and db/03 builds the view over it. CREATE OR REPLACE can append a column to
-- an existing view as long as it goes on the end, which is where ADD COLUMN puts it.
--
-- THE VALUES. From the audited 50-company workbook's Country / Region column, matched
-- on the same normalised name extraction/signals/competitor_portfolio.py uses. A
-- company this dashboard does not track matches nothing and is not inserted -- who we
-- watch is an operator's decision, not an import artefact.
--
-- Four workbook origins are a pair or a bloc: UK/US -> UK, Europe -> France,
-- Turkey/Turkiye -> Turkiye. Mapped, never split, because splitting would put BAE
-- Systems under two origins and double every count on the facet.
--
-- FILL A BLANK ONLY. The WHERE clause carries that rule so it can be checked by
-- reading, not inferred from the generator. NULL still means "not established", and
-- the filter must show such a company under that label rather than invent an origin.
SET lock_timeout = '5s';

ALTER TABLE serving.competitors ADD COLUMN IF NOT EXISTS country text;
CREATE INDEX IF NOT EXISTS competitors_country_idx ON serving.competitors (country);

CREATE OR REPLACE VIEW serving_live.competitors AS
  SELECT * FROM serving.competitors WHERE origin = 'pipeline';

-- One statement, and no temp table. A CREATE TEMP TABLE ... ON COMMIT DROP is dropped
-- the moment its implicit transaction ends, so it survives only when the whole file
-- runs inside one -- true under psql -1, not true when a job replays the file
-- statement by statement. A VALUES list inside the UPDATE needs no such footing.
UPDATE serving.competitors c
   SET country = o.country, updated_at = now()
  FROM (VALUES
    ('aweil','AWEIL','India'),
    ('nexter','Nexter (KNDS France)','France'),
    ('kndsgermany','KNDS Germany','Germany'),
    ('baesystems','BAE Systems','UK'),
    ('leonardo','Leonardo','Italy'),
    ('rheinmetall','Rheinmetall','Germany'),
    ('hanwha','Hanwha (Aerospace/Group)','South Korea'),
    ('elbitsystems','Elbit Systems','Israel'),
    ('generaldynamics','General Dynamics','US'),
    ('norinco','NORINCO','China'),
    ('tataadvancedsystems','Tata Advanced Systems','India'),
    ('mahindradefence','Mahindra Defence','India'),
    ('lt','Larsen & Toubro (L&T)','India'),
    ('patria','Patria','Finland'),
    ('supacat','Supacat','UK'),
    ('otokar','Otokar','Turkiye'),
    ('paramount','Paramount Group','South Africa'),
    ('roshel','Roshel','Canada'),
    ('idv','IDV (Iveco Defence)','Italy'),
    ('plrsystems','PLR Systems (IWI+Adani)','India'),
    ('kalashnikovconcern','Kalashnikov Concern','Russia'),
    ('munitionsindia','Munitions India Ltd (MIL)','India'),
    ('bharatdynamics','Bharat Dynamics Ltd (BDL)','India'),
    ('hsw','Huta Stalowa Wola (HSW)','Poland'),
    ('oshkoshdefense','Oshkosh Defense','US'),
    ('poongsan','Poongsan','South Korea'),
    ('nammo','Nammo','Norway'),
    ('sigsauer','SIG Sauer','US'),
    ('sssdefence','SSS Defence','India'),
    ('rafaeladvanceddefensesystems','Rafael Advanced Defense Systems','Israel'),
    ('kongsberg','KONGSBERG','Norway'),
    ('mbda','MBDA','France'),
    ('iai','Israel Aerospace Industries (IAI)','Israel'),
    ('l3harris','L3Harris','US'),
    ('northropgrumman','Northrop Grumman','US'),
    ('lockheedmartin','Lockheed Martin','US'),
    ('rtx','RTX (Raytheon)','US'),
    ('saab','SAAB','Sweden'),
    ('thyssenkruppmarinesystems','Thyssenkrupp Marine Systems','Germany'),
    ('naval','Naval Group','France'),
    ('huntingtoningallsindustries','Huntington Ingalls Industries','US'),
    ('babcock','Babcock','UK'),
    ('diehldefence','Diehl Defence','Germany'),
    ('aerovironment','AeroVironment','US'),
    ('anduril','Anduril','US'),
    ('uvisionair','UVision Air','Israel'),
    ('adanidefence','Adani Defence','India'),
    ('brahmosaerospace','BrahMos Aerospace','India'),
    ('premierexplosives','Premier Explosives','India'),
    ('solarindustries','Solar Industries','India')
       ) AS o(k, company, country)
 -- the normalised key computed in SQL, so the join is checkable by reading this file
 -- rather than by trusting the script that wrote it
 WHERE o.k = regexp_replace(
               regexp_replace(
                 regexp_replace(lower(c.name), '\(.*?\)', ' ', 'g'),
                 '\y(ltd|limited|inc|corp|corporation|plc|gmbh|sa|ag|as|oyj|private|pvt|group|holdings|company|co)\y',
                 ' ', 'g'),
               '[^a-z0-9]+', '', 'g')
   AND c.origin = 'pipeline'
   AND (c.country IS NULL OR c.country = '');
