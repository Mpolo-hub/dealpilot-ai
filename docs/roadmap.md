# Project Status and Roadmap

Engineering status of DealPilot AI, kept up to date as work lands. The specs in `specs/`
stay the source of truth; this page only records where the implementation stands, what
is blocked and why. "Tested" means the named tests pass; it never means production-ready.

Last update: 2026-11-02 (spec 002 Implemented).

## Baseline
- First commit `85d0c23a009e9c1556ea015de2b842508cca8574` on `main` (96 files). No remote.
- Real-repository clean-tree check on 2026-11-01: `CLEAN` on that commit (pygit2 1.20.1,
  libgit2 1.9.7, profile `o2-windows-v1`). This is a historical result, not proof that
  the tree is clean later.
- O2 (spec 003) closed on 2026-11-01 (D30). D29 license conditions still apply.

## Status by spec

| Spec | Status line | Implementation | Classification |
|---|---|---|---|
| 001 Synthetic sales data | Approved v3 | Generator `dealpilot.data.generate`; AC-01 to AC-17 | COMPLETED AND TESTED (AC-10 in the slow suite) |
| 002 HTTP API v1 | Implemented (2026-11-02) | `dealpilot.api`; AC-API-01 to AC-API-17 | COMPLETED AND TESTED |
| 003 Forecasting baseline | Approved | Tranche 1 and tranche 2 (below) | IMPLEMENTED; exploratory runs validated; formal runs BLOCKED BY APPROVAL |
| 004 AI provider layer | Approved | `dealpilot.ai` (mock, Meta adapter, P4) | COMPLETED AND TESTED offline; real Meta calls BLOCKED BY APPROVAL (Q1); P5 Draft, BLOCKED BY APPROVAL |
| 005 Sales summary | Draft | Only the D6 language rules (`dealpilot.insights.language`, limited exception) | NOT IMPLEMENTED beyond D6; BLOCKED BY APPROVAL |
| 006 Gemini provider | Approved | `dealpilot.ai.gemini`, `dealpilot.ai.budget`; AC-GEM-01 to AC-GEM-24 offline | IMPLEMENTED AND TESTED offline; first real call BLOCKED BY APPROVAL (gates G1 to G4) |
| 007 Web frontend | Implemented (approved 2026-11-02 for the RC1 scope only) | F1 built in `frontend/`: four read-only screens, liquid-blue design system applied to all four (2026-11-02); 45 Vitest tests, `tsc`, ESLint and build pass; D9 verified live; headless Chrome checks at 1440, 1270, 1024 and 390 px | IMPLEMENTED BUT NOT FULLY VALIDATED: browser checks (AC-UI-13, AC-UI-14, end to end) wait for Playwright browsers; waiting for the user's review |

### Spec 003 in detail
| Criteria | Where | State |
|---|---|---|
| AC-FC-01 to 05, 08 to 10, 15, 18, 21, 22 | tranche 1 modules | Tested |
| AC-FC-06, 07, 11 to 14, 17, 23 to 25 | `tests/test_forecasting_harness.py` | Tested (2026-11-01) |
| AC-FC-16 | same file, marked slow | Tested on seed 42 data (2026-11-01) |
| AC-FC-19, 20 | `tests/test_forecasting_holdout.py` | Tested in temporary folders with fake checkers (2026-11-01) |
| AC-FC-26 | `tests/test_forecasting_cleantree.py` | Passed once under O2 gate 6 (D30) |

**Runtime (section 9.7, D23).** Measured on 2026-11-01: 5 consecutive exploratory
backtests on seed 42 data (2023-01-01 to 2025-12-31; 13 folds, both baselines, 3 levels,
both day scopes, signal recovery on), timing the backtest stage only: 4.8, 4.9, 4.8, 4.8
and 4.7 seconds; median 4.8 s, maximum 4.9 s (target: under 60 s). Environment: Windows 10
(10.0.19045), Intel64 Family 6 Model 69, 4 CPUs, Python 3.13.17, numpy 2.5.4, pandas
3.1.0, duckdb 2.0.0, pyarrow 26.0.0. The five runs gave byte-identical CSV files.

**Implementation choices, approved 2026-11-01 (spec 003 D31, D2 implementation
review).** None changes a formula, a threshold or the gate:
1. Command line: `python -m dealpilot.forecasting.evaluate backtest` (exploratory only)
   and `holdout-status` (read-only). Formal runs are Python calls only
   (`run_backtest(formal=...)`, `run_holdout`), so a formal run can't start by accident.
2. `source_manifest` leaves out `__pycache__` and `*.egg-info` under `backend/src/`
   (build output; including it would break AC-FC-13 reproducibility).
3. `run.json` does not store the run duration (it would break AC-FC-13); the duration is
   printed, and a run over 60 s adds the warning to `diagnostics`.
4. `metrics.csv` adds `n_folds_wape`, `n_folds_mae`, `n_folds_bias` and `n_folds_mase`
   for the `mean` rows (section 7.5 "reported with the number of folds used"); the
   section 7.3 counters stay empty on `mean` rows.
5. RelMAE and its counters are reported for every model except seasonal naive (naive's
   value is report only and never gated).
6. Holdout MASE scales use training data up to the holdout cutoff `H`, so no holdout
   observation enters the scale (no leakage).
