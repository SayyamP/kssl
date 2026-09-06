/* A record whose grant status was never read must never render as "FILED".
 *
 * THE SEAM THIS GUARDS. Two changes were made independently: the harvester learned to
 * emit three states (granted / filed / unknown), and the UI learned to say "status not
 * captured" when the CORPUS carries no grant at all. Neither is wrong; together they
 * left a hole that only opens later. dataset.js's normaliser folded every unrecognised
 * status into "filed", and the card chose its badge from the corpus-level
 * `grantStatusKnown`. So while no row has a grant, every card honestly says "not
 * captured" -- and on the first re-harvest that lands real grants, the flag flips true
 * and every record the registry could not answer for silently starts wearing a blue
 * FILED badge. The false claim appears at the exact moment the page starts looking
 * trustworthy, which is the worst possible time for it.
 *
 * The mixed corpus below is the normal end state of a per-record harvest that gives up
 * on some records, so it is the shape to hold the code to.
 */
import { patRecCard, deriveStats } from "./src/lib/patents.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${name.padEnd(66)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

// a corpus where SOME rows have grants and one was never read
const meta = { grantStatusKnown: true, relevDiscriminates: false };
const granted = { id: "US10254091", title: "T", status: "granted", filed: "2016-06-04", granted: "2019-04-09" };
const unread = { id: "AU2010239639", title: "T", status: "unknown", filed: "", published: "2011-09-08" };
const filed = { id: "US20150267996", title: "T", status: "filed", filed: "2015-03-19", published: "2015-09-24" };

const cardU = patRecCard(unread, false, meta);
ck("an unknown record does not wear a FILED badge",
   !/pat-badge filed/.test(cardU), cardU.slice(0, 160));
ck("... it says its status was not captured",
   /status not captured/.test(cardU));
ck("... and it shows the publication date it DOES have, not 'Filed —'",
   /Published 2011-09-08/.test(cardU) && !/Filed —/.test(cardU), cardU);

const cardG = patRecCard(granted, false, meta);
ck("a genuinely granted record still shows its grant",
   /pat-badge granted/.test(cardG) && /Granted 2019-04-09/.test(cardG));
ck("... and is not swallowed by the unknown branch",
   !/status not captured/.test(cardG));

const cardF = patRecCard(filed, false, meta);
ck("a record the registry answered 'no grant' for still reads filed",
   /pat-badge filed/.test(cardF) && /Filed 2015-03-19/.test(cardF));

// the roll-up must not call an unread record "pending"
const s = deriveStats([granted, unread, filed]);
ck("deriveStats counts the grant", s.granted === 1, JSON.stringify(s));
ck("deriveStats does not report the unread record as granted",
   s.granted === 1 && s.filed + s.pending + s.granted === 3, JSON.stringify(s));

console.log(fails ? `\n${fails} FAILED` : "\nok - an unread patent is never reported as filed");
process.exit(fails ? 1 : 0);
