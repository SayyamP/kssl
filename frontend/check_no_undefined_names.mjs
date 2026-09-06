/* A name that was never defined builds green and throws on first render.
 *
 * `formatTitleCase(v)` sat in Products.jsx:495 and no such function has ever
 * existed in this repo. esbuild does not resolve free identifiers -- it assumes
 * anything unbound is a runtime global -- so `npm run build` succeeded, every
 * other check passed, the image shipped, and the Products view rendered
 * "formatTitleCase is not defined" instead of 256 products. The call sat inside
 * a useMemo that runs on every render, so it took the whole panel down, not one
 * button.
 *
 * A SECOND WAY THE SAME BUG ARRIVES: the name resolves, and the binding is not
 * usable yet. A `const` is in its temporal dead zone until its own line runs, so a
 * useMemo placed above the value it depends on compiles and then throws "Cannot
 * access 'feedArticles' before initialization" at render. That shipped in
 * Profile.jsx on 2026-09-06 and this check now refuses it, by reading hook
 * dependency arrays -- the one construct that is evaluated on the spot, so a
 * verdict about it needs no knowledge of React's semantics.
 *
 * This is scope analysis, not a grep: @babel/traverse resolves each referenced
 * identifier against the scope chain it actually appears in, so a parameter, a
 * loop variable, a destructured binding and a hoisted function all count as
 * defined, and only a genuinely free name is reported. The parser and traverse
 * arrive with @vitejs/plugin-react, which is a direct devDependency and pinned
 * in package-lock.json; if they ever go missing this check fails loudly at build
 * time, which is the safe direction to fail in.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { parse } from "@babel/parser";
import _traverse from "@babel/traverse";

const traverse = _traverse.default || _traverse;
const g = (f) => JSON.parse(readFileSync(
  new URL(`./node_modules/@babel/helper-globals/data/${f}`, import.meta.url)));

/* The capitalised browser and builtin sets ship with Babel. The lowercase browser
   surface does not, so it is listed -- deliberately short: a global this file does
   not know about is reported, and the fix is to add it here with a reason, not to
   widen the net. */
const KNOWN = new Set([
  ...g("browser-upper.json"), ...g("builtin-upper.json"), ...g("builtin-lower.json"),
  "window", "document", "console", "navigator", "location", "history", "screen",
  "fetch", "alert", "confirm", "prompt", "structuredClone", "queueMicrotask",
  "setTimeout", "clearTimeout", "setInterval", "clearInterval", "requestAnimationFrame",
  "cancelAnimationFrame", "localStorage", "sessionStorage", "getComputedStyle",
  "globalThis", "undefined", "process", "arguments", "self", "matchMedia",
]);

const files = [];
(function walk(dir) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(jsx?|mjs)$/.test(e)) files.push(p);
  }
})("src");

const bad = [];
for (const file of files) {
  const ast = parse(readFileSync(file, "utf8"), {
    sourceType: "module",
    plugins: ["jsx"],
    errorRecovery: false,
  });
  traverse(ast, {
    ReferencedIdentifier(path) {
      const { name } = path.node;
      if (KNOWN.has(name)) return;
      // A JSX intrinsic (<div>, <span>) parses as an identifier but is not a binding.
      if (path.parentPath.isJSXOpeningElement() || path.parentPath.isJSXClosingElement()) {
        if (/^[a-z]/.test(name)) return;
      }
      if (path.scope.hasBinding(name, { noGlobals: true })) return;
      bad.push(`${file}:${path.node.loc.start.line}  ${name}`);
    },
  });

  /* THE BINDING EXISTS AND IS STILL NOT USABLE YET.
     A `const` is in its temporal dead zone until its own line runs, so a reference
     above it resolves, compiles, and throws at render. Only references evaluated
     ON THE SPOT can be judged here -- a name used inside a nested function may
     legitimately be read later -- so this checks the one place that is always
     evaluated immediately and where the mistake actually happens: a hook's
     dependency array. `useMemo(() => f(x), [x])` with `const x` declared below
     throws on `[x]` before React sees anything. */
  traverse(ast, {
    CallExpression(path) {
      const callee = path.node.callee;
      const fn = callee.name || (callee.property && callee.property.name);
      if (!/^use[A-Z]/.test(fn || "")) return;
      const deps = path.node.arguments[path.node.arguments.length - 1];
      if (!deps || deps.type !== "ArrayExpression") return;
      for (const el of deps.elements) {
        if (!el || el.type !== "Identifier") continue;
        const binding = path.scope.getBinding(el.name);
        if (!binding || !binding.path.node.loc) continue;
        const kind = binding.path.parentPath && binding.path.parentPath.node.kind;
        if (kind !== "const" && kind !== "let") continue;
        if (binding.path.node.loc.start.line > el.loc.start.line) {
          bad.push(`${file}:${el.loc.start.line}  ${el.name}`
            + ` (declared on line ${binding.path.node.loc.start.line}:`
            + " read here before it is initialised)");
        }
      }
    },
  });
}

if (bad.length) {
  console.error(`FAIL  ${bad.length} name(s) are used but never defined or imported:`);
  for (const b of bad) console.error("  " + b);
  console.error("\nEach of these throws a ReferenceError the moment that code runs.");
  process.exit(1);
}
console.log(`OK  ${files.length} source files, every referenced name resolves to a binding`);
