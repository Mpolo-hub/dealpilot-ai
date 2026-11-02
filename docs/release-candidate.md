# Release Candidate RC1: Local Commercial Demonstration

Status: **RC1 accepted on 2026-11-02 (visual acceptance by the product owner; closure
record at the end of this document). Not committed yet.** Scope: a local demonstration on
the synthetic seed 42 dataset. RC1 acceptance does **not** mean readiness for production,
public or cloud deployment: the application has no authentication and must run on
`127.0.0.1` only (spec 007 D1).

Baseline: branch `main`, HEAD `1ea13c8` (second commit). The frontend, spec 007 and this
document are not committed yet (see "Git state" below).

## 1. Architecture
- **Backend** (`backend/`, committed): Python 3.13, FastAPI, DuckDB over the Parquet files of
  the spec 001 generator. Read-only API v1 (spec 002): `/health`, `/v1/metadata`,
  `/v1/dimensions`, `/v1/sales/metrics`. No change in this release candidate.
- **Frontend** (`frontend/`, spec 007 Implemented for RC1): React 19, TypeScript 6 (strict), Vite 8, CSS
  Modules, React Router, self-hosted Inter, hand-drawn SVG charts, URL-based state. 19 pinned
  npm packages (`frontend/package-lock.json`). The browser talks only to its own origin;
  the Vite proxy forwards `/v1` and `/health` to the API.
- **Data:** `data/raw`, seed 42, 2023-01-01 to 2025-12-31 (gitignored, regenerated from code).

## 2. Modules
| Module | Route | Content |
|---|---|---|
| Dashboard | `/` | Total sales, orders, active products, customers; date range; same period last year badges (D3); daily sales chart with tooltip; sales by region donut |
| Sales analysis | `/analysis` | Overview (average revenue per open day, top product, top region, growth, top 10 products, sales by month with year selector); By product (category and region filters); By region (category and product filters) |
| Products | `/products` | All products (search, category and status filters, sorting, product count, status per spec 001 rule, D4); Categories |
| Data | `/data` | Summary cards (seed, dataset period, tables, API version); row counts; metadata |

## 3. Verified functionality (2026-11-02)
Real-browser checks in headless Chrome (the locally installed browser, driven through
its DevTools protocol; no Playwright browser was downloaded), against the running API:

| Check | Result |
|---|---|
| Direct navigation and refresh: `/`, `/analysis` (3 tabs), `/products` (2 tabs), `/data` (2 tabs), unknown URL | PASS (9 of 9) |
| Dashboard: Apply writes the range to the URL; the range survives a refresh; comparison badge shown (+27.5% for 2025) | PASS |
| Date validation: start after end is refused before any request, with a message | PASS |
| Daily chart tooltip with the keyboard | PASS |
| Sales analysis: tab links, category filter and year selector write the URL | PASS |
| Products: search narrows the list and the counter; status filter (3 discontinued); sorting by sales | PASS |
| Data: Metadata tab | PASS |
| Browser console errors or warnings on every page | none (after the favicon fix below) |

Defect found and fixed: every page logged a 404 for `/favicon.ico`. A local SVG icon
(`frontend/public/favicon.svg`) is now declared in `index.html`.

## 4. Data integrity
Expected values were computed independently with DuckDB directly on `data/raw`
(read-only), then compared with the API and with the rendered screens (temporary
integration checks against the real API, removed afterwards):

| Item | Independent value | API | Screen |
|---|---|---|---|
| Total revenue, full range | $75,194,247.93 | equal | $75.2M, exact value in the tooltip |
| Orders / units | 90,643 / 304,897 | equal | 90,643 |
| Regions (North, South, East, West, Central) | 20,873,250.69 / 16,601,029.17 / 15,177,672.95 / 11,956,456.49 / 10,585,838.63; sum equals the total | equal | 28% / 22% / 20% / 16% / 14% |
| Top 10 products by revenue (P035 Vivo Tent first) | list | equal | same order |
| Monthly revenue 2025 | 12 values | equal | 12 columns |
| Product status on 2025-12-31 (spec 001 rule) | 47 active, 3 discontinued | n/a | 47 active, 3 discontinued |
| Open days, full range | 1,090 (1,096 minus 6 closed days) | n/a | average revenue $69K per open day ($68,985.55) |
| 2025 vs 2024 | revenue +27.5%, orders +10.9% | n/a | +27.5%, +10.9% |
| Closed-day only range (2024-12-25) | no sales | empty | "No sales in this period" |
| Row counts and customers | metadata.json and the customers table agree (2,000) | equal | equal |

No test fixture or sample value from the design images is present in production code.
`data/raw` is byte-identical before and after the checks.

