/* THE COUNTRY TABLE, and the two rules that read it.

   Moved out of components/geoMap/GeoMap.jsx on 2026-09-06 so that a plain node test can
   import it: GeoMap.jsx imports leaflet at the top, so test_geo_map.mjs had to slice the
   table out of the file's TEXT and evaluate it. A test that reads source as a string
   cannot notice a syntax error in the half it did not slice.

   GeoMap.jsx re-exports geoCountryCoords and geoPlotPlan, so nothing else had to change.
*/
import { hqParts } from "./countryFacet.js";

/* WHERE A COUNTRY IS -- looked up, never guessed.

   This table used to have a fallback that hashed the country name into a lat/lng:
     lat = 10 + (abs(hash % 50) - 25); lng = 20 + (abs((hash >> 3) % 120) - 60)
   Sixteen of the fifty-two countries the pipeline serves missed the table and were
   drawn at those made-up coordinates -- a band covering the Atlantic and Africa, so
   Russia, Norway, Finland and Taiwan appeared in the Gulf of Guinea. The hash also
   hid the staleness it caused: a country the table did not know still produced a
   confident-looking dot, so nobody ever learned the table needed extending.

   There is no fallback now. A country with no entry is NOT drawn; it is counted and
   named on the map instead (see geoPlotPlan). Add coordinates here when the corpus
   reaches somewhere new -- the notice tells you when that has happened. */
const COUNTRY_COORDS = {
  Afghanistan: [33.9391, 67.7100],
  Argentina: [-38.4161, -63.6167],
  Armenia: [40.0691, 45.0382],
  Australia: [-25.2744, 133.7751],
  Austria: [47.5162, 14.5501],
  Bahrain: [26.0667, 50.5577],
  Bangladesh: [23.6850, 90.3563],
  Belgium: [50.5039, 4.4699],
  Brazil: [-14.2350, -51.9253],
  Canada: [56.1304, -106.3468],
  China: [35.8617, 104.1954],
  Czechia: [49.8175, 15.4730],
  "Czech Republic": [49.8175, 15.4730],
  Denmark: [56.2639, 9.5018],
  Egypt: [26.8206, 30.8025],
  Estonia: [58.5953, 25.0136],
  Ethiopia: [9.1450, 40.4897],
  Finland: [61.9241, 25.7482],
  France: [46.2276, 2.2137],
  Germany: [51.1657, 10.4515],
  Ghana: [7.9465, -1.0232],
  Greece: [39.0742, 21.8243],
  Hungary: [47.1625, 19.5033],
  India: [20.5937, 78.9629],
  Indonesia: [-0.7893, 113.9213],
  Iraq: [33.2232, 43.6793],
  Israel: [31.0461, 34.8516],
  Italy: [41.8719, 12.5674],
  Japan: [36.2048, 138.2529],
  Kazakhstan: [48.0196, 66.9237],
  Kenya: [-1.2921, 36.8219],
  Korea: [35.9078, 127.7669],
  "South Korea": [35.9078, 127.7669],
  "Republic of Korea": [35.9078, 127.7669],
  KSA: [23.8859, 45.0792],
  Kuwait: [29.3117, 47.4818],
  Malaysia: [4.2105, 101.9758],
  Mexico: [23.6345, -102.5528],
  Morocco: [31.7917, -7.0926],
  Netherlands: [52.1326, 5.2913],
  "The Netherlands": [52.1326, 5.2913],
  "New Zealand": [-40.9006, 174.8860],
  Nigeria: [9.0820, 8.6753],
  Norway: [60.4720, 8.4689],
  Oman: [21.5126, 55.9233],
  Pakistan: [30.3753, 69.3451],
  Philippines: [12.8797, 121.7740],
  Poland: [51.9194, 19.1451],
  Qatar: [25.3548, 51.1839],
  Romania: [45.9432, 24.9668],
  Russia: [61.5240, 105.3188],
  "Russian Federation": [61.5240, 105.3188],
  "Saudi Arabia": [23.8859, 45.0792],
  Singapore: [1.3521, 103.8198],
  "South Africa": [-30.5595, 22.9375],
  Spain: [40.4637, -3.7492],
  "Sri Lanka": [7.8731, 80.7718],
  Sweden: [60.1282, 18.6435],
  Taiwan: [23.6978, 120.9605],
  Tanzania: [-6.3690, 34.8888],
  Thailand: [15.8700, 100.9925],
  Turkey: [38.9637, 35.2433],
  Uganda: [1.3733, 32.2903],
  UAE: [23.4241, 53.8478],
  "United Arab Emirates": [23.4241, 53.8478],
  UK: [55.3781, -3.4360],
  "United Kingdom": [55.3781, -3.4360],
  Ukraine: [48.3794, 31.1656],
  USA: [37.0902, -95.7129],
  "United States": [37.0902, -95.7129],
  "United States of America": [37.0902, -95.7129],
  Vietnam: [14.0583, 108.2772],
  Algeria: [28.0339, 1.6596],
  Azerbaijan: [40.1431, 47.5769],
  Bulgaria: [42.7339, 25.4858],
  Chile: [-35.6751, -71.5430],
  Colombia: [4.5709, -74.2973],
  Croatia: [45.1000, 15.2000],
  Ireland: [53.4129, -8.2439],
  Jordan: [30.5852, 36.2384],
  Latvia: [56.8796, 24.6032],
  Lithuania: [55.1694, 23.8813],
  Slovakia: [48.6690, 19.6990],
  Slovenia: [46.1512, 14.9955],
  Switzerland: [46.8182, 8.2275],
};

