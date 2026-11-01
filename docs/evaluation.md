# Forecast Evaluation Principles

Every forecasting model in DealPilot AI follows these rules. A model that skips them
does not ship. `specs/003-forecasting-baseline.md` defines the exact calendar, formulas,
acceptance gate and records; where this page summarizes it, the spec is authoritative.

**Status:** `specs/003-forecasting-baseline.md` was approved on 2026-10-28, as a
specification only. Question O2 (the formal-run clean-tree check) was officially closed on
2026-11-01 (spec D30, section 13.3). The closure does **not** authorize formal evaluation
runs: they stay prohibited until the repository has a first commit, the working tree is
verified clean, and every other condition of spec section 9.5 is met under its own
authorization. The approval did not authorize implementation by itself: tranche 1 was
built under its own authorization, and the harness (tranche 2: results record, holdout
log, decision seed, run classes) was built on 2026-11-01 under the user's standing
authorization for approved specs. Exploratory backtests run with
`python -m dealpilot.forecasting.evaluate backtest` (from `backend/`). No formal run has
been made: it needs a candidate model and every section 9.5 condition, under its own
authorization.

## 1. Split by time, never at random
- Train only on data up to and including the cutoff (the last training day). Test only on
  days after it.
- No random train/test split and no shuffled k-fold. They leak the future into training.
- **Backtesting:** rolling origin on the data before the final holdout: 13 cutoffs, 28
  days apart, each forecasting the next 28 days. The model is refit at each cutoff.
- **Final holdout:** the last 90 days, scored from four origins in a row (28, 28, 28 and
  6 days). At each origin the model is refit on data up to that origin with a frozen
  configuration. Nothing is tuned, and no score is shown until all four origins are done.
- **A holdout is used once.** It is consumed as soon as a holdout run is logged as
  started, even if the run stops early. A consumed holdout is never reused for a final
  decision. A new decision needs a new dataset made with a different, recorded seed, and
  a full new backtest on it.

## 2. Always compare to a baseline
- **Seasonal naive (main baseline):** each day gets the value from the same weekday in the
  last week before the cutoff, repeated weekly. If that source day is closed (Dec 25 or
  Jan 1), the same weekday one week earlier is used (lag 14, then lag 21). If no open
  source day exists, the forecast is 0.
- **Naive (sanity check, report only):** the last observed value, repeated. It is never
  used to decide whether a model ships.
- **Ship rule.** A model ships only if, at each level (total, category, product-region),
  using open days only:
  - its mean WAPE over the backtest folds is at least 5% lower than seasonal naive's,
  - its RelMAE across the backtest folds (the geometric mean of the fold RelMAE values)
    is 0.95 or lower,
  - it wins at least 10 of the 13 folds (WAPE strictly lower and RelMAE strictly below
    1; a tie is not a win; a fold with a missing value is lost and still counts in the 13),
  - on the final holdout, its WAPE and RelMAE are not worse than seasonal naive's.

  All three levels must pass. A missing (null) value never passes. Decisions use
  unrounded values. The 5% and 0.95 thresholds and the holdout comparison are inclusive;
  a fold win needs strictly better values.

## 3. Metrics
| Metric | Why |
|---|---|
| **WAPE** = sum(abs(error)) / sum(actual) | Main metric. Easy to explain, works with zero-sales days. Used in the ship rule. |
| **RelMAE** = geometric mean over series of (model MAE / seasonal-naive MAE) | Below 1 means better than the baseline. Used in the ship rule. |
| **MASE** (scaled by week-over-week changes in training, leaving out pairs that touch a closed day) | Report only. A model is better when its MASE is lower than the baseline's MASE on the same folds; the value 1.0 is not a pass mark. |
| **MAE** | Error in units, for reports. |
| **Bias** = sum(forecast - actual) / sum(actual) | Shows if a model always over- or under-forecasts. |
| **Interval coverage** (if the model gives ranges) | An 80% range should contain the actual value about 80% of the time. |