## 5. Security review (local demonstration scope)
| Item | Result |
|---|---|
| API and Vite servers listen on `127.0.0.1` only | PASS (checked) |
| CORS: no `Access-Control-Allow-Origin` from the API or the Vite proxy, even for a foreign `Origin` | PASS (checked) |
| Content Security Policy in the build (`default-src 'self'`, no inline script) | PASS; note: `frame-ancestors` is ignored in a `<meta>` CSP, it needs an HTTP header if the app is ever served by a real web server |
| Error boundary: a crashed page shows an English message, never a blank page | PASS (unit test) |
| API failures: 503 shows "Data unavailable" without any path; network failure shows the start command | PASS (page tests) |
| URL parameters: dates, tab, year, category, region, product and status are validated against the dataset; free-text search is filtered client-side and escaped by React | PASS (code review and tests) |
| Secrets: no key, token or environment variable in the frontend; no source maps in the build | PASS |
| `vite preview` is a local preview server, not a production web server | Limitation (documented) |

## 6. Responsive and visual review
- Every view at 1440 x 900, 1270 x 860, 1024 x 768 and 390 x 844 (32 combinations): no
  horizontal overflow, no console error; page heights follow the content (only the
  50-product lists are long).
- The shared liquid-blue design system follows the product owner's reference image
  `DealDesign/Tableau de bord futuriste DealPilot AI.png` on all four modules.
- Fixed during the last pass: a clipped KPI label ("Average revenue per day" now wraps).
- Pending: the product owner's own visual review in Chrome (AC-UI-14 asks for a person).

## 7. Automated test results (2026-11-02)
| Suite | Command | Result |
|---|---|---|
| Frontend types | `npx tsc` (strict) | exit 0 |
| Frontend lint | `npx eslint .` | exit 0 |
| Frontend tests | `npx vitest run` | 45 passed (4 files) |
| Frontend build | `npm run build` | built; CSP, favicon and Inter license in `dist/` |
| Backend lint | `ruff check --no-respect-gitignore src tests` | all checks passed (76 files) |
| Backend tests | `pytest` (default suite) | 980 passed, 1 skipped, 58 deselected |
| Repository scans | included in the backend suite (`test_security.py`, `test_english_output.py`) | passed |

## 8. Known limitations
- Local use only; no authentication, accounts or multi-company support (D1).
- Seed 42 synthetic data only; no import of company data.
- Date fields are native browser controls: their display follows the browser language
  (for example 01/01/2023 on a French system); values stay ISO dates.
- The comparison badges are hidden for the default full range by design (D3).
- The Dashboard subtitle stays "Overview of sales" (approved wording, D8); the reference
  image reads "Overview of sales performance", a change that needs approval.
- Automated end-to-end and screenshot tests with Playwright are not possible until the
  browser download is authorized; the checks above were run with the local Chrome.
- Two URL changes fired within the same JavaScript task (not possible for a person) can
  overwrite each other (React Router search parameters).

## 9. Dependencies and licenses
- 19 direct npm packages, exact versions; lockfile SHA-256
  `66d66150b82765c92488e9c063c39ac6ea5a7fef1c1eb5a21bbc2e90b8b58909` (unchanged);
  `npm ls --all` clean. No package added, removed or upgraded.
- `npm audit` (2026-11-02): 11 moderate, 0 high, 0 critical, all from one advisory,
  GHSA-g3hv-75wg-m249 (`minimatch` below 11.0.1), reached only through ESLint tooling. Not
  in the browser bundle. Not fixed: npm's suggested fixes are major downgrades; a fix
  needs an approved ESLint upgrade.
- Licenses: no GPL, AGPL or LGPL. The browser bundle holds MIT code and the Inter font
  (OFL-1.1, license shipped as `dist/licenses/inter-OFL-1.1.txt`). Python lockfiles unchanged.

## 10. Outstanding acceptance criteria and approvals
| Item | State |
|---|---|
| Spec 007 as a whole | Approved and Implemented on 2026-11-02 for the RC1 scope only |
| AC-UI-13 (responsive widths) | Checked with the local Chrome; not an automated Playwright test |
| AC-UI-14 (visual fidelity) | Screenshots compared by the engineer; the product owner's review is pending |
| AC-UI-01 to AC-UI-10 end to end | Verified against the real API (temporary integration checks and browser checks); the committed suite covers them with a fake API |
| Playwright browser download (D13) | Not authorized |
| Commit of the frontend, spec 007 and this report | Not authorized yet |
| Specs 002 and 003 status lines (`Implemented`) | Need the product owner's approval |