/* Not countries. The footprint table carries continent-level rows, and a continent
   has no honest point: "Europe" was pinned at 54.5N 15.2E, which is inside Poland --
   a country that is separately its own row, so one place got two dots and the reader
   had no way to tell which was which. These are reported beside the map instead. */
const REGION_ROWS = new Set(["Africa", "Europe", "Asia", "Middle East",
  "Latin America", "South America", "North America", "Global", "Worldwide"]);

export function geoCountryCoords(countryName) {
  if (!countryName) return null;
  if (COUNTRY_COORDS[countryName]) return COUNTRY_COORDS[countryName];
  const hit = Object.keys(COUNTRY_COORDS).find(
    (k) => k.toLowerCase() === String(countryName).toLowerCase(),
  );
  return hit ? COUNTRY_COORDS[hit] : null;
}

/* Split the served countries into what can be drawn and what cannot.

   Pure, and exported, so the rule can be tested without a map: the old fallback was
   unreachable from any test because it lived inside a Leaflet render effect. */
export function geoPlotPlan(countries) {
  const plotted = [];
  const regions = [];
  const unlocated = [];
  (countries || []).forEach((ct) => {
    if (REGION_ROWS.has(ct)) {
      regions.push(ct);
      return;
    }
    const coords = geoCountryCoords(ct);
    if (coords) plotted.push({ ct, coords });
    else unlocated.push(ct);
  });
  return { plotted, regions, unlocated };
}
/* THE SPELLINGS THAT ARE THE SAME COUNTRY, keyed by one of them.

   sameCountry answers the question for a PAIR. A filter needs the other direction:
   given a name, which other spellings must be folded into it. Both read the same
   coordinate rows, so neither can drift from the other. */
export function countrySpellings(name) {
  const c = geoCountryCoords(name);
  if (!c) return [String(name == null ? "" : name).trim()].filter(Boolean);
  return Object.keys(COUNTRY_COORDS).filter(
    (k) => COUNTRY_COORDS[k][0] === c[0] && COUNTRY_COORDS[k][1] === c[1],
  );
}

/* ARE THESE TWO NAMES THE SAME COUNTRY?

   "UK" and "United Kingdom" are one country under two spellings, and the map already
   knows that -- the alias rows in COUNTRY_COORDS point at identical coordinates. So
   identity is asked of the table that already holds the answer rather than of a second
   alias list that would have to be kept in step with it.

   Two names with no entry are the same only when they are literally the same word: an
   unknown name may never be declared equal to another unknown one. */
export function sameCountry(a, b) {
  const fa = String(a == null ? "" : a).trim().toLowerCase();
  const fb = String(b == null ? "" : b).trim().toLowerCase();
  if (!fa || !fb) return false;
  if (fa === fb) return true;
  const ca = geoCountryCoords(a);
  const cb = geoCountryCoords(b);
  return !!ca && !!cb && ca[0] === cb[0] && ca[1] === cb[1];
}

/* THE COUNTRY AN hq IS IN -- or null, which is a real answer.

   serving.geo_comp.hq is stored at three granularities: a bare country on the archived
   reference rows ("Germany"), a city/region/country chain on the pipeline rows
   ("Ahmedabad, Gujarat, India"), and sometimes only a city ("Beijing", "Madrid").
   GeoMap compared that column to a country name with raw full-string equality, so the
   reference rows matched, the pipeline rows never did, and the "Head office" badge
   silently never fired for a single pipeline competitor.

   The components come from lib/countryFacet.tidyHq (via hqParts) -- the SAME rule the
   Profile page renders an hq with -- and a component becomes a country only if the
   coordinate table already lists it as one. That admits "India" and "United Kingdom"
   and refuses "Gujarat", "Florida" and "Madrid" without a second gazetteer, and it
   cannot invent: a city we have no country for stays null, and no badge is drawn.

   Broadest component last, so the scan runs from the right and stops at the first hit. */
export function hqCountry(hq) {
  const parts = hqParts(hq);
  for (let i = parts.length - 1; i >= 0; i -= 1) {
    if (geoCountryCoords(parts[i])) return parts[i];
  }
  return null;
}

/* Is `country` this company's head office? Uses the STATED origin column when the
   dataset carries one (lib/countryFacet.companyOrigin -- an audited value, not a
   guess) and falls back to the hq string. Null origin and an unreadable hq mean no
   badge, never a guessed one. */
export function isHeadOffice(country, { origin, hq }) {
  const stated = origin && sameCountry(origin, country);
  if (stated) return true;
  const fromHq = hqCountry(hq);
  return !!fromHq && sameCountry(fromHq, country);
}
