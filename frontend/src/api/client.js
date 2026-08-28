/* One fetch wrapper for the whole app. `fetch` is in every browser this ships to and
   the app makes GETs only, so there is no axios here to install, bundle or keep patched.

   KSSL_Deploy build: the dataset comes from the backend, not an embedded blob. All
   requests are relative to the page's own origin under /api — in dev the vite proxy
   forwards them to the FastAPI backend on 127.0.0.1:8600, and a production build works
   behind any static server that routes /api to the same backend. */
const BASE = "/api";

const TIMEOUT_MS = 30000;

export async function apiGet(path, { signal } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  if (signal) signal.addEventListener("abort", () => controller.abort());

  try {
    let response;
    try {
      response = await fetch(`${BASE}${path}`, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
    } catch (err) {
      if (err.name === "AbortError") throw err;
      /* fetch rejects without a status only when the request never got an answer —
         the backend is down or unreachable. Say that in plain English. */
      throw new Error(
        `the API did not answer (${err.message || "network error"}) — is the backend running on port 8600?`,
      );
    }

    if (!response.ok) {
      let detail = "";
      try {
        detail = (await response.json()).error || "";
      } catch {
        /* body was not JSON — the status alone is the message */
      }
      throw new Error(
        `${response.status} ${response.statusText}${detail ? ` — ${detail}` : ""}`,
      );
    }

    return response.json();
  } catch (err) {
    if (err.name === "AbortError")
      throw new Error(`request to ${path} timed out after ${TIMEOUT_MS / 1000}s`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const apiClient = { get: apiGet };
export default apiClient;