## Release checklist
- [x] Backend lint and default tests pass (no backend change).
- [x] Frontend types, lint, tests and build pass.
- [x] All routes load directly and after a refresh; no console error.
- [x] Displayed figures match an independent computation from `data/raw`.
- [x] No fixture or sample value in production code; no secrets in the frontend.
- [x] Local-only binding; no CORS; CSP in the build.
- [x] No horizontal overflow at 1440, 1270, 1024 and 390 px.
- [x] `data/raw`, Python lockfiles and the npm lockfile unchanged.
- [ ] Product owner's visual review in Chrome.
- [ ] Product owner's approval of spec 007.
- [ ] Decision on the `minimatch` advisory (accept for dev tooling, or approve an ESLint upgrade).
- [ ] Authorization to commit the release candidate.
- [ ] Optional: authorization to download Playwright browsers for automated end-to-end tests.

## Git state at preparation
```
branch main, HEAD 1ea13c8eb130e79a8b1dd861bb613e8e29bf6cff, nothing staged, no remote
 M AGENTS.md
 M docs/roadmap.md
?? "DealDesign/Tableau de bord futuriste DealPilot AI.png"
?? docs/release-candidate.md
?? frontend/
?? specs/007-frontend.md
```

## RC1 closure record (2026-11-02)
**Decision.** On 2026-11-02 the product owner reviewed the RC1 screenshots and accepted the
visual rendering of the four modules: Dashboard; Sales analysis (Overview, By product, By
region); Products; Data (Overview and Metadata). RC1 is closed as a **local
demonstration on seed 42**. This acceptance is not a production or public commercial
release. (Spec 007 was approved separately the same day; see the decisions record below.)

**Final audit after acceptance.**
- Defect found and fixed: on Sales analysis, By region, the five-column table scrolled
  inside its card between 1280 and about 1380 px wide (506 px of content in a 461 px half
  at 1280 px). The chart and table now share the row 3:4 instead of 1:1 (`chart-table`
  grid variant); the table fits at 1280, 1366, 1440 and 1920 px. Below 1280 px the layout
  is unchanged, and at 390 px tables still scroll inside their card, as section 10 of spec
  007 requires. No page-level horizontal overflow at any checked width.
- Browser smoke test (local Chrome, headless, no download): 21 of 21 checks pass; no
  console error or warning on any page.
- Frontend: `tsc` exit 0, ESLint exit 0, Vitest 45 passed, build OK (CSP, favicon, Inter
  license; no source maps).
- Backend (unchanged since `1ea13c8`): `ruff check --no-respect-gitignore src tests` all checks passed; `pytest` 980 passed, 1 skipped, 58 deselected (246 s).
- Only the four approved endpoints are requested, all with GET; no write operation.
- `data/raw` byte-identical; lockfile hashes unchanged (`frontend/package-lock.json`
  `66d66150...`, `requirements-dev.lock` `d3c103de...`, `requirements-formal.lock`
  `873ab6ac...`); no secret pattern in the changed files; the only environment file is the
  committed `.env.example`.

