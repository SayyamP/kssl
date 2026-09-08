# KSSL / 137Parallax — E2E test suite

Playwright is the primary E2E framework. Selenium is the cross-browser regression lane.
pytest covers the API, the database and the extraction pipeline.

**Everything here is read-only by default.** The suite drives a *running deployment*; it
does not seed, migrate or provision anything. The one write path in the whole HTTP
surface (`POST /api/bench/submit`) is behind an explicit opt-in.

```
tests/
├── TEST_CASES.md                 the full matrix — read this first
├── REPORT_TEMPLATE.md            the shape of the run report
├── lib/env.py                    one place that knows where the system is
├── conftest.py                   shared fixtures (http session, read-only db)
├── backend/                      API tests            (pytest + requests)
├── database/                     schema + integrity   (pytest + psycopg2)
├── extraction/                   pipeline             (pytest; pure + live)
├── frontend/playwright/          UI                   (Playwright)
├── frontend/selenium/            cross-browser        (Selenium)
└── e2e/                          full-chain           (Playwright)
```

## Install

```bash
cd kssl-deploy/tests
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
npm install && npx playwright install --with-deps
```

## Point it at an environment

```bash
cp .env.example .env       # then edit, then:  set -a; . ./.env; set +a
```

The three things it needs:

| | Local | Staging / prod |
|---|---|---|
| `KSSL_TEST_BASE_URL` | `http://127.0.0.1:5178` (vite dev) | `https://<KSSL_DOMAIN>` |
| `KSSL_TEST_API_URL` | `http://127.0.0.1:8600` | `https://<KSSL_DOMAIN>` (traefik routes `/api`) |
| `KSSL_TEST_BASIC_USER/PW` | not needed | `kssl` + the password from `deploy/provision_env.sh` |

Database tests need postgres reachable. It is bound to loopback on the VPS, so:

```bash
ssh -N -L 5460:127.0.0.1:5460 root@<host>
export KSSL_TEST_DSN="host=127.0.0.1 port=5460 dbname=kssl user=postgres password=<pw>"
```

Anything unreachable **skips** rather than fails — a run without a DB tunnel still gives
you the full API and UI result, clearly marked as partial.

## Run

```bash
# everything Python: API + database + extraction + selenium
pytest

# one section at a time
pytest backend/        # API
pytest database/       # schema and integrity
pytest extraction/     # pipeline (pure logic + live queue state)

# Playwright: UI + full-chain E2E
npx playwright test                       # all projects
npx playwright test --project=chromium    # one browser
npx playwright test frontend/playwright   # UI only
npx playwright test e2e                   # the chain only

# cross-browser through real vendor browsers
KSSL_TEST_BROWSERS=chrome,firefox pytest frontend/selenium/
```

Reports land in `tests/report/`: `pytest.html`, `playwright/index.html`,
`playwright-results.json`.

## Opt-ins

| Variable | Default | Effect |
|---|---|---|
| `KSSL_TEST_ALLOW_WRITES` | `0` | `1` enables BE-065, the only test that writes (one row in `metrics.adhoc_job`) |
| `KSSL_TEST_BROWSERS` | `chrome,firefox` | which real browsers Selenium drives (`safari`, `edge` also supported) |
| `KSSL_TEST_HEADED` | `0` | `1` shows the Selenium browsers |
| `KSSL_TEST_BUDGET_*` | 30 / 10 / 45 s | performance budgets, deliberately set to the app's own thresholds |

## What this suite deliberately does not do

- **It does not modify application logic to make a test pass.** Where the code does
  something the test would rather it did not (CORS `*`, security headers on only one
  traefik router, three service methods with no endpoint behind them), the case
  *records the current behaviour* and says so in its docstring. Changing that is a
  product decision, not a test decision.
- **It does not invent features.** There are no roles, no login, no upload and no
  server-side export in this system, so there are no tests for them. §2 of
  `TEST_CASES.md` lists every such gap and why.
- **It does not duplicate the repository's own unit tests.** `frontend/test_*.mjs`,
  `backend/test_*.py` and `extraction/**/test_*.py` are hermetic tests over pure
  functions and stay where they are. Where a module ships a self-check
  (`portfolio_gate._demo()`), the case here calls it instead of restating the rule.
- **It does not seed data.** Every value a test uses is read from the live payload or
  the live database first. A test that invented a competitor name would pass on a
  fixture and tell you nothing about the deployment.

## Reading a failure

Each test's docstring/comment carries its full record — Test ID, Module, Precondition,
Steps, Test Data, Expected Result, API Endpoint, Database Validation, Priority,
Automation Tool. When a case fails, that block is the bug report: it already names the
endpoint, the table and the invariant.
