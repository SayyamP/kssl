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
import { patRecCard, deriveStats, patCompBody } from "./src/lib/patents.js";

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

/* THE ROLL-UP: WHICH BUCKET, NOT HOW MANY BUCKETS.
 *
 * What was here asserted only that the three counts summed to 3. They did -- because
 * deriveStats' `else` swallowed the unread record into `filed`, and 1+2+0 is 3 just as
 * 1+1+0 plus a separate unknown is. A total is invariant to exactly the mistake this
 * file exists to catch, so it caught nothing: the function shipped counting "nobody
 * asked" as "the registry answered: no grant yet", which is a claim about a record,
 * and the test went green.
 *
 * So this pins the DESTINATION of the unread record. */
const s = deriveStats([granted, unread, filed]);
ck("deriveStats counts the grant", s.granted === 1, JSON.stringify(s));
ck("the unread record lands in `unknown`", s.unknown === 1, JSON.stringify(s));
ck("... and NOT in `filed` -- only the record the registry answered for is filed",
   s.filed === 1, JSON.stringify(s));
ck("... and not in `pending` either", s.pending === 0, JSON.stringify(s));
ck("nothing is lost: the buckets still account for every record",
   s.granted + s.filed + s.pending + s.unknown === 3, JSON.stringify(s));

/* AND IT MUST AGREE WITH dataset.js, which got this right first. That per-holder
 * roll-up ("THREE BUCKETS, NOT TWO") derives pending as filings - granted - unknown,
 * subtracting the unread records out rather than absorbing them. Two roll-ups over the
 * same records disagreeing is how a tab shows one number in the tile and another in the
 * holder row, so the identity is asserted here rather than assumed. */
const recs = [granted, unread, filed];
const holderPending = recs.length - s.granted - s.unknown;
ck("deriveStats' filed+pending is dataset.js's derived `pending`",
   s.filed + s.pending === holderPending, `${s.filed}+${s.pending} vs ${holderPending}`);

// a record carrying no status at all was not measured either
const noStatus = deriveStats([{ id: "X", title: "T" }]);
ck("a record with no status at all is unknown, not filed",
   noStatus.unknown === 1 && noStatus.filed === 0, JSON.stringify(noStatus));

/* THE TILES MUST SHOW IT. A fourth bucket the summary does not draw is a fourth bucket
 * whose records have silently left the page: the three tiles would add up to less than
 * the filings on record with nothing saying why. */
const d = { PATENTS: { _meta: meta }, competitors: { c1: { name: "Rival" } } };
const body = patCompBody(d, "c1", { status: "ok", results: recs });
ck("the summary draws a not-captured tile", /Not captured/.test(body));
ck("... and says how many records it stands for", /1 of these filing/.test(body));
ck("... and the Filed tile counts only the answered record",
   body.includes('pat-stat filed"><div class="pv">1</div>'), body.slice(0, 400));

// with nothing measured anywhere, the old single-tile summary must still count them all
const bodyNone = patCompBody({ PATENTS: { _meta: {} }, competitors: {} }, "c1",
                             { status: "ok", results: recs });
ck("with no grant status in the corpus, all 3 are still 'filings on record'",
   bodyNone.includes('<div class="pv">3</div><div class="pl">Filings on record'));

console.log(fails ? `\n${fails} FAILED` : "\nok - an unread patent is never reported as filed");
process.exit(fails ? 1 : 0);