**npm advisory decision (proposed, needs the product owner's confirmation).**
GHSA-g3hv-75wg-m249 (`minimatch` below 11.0.1, moderate, denial of service through crafted
glob patterns) is reached only through ESLint and `typescript-eslint`, which run on the
developer's machine against the project's own files. It is not in the browser bundle (the
bundle holds React, React DOM, scheduler, React Router and its two helpers, and the Inter
font) and not in the API. Proposed decision for the local release: **accept and record
the risk** (development tooling only, no untrusted glob input). Before any public
deployment: re-run `npm audit`, and approve an ESLint and `typescript-eslint` upgrade
that resolves it once available, as a separate dependency change.

**Blockers for a genuine commercial production deployment (not addressed by RC1).**
1. Authentication, authorization and user accounts (none; spec 002 and spec 007 D1).
2. Multi-company data isolation (none).
3. A production web server with security headers as HTTP headers (CSP with
   `frame-ancestors`, HSTS), TLS, and no Vite dev or preview server.
4. Real data ingestion and a data contract for customer data (seed 42 synthetic only).
5. Operations: deployment, monitoring, logging, backups, incident handling.
6. Automated end-to-end tests in CI (Playwright browsers not authorized), and the npm
   advisory resolved.
7. Formal approval of spec 007 and an update of the spec status lines.

**Approvals still required from the product owner.**
- Approve spec 007 as a whole (status `Draft` to `Approved`; then `Implemented` if
  accepted), by an explicit decision; the RC1 visual acceptance is not that approval.
- Confirm the npm advisory decision above.
- Decide the status lines of spec 002 (still "Ready for implementation review", fully
  implemented) and spec 003 (`Approved`, implemented except formal runs).
- Optionally authorize the Playwright browser download for automated end-to-end tests.
- Authorize the release commit below (and, separately, a tag).

## Release commit preparation (not executed)
**Proposed version.** `0.1.0-rc1`: the package versions stay `0.1.0` (backend
`dealpilot.__version__` and `frontend/package.json`); changing them would change the API
`/health` response and is not needed for a local demonstration. Proposed annotated tag,
only if separately authorized: `v0.1.0-rc1`.

**Proposed commit message.**
```
Add web frontend RC1 for the local seed 42 demonstration

Read-only React + TypeScript + Vite frontend (spec 007) over the existing
v1 API: Dashboard, Sales analysis, Products and Data, with the approved
liquid-blue design system. RC1 visually accepted by the product owner on
2026-11-02 as a local demonstration; not a production release.

Includes spec 007, the release candidate record, the roadmap update, the
product owner's visual reference image and the AGENTS.md layout note.
No backend, API, data or Python dependency change.
```

**Changelog (since `1ea13c8`).**
- Added: `frontend/` (React 19, TypeScript 6 strict, Vite 8, CSS Modules, React Router,
  self-hosted Inter, SVG charts), four modules, 45 tests, local-only Vite proxy with CORS
  off, CSP in the build, favicon, README.
- Added: `specs/007-frontend.md` (Implemented for RC1; decisions D1 to D14 and records),
  `docs/release-candidate.md`, the visual reference
  `DealDesign/Tableau de bord futuriste DealPilot AI.png`.
- Changed: `docs/roadmap.md` (frontend status, RC1), `AGENTS.md` (layout line for
  `frontend/`).
- Unchanged: backend, API contracts, `data/raw`, Python lockfiles.

**File classification (61 files).**
| Class | Files |
|---|---|
| 1. Required for the accepted RC1 | `frontend/` (56 files): `README.md`, `eslint.config.js`, `index.html`, `package.json`, `package-lock.json`, `public/favicon.svg`, `tsconfig.json`, `vite.config.ts`, `src/` (41 files), `tests/` (7 files) |
| 2. Release preparation | `docs/release-candidate.md` |
| 3. Documentation and governance | `specs/007-frontend.md`, `docs/roadmap.md`, `AGENTS.md`, `DealDesign/Tableau de bord futuriste DealPilot AI.png` (approved visual reference, 1.6 MB) |
| 4. Excluded (gitignored, generated) | `frontend/node_modules/`, `frontend/dist/` |

**Exact commands, after authorization only.**
```powershell
cd "D:\DealPilot AI"
git --no-optional-locks status --short --untracked-files=all
git add -- AGENTS.md docs/roadmap.md docs/release-candidate.md specs/007-frontend.md `
  "DealDesign/Tableau de bord futuriste DealPilot AI.png" frontend
git diff --cached --name-only            # expect 61 files, none under node_modules or dist
git diff --cached --check
git commit -F <message file with the text above>
git status --short --branch
git log --oneline -3
# Tag, only with a separate authorization:
# git tag -a v0.1.0-rc1 -m "DealPilot AI 0.1.0 RC1: local seed 42 demonstration"
```

**Release checklist (closure).**
- [x] Product owner's visual acceptance of the four modules (2026-11-02).
- [x] Final audit re-run after acceptance (frontend, backend, browser, data, secrets).
- [x] By region table defect fixed and re-measured.
- [ ] Product owner confirms the npm advisory decision.
- [ ] Product owner approves spec 007 (separate decision).
- [ ] Product owner authorizes the release commit (and, separately, a tag).
- [ ] Not in scope: push, remote, deployment.

## Decisions record and commit (2026-11-02)
**Product owner's decisions (explicit, 2026-11-02).**
- Spec 007 approved for the exact RC1 scope and marked Implemented (status line and
  approval record in the spec). Future screens, API changes and production capabilities
  are not approved.
- npm advisory GHSA-g3hv-75wg-m249 accepted as a moderate risk for the local RC1
  development environment only. No automatic fix, upgrade or lockfile change. A
  separately approved remediation is required before any public deployment.
- Release commit authorized: exactly the 61 files of the classification above, one commit
  on `main`, message `Add web frontend RC1 for the local seed 42 demonstration` (the
  one-line message chosen by the product owner replaces the longer proposal above). No
  push, no tag, no remote change, no deployment.

**Held for a separate documentation change (governance).**
- Spec 002 to `Implemented`: verified eligible on 2026-11-02 (AC-API-01 to AC-API-17
  covered by tests that pass in the default suite; no open question). Not edited in this
  commit, because `specs/002-api.md` is outside the authorized 61 files.
- Spec 003: the authorization asked to "retain Implemented status", but the status line
  reads `Approved`. It is left unchanged pending an explicit decision. The restriction on
  formal forecasting evaluations stays in force (section 9.5: candidate model, decision
  seed, commit, CLEAN result and a separate authorization).

**Commit.** One commit on `main` with parent `1ea13c8eb130e79a8b1dd861bb613e8e29bf6cff`.
Its hash is reported in the release report and is visible with `git log`; this file is
not edited after the commit, so the working tree stays clean.