Do not use plain MAPE. It breaks when actual sales are zero (closed days, small products)
and punishes over-forecasts more than under-forecasts.

Report every metric per fold, per level (total, category, product-region) and as an
average, for open days and for all days. The ship rule uses open days only.

## 4. Prevent data leakage
- Features may only use data known at the cutoff. Lags and rolling averages end at the
  cutoff, not in the test window.
- A model sees only what is known at the cutoff: no future product launch or stop dates,
  and no dataset end date, row counts or seed.
- Scalers, encoders and any fitted values are fit on training data only.
- Planned promotions and the fixed holiday calendar (Dec 25 and Jan 1) may be used as
  future inputs, because a business knows them in advance. A model that uses them must
  say so in its report.
- Products or customers that first appear after the cutoff are not visible to training.
- Do not tune settings on the final holdout. A holdout that has been looked at is used
  up (section 1).
- The synthetic generator's true parameters (`metadata.json`) and true expected demand
  (`expected_demand.parquet`) are never model inputs.

## 5. Reproducibility and records
- Every eval run records: data seed, cutoffs, model name and settings, code version, and
  all metrics.
- **Exploratory runs** (development) may run without a git commit. They record a SHA-256
  list of the source files instead, which shows changes but cannot restore old code.
  They never make a ship decision.
- **Formal runs** (decisions) need a git commit and a verified clean working tree, and
  record the commit. A clean working tree is one requirement among several; on its own it
  never allows a formal run. If cleanliness cannot be verified, the formal run is refused.
- **Clean-tree checker (spec 003 O2, section 13.3).** `dealpilot.forecasting.cleantree`
  returns CLEAN, DIRTY or REFUSED; only CLEAN can satisfy this requirement. It needs the
  optional `formal` extra (pygit2), which is **for internal use only** and is never
  shipped. pygit2 1.20.1, cffi 2.1.1 and pycparser 3.12 are approved (O2 gate 3) and their
  license is accepted for internal use (spec D29, gate 5). They were installed on
  2026-11-01 (gate 4) on Windows AMD64 with
  `python -m pip install --require-hashes --only-binary=:all: -r requirements-formal.lock`
  then `python -m pip check` (from `backend/`, after `requirements-dev.lock`): `pip check`
  found no broken requirements, only these three packages were added, and both lockfiles
  are unchanged (spec section 13.3). The bundled libgit2 1.9.7 was verified at runtime, and
  AC-FC-26 ran on 2026-11-01 (gate 6) with `python -m pytest -m formal_checker` while the
  variable `DEALPILOT_RUN_AC_FC_26` equaled `o2-gate-6-approved`: 56 passed, 0 failed,
  0 skipped, 859 deselected. Without that variable, every run leaves these tests out. O2
  is **closed** (spec D30) and the D29 license conditions still apply. A formal run still
  needs a first commit and a CLEAN result on it; until then every formal run stays refused.
- **Decision seed:** the model is frozen first. The seed of its decision dataset is then
  derived from the frozen model and recorded before that dataset is generated, and every
  formal run checks it.
- The same data and settings, on the same machine with the same library versions, give
  the same numbers. No promise is made across machines or library versions.
- Raw results go in `evals/results/` (gitignored). Holdout runs are logged in
  `evals/holdout-log.csv` (tracked, append-only, hash-chained); its head record and lock
  stay local in `evals/results/`. Integrity incidents are recorded by a person in
  `docs/incidents/holdout-integrity.md`; tools never write it. Summary tables that support
  a decision go in `docs/`.
- The default full backtest aims to finish in under 60 seconds. A slower run gives a
  warning; there is no hard limit.

## 6. Signal recovery (synthetic data only)
- On synthetic data, also report signal WAPE and the noise floor, as defined in
  `specs/001-synthetic-sales-data.md` section 6.3.
- Report them in their own table, separate from the metrics above. Never mix or
  average them in.
- The ship rule in section 2 uses observed sales only.
