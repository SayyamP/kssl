import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/* KSSL_Deploy frontend. Dev proxies /api to the FastAPI backend on :8600;
   the production build fetches /api relative to its own origin, so any static
   server that also routes /api to the backend serves it unchanged. */
export default defineConfig({
  plugins: [react()],
  /* `preview` serves the BUILT bundle. It needs the same proxy as `server`, or the
     only way to test the real artefact is to deploy it. */
  preview: {
    port: 5179,
    host: true,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8600", changeOrigin: true } },
  },
  server: {
    port: 5178,
    host: true,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8600",
        changeOrigin: true,
      },
    },
  },
});
