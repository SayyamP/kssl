# KSSL_Deploy frontend

React (Vite + React 18) dashboard, adapted from `KSSL-Parallax/web`. The only
functional change from that app: the dataset is **fetched from the backend**
(`GET /api/dataset`) instead of read from an embedded `window.__EMBEDDED_DATASET__`
blob. Everything downstream of the fetch — the 35-global wiring in
`src/lib/dataset.js`, hash routing (`#p=...&v=...`), localStorage route restore,
and the ErrorBoundary around the app and the detail panel — is unchanged.

## Dev

    npm install
    npm run dev          # http://localhost:5178

The dev server proxies `/api` to `http://127.0.0.1:8600` (see `vite.config.js`),
so the FastAPI backend must be running there:

    cd ../backend && uvicorn app:app --port 8600
    # or, from KSSL_Deploy/: docker compose up -d

## Build

    npm run build        # emits dist/

The build fetches `/api/dataset` **relative to its own origin** — no baked-in
host. Serve `dist/` from any static server that also routes `/api/*` to the
backend on port 8600 (nginx `proxy_pass`, Caddy `reverse_proxy`, or the
docker-compose frontend service). `npm run preview` serves the build locally
but does not proxy `/api`, so use it only with a reverse proxy in front.

## How it talks to the backend

- One bootstrap read: `GET /api/dataset` (`src/api/client.js` +
  `src/api/datasetService.js`, consumed in `src/state/DataProvider.jsx`).
- The API must return the same 35-global JSON shape described by
  `../contract_shapes.json`. The frontend does **not** repair shapes — the
  backend owns them. A missing or mis-shaped global will surface as a thrown
  error far from the cause; that is intentional (no silent defaults).
- While the fetch is in flight the app shows an explicit loading screen; if the
  backend is down or returns a non-2xx / unusable payload, it shows a
  plain-English error screen with a Retry button — never a blank page.

Known shape rules the backend must honour (both have blanked the app before):
`overviewConfig`'s `competitive/market/technology` groups must be non-empty
lists, and `details[id].lens` is a **list of `[lead, html]` pairs**.
