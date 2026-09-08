// @ts-check
import { defineConfig, devices } from "@playwright/test";

/* Where the app is, and who we are to it.
 *
 * BASE_URL: the front door. Locally the vite dev server (frontend/vite.config.js
 * server.port = 5178); on staging/prod https://$KSSL_DOMAIN.
 * The ONLY authentication is HTTP Basic, enforced by traefik on both the UI and /api
 * (docker-compose.vps.yml, middleware kssl-auth). There is no login form to drive. */
const BASE_URL = process.env.KSSL_TEST_BASE_URL || "http://127.0.0.1:5178";
const USER = process.env.KSSL_TEST_BASIC_USER || "";
const PASS = process.env.KSSL_TEST_BASIC_PW || "";

export default defineConfig({
  testDir: ".",
  testMatch: ["frontend/playwright/**/*.spec.js", "e2e/**/*.spec.js"],
  /* The dashboard's bootstrap read is the WHOLE corpus in one round trip and the app
     itself waits 30s for it (frontend/src/api/client.js). A shorter test timeout would
     fail on something the application considers healthy. */
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,          // one shared read-only deployment; do not stampede it
  workers: process.env.CI ? 2 : 4,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "report/playwright", open: "never" }],
             ["json", { outputFile: "report/playwright-results.json" }]],
  use: {
    baseURL: BASE_URL,
    httpCredentials: USER ? { username: USER, password: PASS } : undefined,
    ignoreHTTPSErrors: true,
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    /* The rail is 244px at its widest and a label once rendered "Innovation Pip..." at
       EVERY viewport including 1920 -- so a narrow project is a real regression lane. */
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
  ],
});
