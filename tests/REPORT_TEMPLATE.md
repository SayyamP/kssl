# Test run report — <environment> — <date>

> Fill this in from an actual run. Every number must come from `tests/report/`
> (`pytest.html`, `playwright-results.json`), never from an impression of how it went.

## 1. Run context

| | |
|---|---|
| Environment | dev / staging / prod |
| Base URL | |
| API URL | |
| Commit / TAG | |
| Database reachable | yes / no (tunnel) |
| `KSSL_TEST_ALLOW_WRITES` | 0 / 1 |
| Browsers (Playwright) | chromium / firefox / webkit / mobile-chrome |
| Browsers (Selenium) | chrome / firefox / safari / edge |
| Run started / finished | |

## 2. Result summary

| Section | Total | Passed | Failed | Skipped | Blocked |
|---|---|---|---|---|---|
| Frontend / UI | | | | | |
| Backend / API | | | | | |
| Database | | | | | |
| Extraction | | | | | |
| Security | | | | | |
| Integration / E2E | | | | | |
| Cross-browser | | | | | |
| Performance | | | | | |
| **Total** | | | | | |

Pass rate: __% of executed · Coverage executed: __ of 165 authored cases.

## 3. Failed tests

| Test ID | Module | Expected | Actual | Endpoint / table | Priority |
|---|---|---|---|---|---|
| | | | | | |

## 4. Bugs found

One row per distinct defect (several failing tests may share one bug).

| Bug | Severity | Evidence (test IDs) | Where it lives | Effect on the user |
|---|---|---|---|---|
| | | | | |

## 5. Blocked tests

A test is **blocked**, not failed, when its precondition could not be met.

| Test ID | Blocked by | What is needed to unblock |
|---|---|---|
| | | |

Common blockers on this system: no SSH tunnel to postgres (all `DB-*`, `EXT-03x`);
`provenance.event` migration not applied (`BE-034/036/037`); no bench tables
(`BE-060..065`); `KSSL_TEST_ALLOW_WRITES=0` (`BE-065`); a browser driver missing
(`XB-*`); an empty corpus (most content assertions skip by design).

## 6. Performance measurements

| Metric | Test ID | Budget | Measured | Verdict |
|---|---|---|---|---|
| `/api/dataset` cold | PERF-001 | 30 s | | |
| `/api/ops/*` each | PERF-002 | 10 s | | |
| Shell interactive | PERF-010 | 45 s | | |
| Dataset fetches / 3 views | PERF-011 | exactly 1 | | |
| TTFB / DCL / load | PERF-013 | recorded | | |
| Boot per engine | XB-009 | 45 s | | |

## 7. Coverage

| Dimension | Covered | Total | Notes |
|---|---|---|---|
| Backend routes | | 15 | every route in `backend/app.py` |
| Frontend rail views | | 12 | + 3 archived + `/ops/` |
| `serving_live` views | | 16 | presence; 8 also for content |
| Queue states | | 5 | ready/leased/done/deferred/parked |
| Provenance actions | | 10 | the CHECK vocabulary |

## 8. Sign-off

| Question | Answer |
|---|---|
| Any P0 failing? | |
| Any data-integrity failure (DB-011/012/018)? | |
| Any security failure (SEC-001..004, 008..013)? | |
| Any full-chain failure (E2E-001..007)? | |
| Safe to deploy? | |

**Note.** No application logic was changed to make any test pass. Where a test records a
current behaviour rather than asserting a desired one (SEC-006 headers, SEC-007 CORS,
BE-002 `/healthz` routing, BE-021 unimplemented client paths), that is stated in the
test's own docstring and belongs in §4 as a decision, not a defect, until the product
owner rules on it.
