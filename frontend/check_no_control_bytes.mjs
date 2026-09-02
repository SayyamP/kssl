/* Fail the build if a source file contains a raw control byte.
 *
 *     node check_no_control_bytes.mjs
 *
 * A regex written as backslash-b can reach a file as ONE byte, 0x08, instead of the two
 * characters. The file still parses, the regex still compiles, and it silently matches
 * nothing -- so the code looks right, the build is green, and the fix is a no-op. It has
 * happened three times in this repo:
 *
 *   serving_fill.py   the dangle-repair loop that was meant to stop signals ending
 *                     mid-sentence. Shipped dead; all 17 cards stayed broken.
 *   Profile.jsx       `jv\b` and `tot\b` in the partner-tie ranking, so joint ventures
 *                     written "JV" never sorted first.
 *
 * Only 0x08 has actually bitten, but every C0 control except tab/newline/carriage-return
 * is an error in source, so the check is written for the class rather than the instance.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOTS = ["src", "../extraction/signals", "../pipeline"];
const EXT = /\.(m?js|jsx|ts|tsx|css|py)$/;
const SKIP = /node_modules|[\/]dist[\/]/;

const walk = (dir, out = []) => {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const e of entries) {
    const p = join(dir, e);
    if (SKIP.test(p)) continue;
    if (statSync(p).isDirectory()) walk(p, out);
    else if (EXT.test(p)) out.push(p);
  }
  return out;
};

const bad = [];
let scanned = 0;
for (const root of ROOTS) {
  for (const file of walk(root)) {
    scanned += 1;
    const buf = readFileSync(file);
    for (let i = 0; i < buf.length; i += 1) {
      const c = buf[i];
      if (c < 32 && c !== 9 && c !== 10 && c !== 13) {
        const line = buf.slice(0, i).toString("utf8").split("\n").length;
        bad.push(
          `${relative(".", file)}:${line}  byte 0x${c.toString(16).padStart(2, "0")}  ` +
            `near ${JSON.stringify(buf.slice(Math.max(0, i - 26), i + 12).toString("utf8"))}`,
        );
        break;
      }
    }
  }
}

if (bad.length) {
  console.error(`CONTROL BYTES IN SOURCE - ${bad.length} file(s):`);
  bad.forEach((b) => console.error("  " + b));
  console.error("\nA backslash escape was written as a literal control character.");
  console.error("The regex compiles and matches nothing. Replace it with the two chars.");
  process.exit(1);
}
console.log(`no control bytes in ${scanned} source file(s)`);