7. A run takes at most one candidate model. A formal holdout run reads gate conditions 1
   to 3 from the matching formal backtest `run.json`, then (user's condition) recomputes
   the 13 folds from the hashed bytes and compares them with that record before any
   holdout forecast; a mismatch stops the run. It refuses in step 3 when library versions
   differ or `metrics.csv` is missing. This is a consistency check against editable local
   files, not cryptographic proof (spec 003 section 9.4 clarification).
8. A backtest run creates its folder after scoring, so a failed run leaves no folder.

## Blocked work (needs the user's decision)
| Item | Why it is blocked | Decision needed |
|---|---|---|
| Formal forecasting runs | Spec 003 section 9.5: a candidate model (none exists; a later spec adds models), a decision seed, a commit, CLEAN, and its own authorization | A candidate-model spec, then a separate authorization per formal run |
| Spec 005 sales summary | Spec is Draft | Approve spec 005 (its section 14 decisions) |
| Real Gemini calls | Spec 006 gates G1 to G4 not verified; separate authorization | Operator checks (G3, G4), then an explicit authorization |
| Real Meta calls, P5 | Spec 004 Q1 open; P5 Draft | Confirm A1 to A5; approve or reject P5 |
| `/v1/forecasts` | Spec 003 D11 deferred; needs a spec 002 update | Approve D11 and the spec 002 change |
| Frontend browser validation | Playwright browsers not authorized | Review of the F1 implementation; authorize the Playwright browser download for AC-UI-13, AC-UI-14 and end-to-end tests. No further approval of spec 007 is pending for the accepted RC1 scope: it is Implemented (2026-11-02) for the four RC1 modules (Dashboard, Sales analysis, Products, Data), local-only, read-only, seed 42 data; future features and production capabilities stay outside that approval |
| Spec 002 status line | Resolved 2026-11-02: `Implemented` by the user's approval (commit `f06133b`) | None |
| Spec 003 status line | Implemented and tested except formal runs | Approve `Implemented` if wanted |

### Notes on the design references (`DealDesign/`)
- The screens are labeled in French, but the permanent product rule (`AGENTS.md`,
  2026-10-31) requires English-only output: an implementation keeps the layout and style
  and uses English text.
- Several visible elements have no approved behavior yet: login and accounts (spec 002
  has no authentication), the "expected demand" line on `dashboard.png` (spec 002 section
  3.8 forbids exposing `expected_demand.parquet`), a Prophet model, confidence intervals
  and a "New forecast" action on `farecasting.png` (spec 003 has baselines only and no
  intervals), and data management, products, promotions and reports pages.
- `Work_screen.png` is a screenshot of the developer's IDE, not a product screen.
- `farecasting.png` and `seal.png` keep their file names (they are not renamed).

## Frontend discovery and specification (2026-11-01)
Authorized by the user on 2026-11-01 as a discovery and specification phase only: no
code, no dependency, no API change. The user approved the **direction** of the first
release the same day; `specs/007-frontend.md` was approved and marked Implemented on
2026-11-02 for the RC1 scope only.

| Group | Content | State |
|---|---|---|
| First release F1 | Four read-only screens (Dashboard, Sales analysis, Products, Data) over the four existing endpoints | Direction approved 2026-11-01; spec ready for approval |
| Architecture | React + Vite + TypeScript, CSS Modules, URL-based state | Direction approved 2026-11-01 (not an installation authorization) |
| Business rules | D3 = option C (same dates one year earlier, hidden when not fully available), D4 = option B (status from launch and discontinue dates on a reference date), D5 = option A (revenue; daily average over open days) | Approved 2026-11-01 |
| Ready for approval | Scope, screenshot mapping, API-to-interface mapping per screen, functional requirements FR-01 to FR-08, English text table, visual fidelity, responsive and security rules, architecture, AC-UI-01 to AC-UI-18 | Waiting for the user |
| Decisions | D1, D2, D6 to D14 (spec 007 section 15): no sign-in, local only, never exposed publicly (D1); hidden tabs and menu items (D2, D6); URL state only (D7); approved wording (D8); Vite proxy and preview, same origin verified (D9); Inter (D10); react-router (D11); hand-drawn SVG charts (D12); Playwright, browsers tracked separately (D13); new screens need their own spec (D14) | Approved 2026-11-01 |
| Dependencies | 19 direct npm packages pinned, 253 in the tree (228 installed on Windows), 7 shipped to the browser (MIT and the OFL-1.1 font), no GPL, AGPL or LGPL; lockfile identical to the reviewed tree; npm audit: 11 moderate from one `minimatch` advisory in the lint chain, not fixed (spec 007 section 12.9, installation record) | Installed 2026-11-01 under explicit authorization with `--ignore-scripts`. Playwright browsers not downloaded (not authorized) |
| Future releases | Sign-in, forecasts, promotions, reports, customer analytics, regions, settings, write actions, expected demand | Each needs its own spec or amendment |

Node 24.21.0 and npm 11.19.0 are present on the development machine; nothing was
installed. `Work_screen.png` is excluded (IDE screenshot).

## Release candidate RC1 (2026-11-02)
Stabilization and QA of the four frontend modules for a local commercial demonstration on
seed 42: see `docs/release-candidate.md` (verified functionality, data integrity against an
independent DuckDB computation, security review, responsive checks, test results, known
limitations, checklist). One defect fixed (missing favicon caused a console error on every
page). Visually accepted by the product owner on 2026-11-02 and closed as a local
demonstration (closure record and commit record in `docs/release-candidate.md`; one more
defect fixed: the By region table scrolled between 1280 and about 1380 px). Decisions of
2026-11-02: spec 007 approved and Implemented for the RC1 scope; npm advisory
GHSA-g3hv-75wg-m249 accepted for the local development environment only (remediation
required before public deployment); release commit authorized. Spec 002 marked
`Implemented` the same day after verification (AC-API-01 to AC-API-17 tested and passing,
no open question; commit `f06133b`). Spec 003 stays `Approved`; formal forecasting runs
stay restricted. Not a public or cloud release.

## Next authorized work
- Keep the default and slow suites green after each change.
- Nothing else in the approved scope is open: every approved, authorized criterion is
  implemented and tested. Further progress needs one of the decisions above.
