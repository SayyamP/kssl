/* HQ is stored at three granularities and must render at one.

   Run: node frontend/src/pages/competitive/tidyHq.test.mjs

   Every input below is a real serving.competitors.hq value read from production on
   2026-09-06. The rule only REMOVES -- street lines, postcodes, parenthetical asides --
   and keeps the last three components, so a short value must survive untouched and no
   city may be lost. The second property is the one that broke first: an initial
   postcode ("80997 Munich") reads exactly like a house number, and the first version of
   this rule dropped Munich and Le Plessis-Robinson, leaving a bare country. */
/* 2026-09-06: tidyHq moved into lib/countryFacet.js when the geo map's "Head office"
   badge became its second reader, so this imports it rather than slicing it out of
   Profile.jsx's source. Same rule, same cases -- and the module is now loaded the way
   the app loads it, so it is really this code that is under test. */
import { tidyHq } from "../../lib/countryFacet.js";

const CASES = [
  // full postal address -> the geographic chain only
  ["241 18th Street South, Suite 650, Arlington, Virginia 22202, United States", "Arlington, Virginia, United States"],
  ["6 Carlton Gardens, London SW1Y 5AD, United Kingdom", "London, United Kingdom"],
  ["L&T House, N. M. Marg, Ballard Estate, Mumbai 400001, Maharashtra, India", "Mumbai, Maharashtra, India"],
  ["2307 Oregon Street, Oshkosh, Wisconsin 54902, United States", "Oshkosh, Wisconsin, United States"],
  ["Poongsan Building, 23 Chungjeong-ro, Seodaemun-gu, Seoul, South Korea", "Seodaemun-gu, Seoul, South Korea"],
  ["Hardware Park, Plot No.21, Sy No.1/1, Imarat Kancha Raviryala Village, Maheshwaram Mandal, Hyderabad 501218, Telangana, India", "Hyderabad, Telangana, India"],
  ["No. 4, Bommasandra Industrial Area, Jigani Link Road, Bommasandra, Bengaluru 560099, Karnataka, India", "Bengaluru, Karnataka, India"],
  // A LEADING POSTCODE IS NOT A HOUSE NUMBER -- these lost their city once.
  ["Krauss-Maffei-Strasse 11, 80997 Munich, Germany", "Munich, Germany"],
  ["1 Avenue Réaumur, 92350 Le Plessis-Robinson, France", "Le Plessis-Robinson, France"],
  ["Via Alessandro Volta 6, 39100 Bolzano, Italy", "Bolzano, Italy"],
  // an aside and a second clause are not part of the headquarters
  ["86 Cheonggyecheon-ro, Jung-gu, Seoul, South Korea (Seoul headquarters); major manufacturing in Changwon", "Jung-gu, Seoul, South Korea"],
  // already short -- must pass through untouched, and nothing invented
  ["Ahmedabad, Gujarat, India", "Ahmedabad, Gujarat, India"],
  ["Costa Mesa, California, United States", "Costa Mesa, California, United States"],
  ["Bethesda, MD, USA", "Bethesda, MD, USA"],
  ["Hyderabad, Telangana", "Hyderabad, Telangana"],
  ["Devon, UK", "Devon, UK"],
  ["Israel", "Israel"],
  ["Beijing", "Beijing"],
  // absent stays absent
  ["", null], [null, null], [undefined, null],
];

let bad = 0;
for (const [input, want] of CASES) {
  const got = tidyHq(input);
  const ok = got === want;
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"} ${JSON.stringify(got)}${ok ? "" : `  want ${JSON.stringify(want)}`}`);
}
if (bad) { console.error(`\n${bad} case(s) failed`); process.exit(1); }
console.log(`\nall ${CASES.length} headquarters render at one granularity`);
