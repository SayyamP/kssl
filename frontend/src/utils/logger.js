/* `import.meta.env` is Vite's; the optional chain keeps these modules importable by
   plain Node too, which is what lets check.mjs run the self-checks outside a browser. */
const DEV = typeof import.meta.env !== "undefined" && import.meta.env.DEV;

export const logger = {
  info: (...args) => DEV && console.info("[Parallax]", ...args),
  warn: (...args) => console.warn("[Parallax]", ...args),
  error: (...args) => console.error("[Parallax]", ...args),
};
