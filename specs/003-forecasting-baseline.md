# Spec 003: Forecasting baseline and evaluation harness

Status: Approved (2026-10-28, by the user's explicit approval; revised 2026-10-28).
Decisions marked approved in section 12 were confirmed by the user on 2026-10-28. This
approval covers the specification only: O2 was then open, so every formal run was
refused (section 9.5), and no dependency was approved then. On 2026-11-01 the
optional `formal` extra (pygit2 1.20.1, cffi 2.1.1, pycparser 3.12) was approved (O2 gate
3), its internal-use license accepted (D29, gate 5) and it was installed in the project
virtual environment (gate 4, section 13.3). AC-FC-26 ran and passed (gate 6), and O2 was
officially closed on 2026-11-01 by the user's explicit approval (D30, section 13.3). The
closure does **not** authorize formal evaluations: a first commit, a verified clean
working tree and every other section 9.5 condition are still required.
`docs/evaluation.md` was aligned on 2026-10-28 (section 15).
Owner: DealPilot AI team
Depends on: spec 001 (data, section 5.7 closed days, section 6.3 signal recovery), spec 002
(error format, section 6 planned contract, D10, AC-API-17), `docs/evaluation.md` (binding
rules for every model; aligned with this spec on 2026-10-28, see section 15)

## 1. Goal
Build the yardstick every future forecasting model is measured against:
- two reference forecasts from `docs/evaluation.md` section 2: **seasonal naive** (main
  baseline, the reference for every acceptance decision) and **naive** (sanity check,
  report only),
- a **leakage-safe evaluation harness** that applies the time split, metrics, leakage rules
  and reproducibility rules of this spec to any model with the same interface,
- an **acceptance gate** (section 8) that decides whether a candidate model beats seasonal
  naive,
- a **results record** in `evals/results/` and a **holdout log** in
  `evals/holdout-log.csv` that make every run repeatable and auditable.

The harness is the main deliverable. A later spec adds real models; each one ships only
if this harness accepts it (AGENTS.md, "How we work" item 4).

## 2. Non-goals
- No machine-learning or statistical models beyond seasonal naive and naive.
- No prediction intervals. Baselines give point forecasts only, so interval coverage
  (`docs/evaluation.md` section 3) is not computed in this spec.
- No revenue, order or order-line forecasts. The target is units (section 4.1, D3).
- No customer-level, channel-level or promotion-level forecasts.
- No tuning and no model selection. Baselines have one fixed setting each.
- No use of planned promotions as future inputs. Baselines ignore them
  (`uses_planned_promotions` is `false`).
- No formal acceptance decision on seed 42 data (D18). Seed 42 is for testing the harness
  and measuring baselines.
- No HTTP endpoint. Section 10 only records a deferred proposal (D11). Spec 002 is not
  changed by this spec.
- No frontend, no LLM features, no external services, no new dependencies. The only
  possible exception is an optional formal-evaluation extra that needs its own explicit
  approval under O2 (D2, section 9.5). Only that extra is approved: the `formal` extra
  (pygit2 1.20.1, cffi 2.1.1, pycparser 3.12), O2 gate 3, 2026-11-01, internal use only
  (D29). It was installed on 2026-11-01 (gate 4, section 13.3); O2 closed the same day
  (D30).
- No real data. Synthetic spec 001 data only.

## 3. Assumptions
Each assumption is marked with its source. Unsourced points are open items (section 13).

| ID | Assumption | Source |
|---|---|---|
| A1 | The input is a spec 001 data folder: `metadata.json`, `regions.parquet`, `products.parquet`, `orders.parquet`, `order_lines.parquet` (the spec 002 v1 dataset). | spec 001 section 3; spec 002 section 3.2 |
| A2 | The range is 730 to 1096 days, counting both ends. | spec 001 section 3 |
| A3 | Default data: seed 42, 2023-01-01 to 2025-12-31, 1,096 days, 6 closed days (Dec 25 and Jan 1). | spec 001 sections 3 and 5.7; spec 002 AC-API-07 |
| A4 | 5 regions, 50 products, 5 categories with 10 products each, so 250 product-region pairs. | spec 001 section 4 |
| A5 | Products can launch late (between `--start` + 90 and `--end` - 180 days) or stop (between `--start` + 180 and `--end` - 90 days). So a series can be all zero for part of the range. | spec 001 section 4 |
| A6 | A day with no order line for a key means zero units for that key. | spec 002 D5; spec 001 section 5.9 |
| A7 | The forecast levels are total, category and product-region. | `docs/evaluation.md` section 3; spec 002 section 6 |
| A8 | The only closed days are December 25 and January 1, every year. | spec 001 section 5.7 |

Observed facts for seed 42 (checked read-only on `data/raw`, 2026-10-28). They are not
guarantees for other seeds:
- All 250 product-region pairs have at least one sale. Sales exist on 1,090 days.
- Late launches: P005 (2024-02-27), P036 (2024-04-01), P047 (2024-06-24), P031
  (2024-09-13), P011 (2025-02-08). Discontinued: P048 (2024-01-03), P023 (2023-09-14),
  P018 (2024-07-06).
- With 13 folds (section 5.2), 4 late launches come before the first cutoff (2024-10-03).
  P011 launches after it, inside fold 5's test window, so it is inactive in folds 1 to 4.
  The 3 discontinued products are inactive in every test window. So 20 product-region
  series are excluded from per-series averages in folds 1 to 4 (P011 and the 3
  discontinued products) and 15 in folds 5 to 13 (the 3 discontinued products only)
  (section 7.4).

## 4. Data used

### 4.1 Target
Daily **units**: the sum of `order_lines.quantity` for the key and date, with
`order_date` from `orders`. This is the same "daily units" as spec 001 section 8.1 and the
same quantity spec 001 section 6 models as expected demand.

### 4.2 Series and scoring universe
For level L and key k, `y_k(d)` is the daily units of the products and regions in k on day
d, for **every** date from `start` to `end`. Days without sales are 0 (A6), closed days
included.

| Level | Keys | Count (default data) |
|---|---|---|
| `total` | one key: all products, all regions | 1 |
| `category` | each distinct `products.category` | 5 |
| `product_region` | each `products.product_id` x each `regions.region_id` | 250 |

The **scoring universe** comes from `products.parquet` and `regions.parquet`, not from
which keys have sales, so every series is scored (D4). Only evaluation code knows the full
universe. A product that is not visible to the model at a cutoff (section 4.3) gets a
forecast of 0 from the evaluator for every product-region series it belongs to; the model
is not asked about it. Category and total forecasts come from the model's own level
forecast, built only from visible inputs.

### 4.3 Model-visible inputs (D13)
At a cutoff `c`, model code (fit and forecast) receives only:

| Input | Content |
|---|---|
| Sales history | Daily series values for dates `start` to `c` |
| Products | Rows with `launch_date <= c`, with the fields `product_id`, `category`, `launch_date`, and `discontinue_date` only when it is `<= c` (otherwise null) |
| Regions | `region_id` only |
| Metadata | `start` and the cutoff `c` only |
| Holiday calendar | The fixed constant in section 6.3 |

Model code never receives: future product lifecycle data (`launch_date > c`,
`discontinue_date > c`), the dataset `end`, `row_counts`, `seed`, `generator_version`,
`metadata.json` `parameters` (including `closed_days` and `base_demand`),
`regions.size_weight`, `list_price`, or `expected_demand.parquet`. Model code reads
metadata only through a reader that returns the allowed fields (AC-FC-07).

### 4.4 Evaluation-only data
Evaluation code (calendar, scoring, gate, records) may additionally read:
- the full `products.parquet` and `regions.parquet`, to build the scoring universe and to
  decide which series are inactive (section 7.4),
- `metadata.json` `seed`, `start`, `end`, `generator_version`, `row_counts`, and file hashes,
- `expected_demand.parquet`, only for the signal-recovery table and only for test-window
  dates (spec 001 section 6.3).

Evaluation code never reads `metadata.json` `parameters` or `regions.size_weight`. Test
code may read `parameters.closed_days` to check the holiday constant (AC-FC-17).

## 5. Time split

### 5.1 Rule for any valid range
Let `E` be the dataset `end`. The holdout is the last 90 days, `E - 89` to `E`, with
holdout cutoff `H = E - 90`.

**Backtest:** `c_k = H - 28 * k` for k = 1 to 13. Each fold trains on `start` to its
cutoff and forecasts the next 28 days. The 13 test windows are back to back, do not
overlap, cover 364 days, and the last one ends on `H`, so no backtest window touches the
holdout. The earliest cutoff is `E - 454`; with the shortest allowed range (730 days) its
training data still has 276 days, so every valid spec 001 range fits.

**Holdout:** four sequential origins (D6):

| Origin | Cutoff | Horizon | Days scored |
|---|---|---|---|
| 1 | `H` | 28 | `H + 1` to `H + 28` |
| 2 | `H + 28` | 28 | `H + 29` to `H + 56` |
| 3 | `H + 56` | 28 | `H + 57` to `H + 84` |
| 4 | `H + 84` | 6 | `H + 85` to `E` |

At each origin the model is refit on data from `start` to that origin's cutoff, with the
frozen configuration (section 5.3). Holdout metrics are computed once over all 90 days
together (section 7).

### 5.2 Default data (seed 42, 2023-01-01 to 2025-12-31)
Folds are numbered in time order (fold 1 is `k = 13`). Every cutoff is a Thursday.

| Fold | Cutoff | Test window | Closed days in window | Closed days in the 7 days before the cutoff |
|---|---|---|---|---|
| 1 | 2024-10-03 | 2024-10-04 to 2024-10-31 | none | none |
| 2 | 2024-10-31 | 2024-11-01 to 2024-11-28 | none | none |
| 3 | 2024-11-28 | 2024-11-29 to 2024-12-26 | 2024-12-25 | none |
| 4 | 2024-12-26 | 2024-12-27 to 2025-01-23 | 2025-01-01 | 2024-12-25 |
| 5 | 2025-01-23 | 2025-01-24 to 2025-02-20 | none | none |
| 6 | 2025-02-20 | 2025-02-21 to 2025-03-20 | none | none |
| 7 | 2025-03-20 | 2025-03-21 to 2025-04-17 | none | none |
| 8 | 2025-04-17 | 2025-04-18 to 2025-05-15 | none | none |
| 9 | 2025-05-15 | 2025-05-16 to 2025-06-12 | none | none |
| 10 | 2025-06-12 | 2025-06-13 to 2025-07-10 | none | none |
| 11 | 2025-07-10 | 2025-07-11 to 2025-08-07 | none | none |
| 12 | 2025-08-07 | 2025-08-08 to 2025-09-04 | none | none |
| 13 | 2025-09-04 | 2025-09-05 to 2025-10-02 | none | none |

| Holdout origin | Cutoff | Days scored | Closed days in window | Closed days in the 7 days before the cutoff |
|---|---|---|---|---|
| 1 | 2025-10-02 | 2025-10-03 to 2025-10-30 | none | none |
| 2 | 2025-10-30 | 2025-10-31 to 2025-11-27 | none | none |
| 3 | 2025-11-27 | 2025-11-28 to 2025-12-25 | 2025-12-25 | none |
| 4 | 2025-12-25 | 2025-12-26 to 2025-12-31 | none | 2025-12-25 (the cutoff itself) |

In fold 4, seasonal naive's Wednesday source day is 2024-12-25 (closed), so it uses
2024-12-18 (lag 14, section 6.1). At holdout origin 4 the 6 forecast days use source days
2025-12-19 to 2025-12-24, all open; naive forecasts `y(2025-12-25) = 0` (section 6.2).

### 5.3 Stages and holdout governance (D12)
- **Backtest stage:** runs the 13 folds. It must give the same results no matter what the
  data holds after `H` (AC-FC-11).
- **Holdout stage:** formal runs only (section 9.5). It runs only when all of these hold:
  1. the candidate configuration is frozen, and its `config_hash` and the `data_hash` of
     the five A1 files (section 9.4) are computed and written into the `started` entry
     before any holdout observation is loaded (sequence in section 9.4),
  2. a formal backtest run with the **same configuration hash and `data_hash`** (section
     9.4; for the backtest run, computed from the A1 file hashes in its `run.json`) passed
     conditions 1 to 3 of section 8 at all three levels,
  3. the holdout log has no `started` entry for the same `data_hash` and holdout dates
     (the holdout is not consumed),
  4. the log's hash chain verifies (section 9.4).
- **No tuning during the holdout.** All four origins run in one formal run with the frozen
  configuration. Refitting at each origin uses only data available by that cutoff and
  changes no settings. Scores for all four origins are computed in memory; no partial
  score is written or shown before all four are done.
- **Consumed holdout.** A holdout is consumed when, and only when, its `started` entry is
  durably recorded (step 4 of section 9.4). A crash or a stale lock alone does not prove
  that a holdout was consumed. An identifiable complete `started` entry found in the log
  counts as durably recorded even when other parts of the log fail the integrity checks
  (section 9.4).
  A `started` entry with no matching `completed` entry means the run was interrupted; it
  still counts as consumed. A consumed holdout is never reused for another final
  decision, whatever its result.
- **New decision after consumption (D18).** A new final decision needs a new dataset made
  with a different, recorded seed. The complete backtest is rerun on that dataset; no
  earlier backtest result is reused. A **decision seed** distinct from 42 is reserved for
  this purpose. It is not selected or run under this spec (section 13). The decision seed
  is derived, recorded and checked as in section 5.4. A formal run is only possible on a
  dataset whose seed passes that check, so seed 42 data can never be used for a formal run.

### 5.4 Decision seed (D22)
Each formal decision uses a seed derived from fixed inputs. No seed is selected under this
spec, and a formal decision needs a Git commit, which does not exist yet.

**Derivation text.** One line, fields in exactly this order, no spaces, no trailing
newline:

```
dealpilot-decision-seed/v1|spec=<spec>|candidate=<name>@<version>|config=<config_sha256>|decision=<d>|n=<n>
```

| Field | Exact form |
|---|---|
| `<spec>` | The candidate spec's 3-digit number, `^[0-9]{3}$`, for example `004` |
| `<name>` | The candidate model `name`, `^[a-z][a-z0-9_]*$` |
| `<version>` | The candidate model `version`, `^[0-9]+(\.[0-9]+)*$`, for example `1.0` |
| `<config_sha256>` | `candidate_config_sha256` (below): 64 lowercase hex characters, `^[0-9a-f]{64}$` |
| `<d>` | Decision number: a decimal integer of 1 or more, no sign, no leading zeros |
| `<n>` | Skip counter: same form as `<d>`, starting at 1 |

- Values are validated, never normalized. A value that does not match its pattern makes
  the derivation fail, and the formal run is refused.
- Separators are the literal characters `|` between fields, `=` between key and value,
  and `@` between name and version. No value can contain `|`, `=` or `@`, so the text is
  unambiguous.
- Every allowed character is ASCII, so the UTF-8 encoding of the text equals its ASCII
  bytes and no Unicode normalization is needed.

**Seed.** `seed = int.from_bytes(SHA-256(UTF-8 bytes of the text)[0:4], "big") & 0x7FFFFFFF`,
a value from 0 to 2,147,483,647. If the seed is excluded (below), `n` goes up by 1 and the
seed is derived again. `n` changes for no other reason.

**`candidate_config_sha256`.** The SHA-256, as 64 lowercase hex characters, of the
canonical JSON of the candidate's own record only: `name`, `version`, `settings`,
`uses_holiday_calendar` and `uses_planned_promotions`. Canonical JSON means: object keys
sorted by Unicode code point; separators `,` and `:` with no whitespace; strings use
standard JSON escaping only where JSON requires it (`\"`, `\\`, and control characters
U+0000 to U+001F as `\b`, `\f`, `\n`, `\r`, `\t`, or otherwise `\u00XX` in lowercase hex),
and every other character, including non-ASCII ones, is written as-is (no `\uXXXX` ASCII
escaping); integers in plain decimal; no NaN or infinite values; encoded as UTF-8 with no
trailing newline. This is the output of Python's `json.dumps(value, sort_keys=True,
separators=(",", ":"), ensure_ascii=False, allow_nan=False)`.
`settings` values may only be strings, integers, booleans, `null`, arrays or objects of
these. Floats are not allowed; a decimal value is written as a string. This differs from
the run-level `config_hash` (section 9.3), which covers every model in the run, baselines
included.

**Excluded seeds.** 42, 7, 1 to 10, and every seed already registered for an earlier
decision. Future exclusions are added to this list with a date and a reason. Nothing is
ever removed from it.

**Order.**
1. Freeze the candidate.
2. Compute `candidate_config_sha256`.
3. Derive the seed.
4. Record every input, the final `n` and the seed in the candidate's version-controlled
   spec.
5. Commit.
6. Only then generate the decision dataset.

**Rules.**
- A frozen candidate is never retuned against its decision dataset.
- Before every formal run, the harness derives the seed again from the recorded inputs and
  refuses to run if `metadata.json` `seed` differs (`seed` is evaluation-only data,
  section 4.4).
- The seed is reproducible, not secret. The protection is the recorded order of steps and
  Git history.

## 6. Baseline forecasts
Both forecast every visible series independently, for horizons h = 1 to the origin's
horizon (28 for backtest folds; 28, 28, 28 and 6 for the holdout origins).

### 6.1 Seasonal naive (main baseline)
The last observed week, repeated forward, with a weekly fallback for closed source days
(D15). For cutoff `c` and horizon `h`:

```
s0 = c - 6 + ((h - 1) mod 7)
source = s0 - 7 * j, for the smallest j >= 0 such that source >= start and source is open
forecast(c + h) = y(source), or 0 if no such source exists
```

So day `c + 1` normally gets the value of day `c - 6` (lag 7), day `c + 7` gets `y(c)`,
and day `c + 8` again gets `y(c - 6)`. If the source day is closed, the same weekday one
week earlier is used (lag 14), then two weeks earlier (lag 21), and so on. Because the
only closed days are Dec 25 and Jan 1, which are 7 days apart, lag 21 is the furthest the
search ever needs to go. If no open source day exists on or after `start`, the forecast is
0 and the diagnostic counter `zero_fallback_count` goes up by one per affected forecast
value.

Name `seasonal_naive`, version `"1.0"`, settings
`{"lag_days": 7, "closed_day_fallback": "weekly"}`, `uses_holiday_calendar: true`,
`uses_planned_promotions: false`.

### 6.2 Naive (sanity check, report only)
`forecast(c + h) = y(c)` for every h. No closed-day handling. Name `naive`, version
`"1.0"`, settings `{}`, `uses_holiday_calendar: false`, `uses_planned_promotions: false`.
Naive is reported only. It is never part of the acceptance gate and never served.

### 6.3 Closed days and other edge cases
- **Holiday calendar (D17).** December 25 and January 1 are fixed business-calendar
  constants in the forecasting module, matching spec 001 section 5.7. The module never
  reads `metadata.json` `parameters`. A model that uses this calendar declares
  `uses_holiday_calendar: true`.
- **Closed target days.** A closed day inside a forecast window gets a normal forecast. It
  is left out of the acceptance gate and of open-day metrics, and included in all-day
  metrics (section 7).
- **Products not visible at the cutoff** get 0 from the evaluator (section 4.2).
- **Short history.** Section 5.1 always gives at least 276 training days, so the fallback
  to 0 happens only for cutoffs within 20 days of `start` (for example a cutoff of
  2023-01-07, whose Sunday source day 2023-01-01 is closed and lies at `start`).

## 7. Metrics
`A` is actual, `F` is forecast. Every metric is computed for two **day scopes**:
- `open`: open days only (closed days removed). **The acceptance gate uses only this
  scope.**
- `all`: every date in the window, closed days included. Reported only.

### 7.1 Per level, per window
For one model, one level, one window and one day scope, over all series s of the level
(including inactive series) and all dates d in scope:

| Metric | Formula | When undefined |
|---|---|---|
| WAPE | `sum |F - A| / sum A` (pooled over series and dates) | `sum A = 0`: `null` |
| MAE | `mean |F - A|` over all series-date pairs, in units | never (an empty scope is an internal error, D26) |
| Bias | `sum (F - A) / sum A` | `sum A = 0`: `null` |
| MASE (report only) | mean and median of `MASE_s` over eligible series (section 7.2) | no eligible series with a defined `MASE_s`: `null` |
| RelMAE | section 7.3 | section 7.3 |

Whether a WAPE is `null` depends only on the actuals, so it is the same for every model.

**Empty scope (D26).** Every window of section 5.1 has at least 6 consecutive days and
the closed days are 7 days apart, so every scope holds open days, and every level has at
least one series. A scope with no series-date pair is therefore an internal error: MAE,
per-series MAE (used by MASE and RelMAE) and RelMAE stop with `ForecastingError`. A
non-finite per-series MAE (`NaN` or infinity) is refused the same way and is never
counted as a tie.

### 7.2 MASE for one series (report only)
```
MASE_s = mean over window of |F - A|  /  scale_s
scale_s = mean of |y(t) - y(t - 7)| over training days t with t - 7 >= start,
          leaving out every pair where t or t - 7 is a closed day
```
Training days run from `start` to the cutoff. `scale_s = 0` gives `MASE_s = null`. If no
training day t has `t - 7 >= start` with both t and `t - 7` open, `scale_s` is undefined
and `MASE_s` is `null` in the same way (D25). This cannot happen for the windows of
section 5.1, and MASE never affects the gate.
MASE is reported (mean and median per level) but is never part of the acceptance gate.

**Clarification (2026-11-01, D31).** For the holdout, scored as one 90-day window from four
origins, `scale_s` uses training days from `start` to the holdout cutoff `H` only. Taking a
later origin's cutoff would put holdout days into the scale, so `H` is the one choice that
keeps every holdout observation out of it (no leakage, section 4). MASE stays report only.

### 7.3 RelMAE
For a candidate and seasonal naive on the same window, day scope and series s:
`MAE_c,s` and `MAE_b,s` are the mean absolute errors of the candidate and the baseline.
Only **eligible** series count: series not excluded as inactive (section 7.4).

| Case | Treatment | Counter |
|---|---|---|
| `MAE_b,s > 0` and `MAE_c,s > 0` | `r_s = MAE_c,s / MAE_b,s` enters the geometric mean | none |
| `MAE_b,s = 0` and `MAE_c,s > 0` | Baseline perfect: candidate loss. Left out of the geometric mean. | `n_base_perfect` |
| `MAE_b,s > 0` and `MAE_c,s = 0` | Candidate perfect: candidate win. Left out of the geometric mean. | `n_cand_perfect` |
| `MAE_b,s = 0` and `MAE_c,s = 0` | Tie. Left out of the geometric mean. | `n_tie` |

`RelMAE = exp(mean over included series of ln r_s)`, where the included series are only
those in the first row of the table. If no series is included, `RelMAE` is `null`.

How the other three cases affect the result:
- They never enter the geometric mean, so they move `RelMAE` neither up nor down. A
  perfect-candidate series gives the candidate no `RelMAE` credit, and a perfect-baseline
  series gives it no `RelMAE` penalty.
- Their errors still count in WAPE (section 7.1), so they still affect gate condition 1
  and the WAPE part of every fold win (section 8).
- `n_base_perfect`, `n_cand_perfect` and `n_tie` are reported for every level, window and
  day scope. "Loss" and "win" in the table describe the series only; the counters are
  diagnostics and are not an acceptance condition of their own. A fold is won or lost only
  by the rule in section 8 (WAPE strictly lower and fold `RelMAE` strictly below 1), and a
  fold whose `RelMAE` is `null` is not won.

**Total level.** There is one series, and the candidate and the baseline are scored on the
same open days with the same actuals, so a fold's `RelMAE` equals
`WAPE_candidate / WAPE_baseline` whenever both are defined and the baseline WAPE is above
0. The 13-fold aggregates can still differ, because condition 1 of section 8 uses an
arithmetic mean of WAPE and condition 2 a geometric mean of `RelMAE`.

### 7.4 Inactive series
Using evaluation-only product dates (section 4.4), a product-region series is **inactive
for a window** if its product is not active (spec 001 section 4) on any day of that
window. Inactive series:
- are excluded from per-series MASE and from `RelMAE`, and counted as `n_inactive`,
- stay in WAPE, MAE and Bias, where any non-zero forecast on them counts as error.

For `total` and `category`, a series is inactive only if every product in it is inactive
for the whole window.

### 7.5 Averages over folds
For a level and day scope:
- **Mean WAPE** = arithmetic mean of fold WAPE over the **WAPE-eligible folds**: the folds
  where WAPE is defined. A fold's WAPE is `null` only when `sum A = 0` (section 7.1), which
  depends on the actuals alone, so the eligible folds are the same for every model being
  compared. A `null` WAPE is never averaged and never treated as 0. If no fold is
  WAPE-eligible, mean WAPE is `null`.
- **Mean RelMAE** = geometric mean of fold `RelMAE` over the folds where it is not `null`.
  If every fold is `null`, it is `null`.
- **Fold wins** are counted over the **fixed 13 folds**, not over the eligible folds. A
  fold whose WAPE or `RelMAE` is `null` cannot be won, still counts in the 13, and the
  requirement stays at least 10 wins out of 13 (section 8). So excluding a `null` fold
  from a mean never lowers the number of wins needed.
- MAE, Bias and MASE are averaged arithmetically over non-null folds and reported with the
  number of folds used.

### 7.6 Signal recovery (spec 001 section 6.3, synthetic only)
For each model, level, window and day scope, with `X` the expected units summed to the
same key and date:
- Signal WAPE = `sum |F - X| / sum X`
- Noise floor = `sum |X - A| / sum A`

These go in a separate table labeled "Signal recovery (synthetic only)". They are never
mixed with, averaged into or traded off against sections 7.1 to 7.5, and the gate never
uses them.

## 8. Acceptance gate (D9)
The gate compares a candidate with seasonal naive from the **same run**, using day scope
`open` and unrounded float64 values. Thresholds are inclusive. The gate is evaluated
separately at each level: `total`, `category`, `product_region`.

At one level, with `W_c`, `W_b` the mean WAPE of the candidate and the baseline over the
WAPE-eligible backtest folds, and `R` the candidate's mean RelMAE (both as defined in
section 7.5):

| # | Condition | Fails when |
|---|---|---|
| 1 | `W_b > 0` and `1 - W_c / W_b >= 0.05` | `W_b = 0`, `W_b` or `W_c` is `null`, or the improvement is below 5% |
| 2 | `R <= 0.95` | `R` is `null` or above 0.95 |
| 3 | At least 10 of the 13 folds are **won** | fewer than 10 wins |
| 4 | Holdout: candidate WAPE `<=` baseline WAPE and holdout `RelMAE <= 1` | either holdout value is `null`, or either comparison fails |

A fold is **won** only when both its WAPE values are defined, candidate WAPE is strictly
lower than baseline WAPE, and its `RelMAE` is defined and strictly below 1. Ties are not
wins. A fold with a `null` WAPE or `null` `RelMAE` is lost and stays in the denominator
of 13.

Holdout WAPE is pooled over all open days of the four origins. Holdout `RelMAE` uses
per-series MAE over all open holdout days, with the rules of sections 7.3 and 7.4 applied
to the whole 90-day holdout as one window.

**Verdict.** A level passes only if all four conditions hold. The candidate is accepted
(`pass`) only if all three levels pass. The run's `decision` is:
- `not decided` for every exploratory run (section 9.5), and for a formal backtest run that
  passes conditions 1 to 3 at all three levels (the holdout is still needed),
- `fail` for a formal backtest run that fails condition 1, 2 or 3 at any level, and for a
  formal holdout run that fails condition 4 at any level,
- `pass` only for a formal holdout run where all four conditions hold at all three levels.

Seasonal naive is the reference and is not gated against itself. Naive is never gated.

**Baseline sanity check (report only).** If seasonal naive's mean WAPE at the `total`
level is not lower than naive's, the run records a warning. It does not block anything.
There is no performance threshold for the baselines.

## 9. Results record

### 9.1 Where
- Every run writes one new folder `evals/results/<run_id>/` (gitignored). A holdout run
  creates its folder only after step 4 of section 9.4 is durable; a holdout run refused
  before that creates none.
- Holdout runs also append to `evals/holdout-log.csv`. This file is outside the ignored
  folder and is meant to be tracked by Git.
- The holdout lock file is `evals/results/holdout.lock` and the log head record is
  `evals/results/holdout-log.head` (both gitignored; section 9.4).
- The incident record is `docs/incidents/holdout-integrity.md` (section 9.8). It is
  Git-tracked and written by a person, never by the harness.
- The harness writes nowhere else and never changes the data folder or `docs/`. The paths
  of the results folder, the log and the lock are parameters, so tests can use temporary
  folders.

### 9.2 Files in a run folder (D10)
| File | Content |
|---|---|
| `run.json` | The run record (section 9.3) |
| `metrics.csv` | One row per model x level x window (`fold_01` to `fold_13`, `mean`, `holdout`) x day scope: WAPE, MAE, Bias, MASE mean and median, RelMAE, and the counters of sections 7.3 and 7.4 |
| `series_metrics.csv` | One row per model x window x day scope x product-region series: MAE, `scale_s`, `MASE_s`, `r_s`, eligibility and inactive flags |
| `signal_recovery.csv` | Section 7.6, in its own file |

Holdout-stage files are written only after all four origins are scored.

### 9.3 `run.json` fields
| Field | Value |
|---|---|
| `run_id` | Folder name (section 9.6) |
| `created_at` | UTC time, `YYYY-MM-DDTHH:MM:SSZ` |
| `spec` | `"003"` and this spec's status line |
| `stage` | `"backtest"` or `"holdout"` |
| `run_class` | `"exploratory"` or `"formal"` |
| `decision_grade` | `false` for exploratory runs, `true` for formal runs |
| `decision` | `"pass"`, `"fail"` or `"not decided"` (section 8), with per-level, per-condition results |
| `config_hash` | SHA-256 of the canonical JSON (section 5.4 rules) of a JSON array with one object per model holding its `name`, `version`, `settings`, `uses_holiday_calendar` and `uses_planned_promotions`, the objects sorted by `name`, then by `version` in numeric order: the parts between dots are compared as integers from left to right (so `1.9` sorts before `1.10`); a version that runs out of parts first sorts first (`1.0` before `1.0.0`); if still equal (only leading zeros differ, as in `1.01` and `1.1`), the version strings are compared as text (run level, all models). The candidate-only `candidate_config_sha256` is defined in section 5.4. |
| `code_version` | `dealpilot.__version__`; for formal runs the git commit and `clean_tree: true` |
| `source_manifest` | Exploratory runs: SHA-256 of every file under `backend/src/`, `specs/`, plus `docs/evaluation.md`, `backend/pyproject.toml` and `backend/requirements-dev.lock` |
| `data` | `seed`, `start`, `end`, `generator_version`; the data folder shown as in spec 002 section 3.7 (relative path as written, or `"<absolute path>"`); SHA-256 of every file read |
| `library_versions` | Python, numpy, pandas, duckdb, pyarrow |
| `calendar` | Holdout dates, holdout cutoff and origins, the 13 cutoffs, horizon per window |
| `models` | For each model: `name`, `version`, `settings`, `uses_holiday_calendar`, `uses_planned_promotions` |
| `levels` | Each level and its series count |
| `diagnostics` | `zero_fallback_count`, `n_inactive`, `n_tie`, `n_base_perfect`, `n_cand_perfect`, the baseline sanity warning |
| `holdout_log` | Holdout runs only: `seq` and SHA-256 of the `started` and `completed` entries, and the log head after `completed` (section 9.4) |
| `decision_seed` | Formal runs only: every section 5.4 input (including `candidate_config_sha256`), the final `n`, the derived seed, the `metadata.json` seed, and whether they match |
| `git_provenance` | Formal runs only: commit, `clean_tree`, the name and exact version of the clean-tree checker, and its libgit2 version (section 9.5) |
| `signal_recovery` | `true` if computed, or `false` with a reason |

**Clarifications (2026-11-01, D31).** The table above is unchanged; these notes record how
the implementation reads it, as approved at the implementation review:
- `source_manifest` covers every source file under `backend/src/` and `specs/` (plus the
  three named files). Generated artifacts under `backend/src/`, namely `__pycache__`
  folders and `*.egg-info` folders, are left out: they are build output, not source, and
  they change between runs, which would break AC-FC-13. Every actual source file stays
  covered.
- `run.json` holds no run duration, because a duration differs between runs and AC-FC-13
  allows only `run_id` and `created_at` to differ. The duration is printed on the console
  and returned to the caller; a run over 60 seconds adds the section 9.7 warning to
  `diagnostics`.
- `metrics.csv` also has `n_folds_wape`, `n_folds_mae`, `n_folds_bias` and `n_folds_mase` on
  the `mean` rows (section 7.5, "reported with the number of folds used").
- RelMAE and its counters are also reported for naive against seasonal naive. They are
  informational only and never used by the gate (section 8).
- A holdout run's `run.json` also has `backtest_verification` (section 9.4, recomputation).

### 9.4 Holdout log (`evals/holdout-log.csv`)
- **Append only.** The file is opened for appending, never truncated or rewritten.
- **Columns:** `seq`, `timestamp_utc`, `event` (`started` or `completed`), `run_id`,
  `config_hash`, `commit`, `data_hash` (SHA-256 of the UTF-8 text made of the 64-character
  lowercase hex SHA-256 of each of the five A1 files, in ascending byte order of file name
  (`metadata.json`, `order_lines.parquet`, `orders.parquet`, `products.parquet`,
  `regions.parquet`), each followed by LF; always all five, whatever else the run reads,
  so signal recovery or `expected_demand.parquet` never changes it; a missing A1 file
  refuses the run in step 3 below),
  `holdout_start`, `holdout_end`, `result` (empty for `started`; `pass` or `fail` for
  `completed`), `prev_sha256`. The hash values `config_hash`, `data_hash` and
  `prev_sha256` are written as 64 lowercase hex characters.
- **Line bytes.** A line's bytes are its UTF-8 bytes **without** its terminating LF. Every
  log-line hash in this spec (`prev_sha256`, the head record, `run.json` `holdout_log`)
  is the SHA-256 of these bytes, as 64 lowercase hex characters.
- **Hash chain.** `prev_sha256` is the SHA-256 of the previous line's bytes (the header
  line for the first entry). `seq` starts at 1 and goes up by exactly 1 per entry.
- **Head record.** After every append, the harness writes the chain head (the last
  entry's `seq` and the SHA-256 of its line bytes) to `evals/results/holdout-log.head`,
  flushed and synced. The file holds exactly `<seq>,<sha256>` followed by one LF and
  nothing else: `<seq>` in decimal with no sign or leading zeros, `<sha256>` as 64
  lowercase hex characters, all ASCII (so UTF-8), no spaces, no CR and no second line.
  Each holdout run also copies the head into its `run.json` (section 9.3). The head
  record is a **local integrity checkpoint** only. It is gitignored and stored next to the
  results, so it is not an independent trusted anchor:
  anyone who can change the log can also change the head record, and a coordinated change
  of both is not detected.
- **Verification before every holdout run.** The harness refuses to run unless all of
  these hold:
  1. the header line is exactly the column names above, in that order, separated by commas,
  2. `seq` values are 1, 2, 3, ... with no gap or repeat,
  3. every `prev_sha256` matches the previous line,
  4. every `completed` entry follows a `started` entry with the same `run_id`, and no
     `run_id` has more than one of each,
  5. the last entry's `seq` and line hash equal the head record (a missing head record
     with a non-empty log also fails).

  What this detects: a modified, deleted, inserted or reordered entry before the last one
  breaks checks 2 or 3. A modified **last** entry has no later entry to expose it, and
  removing entries from the end (truncation) leaves a valid chain; both are caught only by
  check 5. If verification fails, the harness follows the integrity-failure rules below.
- **Log states.** Before checks 1 to 5, the harness classifies the log
  (`evals/holdout-log.csv`) and the head record (`evals/results/holdout-log.head`). A
  "holdout-stage run folder" is any folder in the results folder whose name contains
  `-holdout-` (section 9.6). A holdout run creates its own run folder only after step 4 is
  durable (below), so at step 2 the current run has no folder yet, a run refused in steps 1
  to 3 never leaves one, and any holdout-stage run folder found at step 2 comes from an
  earlier run that reached step 4. Every line of the log, the last one included, ends with
  LF. A line is **complete** when it ends with that LF and **partial** when it does not. A
  complete line can still fail checks 1 to 4.

  | State | Log and head record | Class |
  |---|---|---|
  | Normal | Log has the header and at least one entry; head record present; checks 1 to 5 pass | Valid: the run continues |
  | A | Neither file exists, and the results folder holds no holdout-stage run folder | Valid first use: the run continues |
  | B | Neither file exists, but a holdout-stage run folder exists | Integrity failure |
  | C | Log absent, head record present | Integrity failure |
  | D | Log holds only the header line, with or without a head record | Integrity failure |
  | E | Log has at least one entry, head record missing | Integrity failure (check 5) |
  | F | Log malformed: empty file, wrong header, a line with the wrong number of fields or not valid UTF-8, a last line without LF, or any of checks 1 to 4 fails | Integrity failure |
  | G | Head record present but unreadable (its bytes are not exactly the head-record format above), or its `seq` or hash differs from the last entry | Integrity failure (check 5) |

  - **First use (state A) is the only case where a log is created.** Only the harness
    creates it, only in step 4 of a formal holdout run that passed steps 1 to 3: it creates
    the log exclusively (refusing if it now exists), writes the header line and the
    `started` entry, `fsync`s, then creates the head record. A log or header is never
    created by hand. A log made any other way is classified like any other log (a
    header-only log is state D).
  - **States B to G** are integrity failures. The harness refuses the holdout run before
    anything is appended; creates no log, header or head record; and changes nothing it
    found. It reports the state, and the integrity-failure rules below apply (a person
    investigates and records the incident; the harness never writes the incident record).
  - **Precedence.** If more than one of states B to G applies, the harness reports the
    first one in the order B, C, D, F, E, G.
  - The harness never rebuilds, resets, re-initializes or overwrites a log in any state. A
    missing head record never counts as proof that the log is empty, and a missing log is
    never treated as first use while a head record or a holdout-stage run folder exists.
- **Order of a holdout run.** Hashing input files reads their raw bytes only; it does not
  load, parse, inspect or score observations. The sequence is:
  1. create the lock exclusively (refuse if it exists),
  2. classify and verify the log as above; continue only in the normal state or state A,
  3. compute the configuration hash and the SHA-256 of every input data file; check the
     formal backtest pass for the same hashes, and that no `started` entry exists for the
     same `data_hash` and holdout dates; verify the decision seed (section 5.4) and the
     Git clean-tree prerequisite (section 9.5). These checks happen before `started`, so
     if any of them fails nothing is appended, the lock is removed, and the holdout is
     not consumed,
  4. append the `started` entry with those hashes, `fsync` it, and update the head record
     (in state A: create the log with its header first, as described under "Log states").
     Step 4 is durable once the `started` entry is synced and the head record is written
     and synced. Only then does the harness create the run folder, exclusively, under the
     run ID it chose before step 4 (the first name of section 9.6 whose folder did not
     exist). Creating the folder is the last action of step 4 but comes after its durable
     point, so if it fails the run stops and, like any failure after that point, this
     consumes the holdout,
  5. parse the data from the exact bytes hashed in step 3 (preferred). If the
     implementation must read a file again, it recomputes that file's SHA-256 from the
     bytes it reads and stops if the hash differs from the one computed in step 3,
  6. fit, forecast and score all four origins in memory,
  7. write the CSV files, append the `completed` entry, `fsync` it, update the head
     record, write `run.json` with the final head (to a temporary name in the run folder,
     then renamed, so `run.json` is either complete or absent), and remove the lock.

  No holdout observation is loaded, parsed or scored before step 4 is durable. Any failure
  after step 4 (a hash mismatch in step 5, an error, a crash) consumes the holdout.

  **Backtest recomputation (2026-11-01, D31).** The formal backtest pass checked in step 3
  is read from that run's `run.json`, a local, gitignored file that anyone with access can
  edit. So the holdout run also recomputes it. In step 3 it refuses (before `started`,
  holdout not consumed) when the recorded run used other library versions than the current
  ones or has no `metrics.csv`, since identical numbers are promised only on the same
  machine with the same versions (section 9.6). In step 5, after parsing the hashed bytes
  and before any holdout forecast, it recomputes the 13 backtest folds and compares the
  gate values per level (conditions, means, wins) and the `metrics.csv` bytes with the
  record. Any difference stops the run. The comparison can't run earlier: parsing the data
  files loads holdout observations, which section 9.4 allows only after step 4 is
  durable. So a mismatch, like any failure after step 4, consumes the holdout and keeps
  the lock (integrity-failure rules below). Limits: this is a consistency check, not
  cryptographic proof of trust. It shows that the recorded pass is what the current,
  committed code computes on the hashed data. It does not protect against changes to that
  code, and the log, head record and run records stay locally editable (Limits below).

  **Handled errors from step 4 onward keep the lock.** If writing or syncing the `started`
  entry or the head record fails without a crash (for example an `fsync` error), if the run
  folder cannot be created, or if an error stops steps 5 to 7, the run stops and the
  harness keeps the lock; it never removes it automatically. Data is never loaded when the
  durable point was not reached. The kept lock is handled like a lock left by a crash
  (Lock bullet and integrity-failure rules below), and the log state and consumption are
  read from the files as for a crash. Before step 4 the existing rules are unchanged (a
  failed check in step 3 removes the lock).

  A crash inside step 4 leaves a stale lock. The log state is then read from the files as
  found, with the log-state table and checks 1 to 5, never from when the crash happened or
  whether an `fsync` call returned:
  - no `started` bytes: on first use, a log holding exactly the complete header line is
    state D, while an empty file or a partial header is state F; on a later run the log is
    unchanged and only the stale lock remains,
  - a partial or malformed `started` line (for example no final LF or the wrong number of
    fields), or a `started` line that breaks the chain: state F,
  - a complete `started` line that passes checks 1 to 4, with the head record missing or
    not matching it: state E or G,
  - a complete `started` line and a matching head record, but no run folder: the normal
    state, with the run reported `interrupted`.

  If the files cannot be read or classified with certainty, the harness reports an
  integrity failure; it never guesses. Four questions are kept apart: (1) whether an
  identifiable `started` entry exists: a complete line whose own `event` (`started`),
  `run_id` and `data_hash` fields can be read unambiguously, (2) whether the log and head
  record pass checks 1 to 5, (3) whether step 4 reached its durable point, and (4) whether
  the holdout is consumed. Only (1) decides (4): such an entry found in the log counts as
  durably recorded (section 5.3), so that holdout is consumed even if step 4 never
  completed, its chain link is broken, or other lines fail checks 1 to 4. Damage elsewhere
  in the log never makes it unused. Whether a complete `started` line whose own
  identifying fields cannot be read establishes consumption is not decided by this spec;
  it is left to a separate governance decision. A log that fails checks 1 to 4 is still
  state F, so every holdout run stays refused (see the integrity-failure rules). If
  (2) also fails, the integrity-failure rules below apply as well, and they never make a
  consumed holdout usable again. If the log holds no complete `started` entry for it, the
  log does not establish consumption. Every case follows the integrity-failure rules below,
  because the stale lock alone requires that. None of this authorizes a retry by itself:
  no holdout run is possible until the incident is handled under those
  rules, and any later attempt must still pass every check of this section, including the
  log states and the reuse check in step 3.
- **Interruption.** A crash cannot write anything, so it is not logged at the time. The
  log is the authoritative record of a holdout run's state:

  | Log entries for a `run_id` | `run.json` | Reported state |
  |---|---|---|
  | `started` only | absent (normal case) | `interrupted`: consumed, no result |
  | `started` and `completed` | absent | `completed, record incomplete`: consumed; the result is the `completed` entry's `result`; the missing `run.json` is reported |
  | `started` and `completed` | present | `completed`: consumed; result in both |

  Whatever the run folder holds for an interrupted run (for example CSV files written
  before the crash) is left untouched and is never used as a result. Every holdout
  invocation, and a read-only status report of the log, lists the state of every `run_id`
  so an interruption cannot go unnoticed. The holdout is never retried silently: the same
  `data_hash` and dates are refused from then on.
- **Lock.** If the lock exists, the harness refuses to run. A lock left by a crash, or kept
  after a handled error from step 4 onward, is handled under the integrity-failure rules
  below and is never removed automatically. A
  stale lock alone does not make a holdout consumed: it is consumed only if the log holds
  a durable `started` entry for it (section 5.3), and then it stays consumed.
- **Integrity failure (manual, auditable).** When a log check fails (checks 1 to 5), the
  head record is missing or does not match, the log is in any of states B to G, or a
  stale lock is found:
  1. the harness refuses every holdout run and reports which check failed; backtest-stage
     runs, which never use the log, are not affected,
  2. the harness changes nothing: the log, the head record, the lock and every run folder
     stay byte-for-byte as found,
  3. a person records the incident (date, failed check, files involved, what is known about
     the cause) in the Git-tracked incident record `docs/incidents/holdout-integrity.md`
     (section 9.8),
  4. any corrective action needs explicit human review and the user's explicit approval,
     recorded in that incident record before the action.

  The harness enforces the block only through the lock and the log state it finds. It
  never reads or checks the incident record; recording the incident and approving a fix
  are human procedures.

  Never allowed, by the harness or by hand: automatic repair, truncating the log, deleting
  or editing entries, or resetting a holdout's consumed state. A corrective action may at
  most make the log verifiable again (for example an approved new head record that matches
  the unchanged log). It never makes a consumed holdout usable again. A log that these
  actions cannot make verifiable (for example one with a partial last line, which may not
  be truncated or edited) keeps every later holdout run blocked until a separate,
  explicitly authorized governance decision sets a recovery policy. A new final decision
  still needs a new dataset (D18) unless a separate governance decision says otherwise.
- **Limits.** The chain and head record are tamper-evident for partial or accidental edits
  only; they do not prevent tampering. The head record and `run.json` are local and
  gitignored, so someone who edits the log and the head record together, or rewrites the
  whole log, is not detected. Deleting both the log and the head record looks like first
  use unless a holdout-stage run folder remains (state B) or the log has been committed. A
  run that stops after the durable point but before its run folder exists leaves no such
  folder.
  There is no trusted external anchor until the log is
  committed: from then on, the clean-tree rule for formal runs (section 9.5) makes the
  committed log the reference, and Git history shows later changes. Holdouts are
  identified by the fixed five-file `data_hash`, so a dataset regenerated or edited with
  the same seed and date range (for example after a generator change, or a hand edit to
  `metadata.json`) gets a new `data_hash` and is not recognized as an already-used
  holdout, so it may be scored again. The user chose this byte-based identity on
  2026-10-28; no seed or date matching is added.

### 9.5 Exploratory and formal runs (D14)
- **Exploratory:** allowed without a git commit, backtest stage only. `decision_grade` is
  `false`, `decision` is `not decided`, and `run.json` holds the `source_manifest`. The
  manifest detects whether source files changed between runs, but it **cannot restore old
  source code**, because no copy is kept.
- **Formal:** requires an existing git commit and a clean working tree (no changes and no
  untracked files outside ignored paths). The commit hash is recorded. The holdout stage
  is formal only. Because the holdout log is tracked, it must be committed before the next
  formal run.
- **No commit is created under this spec.** Today the repository has no commits, so only
  exploratory runs are possible.
- **Formal-run authorization.** The Git clean-tree check is **one prerequisite**; it never
  authorizes a run on its own. A formal run needs all of these:
  - both stages: an existing commit, a verified clean tree, a passing decision-seed check
    (section 5.4), and the run classed as formal;
  - holdout stage: in addition, every holdout condition of section 5.3 (a formal backtest
    pass for the same configuration hash and `data_hash`, holdout not consumed, log verified)
    and the run order of section 9.4.

  All holdout-consumption and decision rules (D12, D18) are unchanged.
- **No subprocess, no exception, no workaround.** Clean-tree checks never use a
  subprocess in `src/`, and never add a Ruff exception or anything that gets around Ruff
  (D14).
- **Clean-tree checker: O2 closed (2026-11-01, D30).** The checker is **pygit2**, as an
  optional `formal` extra loaded only for formal runs. Plan approved (gate 1); code
  written and accepted (gate 2, D27, D28); pygit2 1.20.1, cffi 2.1.1 and pycparser 3.12
  **approved** as dependencies (gate 3); installed in the project virtual environment
  (gate 4); internal-use license accepted (gate 5, D29); AC-FC-26 run and **passed**
  (gate 6), with libgit2 1.9.7 verified at runtime. The closure of O2 does **not**
  authorize formal evaluations and does not make them available: the repository has no
  commit yet, and a formal run still needs a first commit, a verified clean working tree
  (CLEAN) and every other condition of this section, under its own authorization.
- **Fail closed.** Even with an approved checker, a formal run is refused when the checker
  cannot be imported; when there is no repository, the repository is bare, or there is no
  `HEAD`; when the repository root is not the project root; when any staged change,
  modified, deleted or renamed tracked file, untracked non-ignored file, merge conflict or
  unreadable file is reported; and on any error or unknown status. Ignored paths do not
  count. A clean result is never assumed; the checker must return it explicitly.

### 9.6 Run IDs and reproducibility
- **Run ID:** `YYYYMMDDTHHMMSSZ-<stage>-<first 8 hex characters of config_hash>`. The
  folder is created exclusively. If it already exists, the harness tries the suffixes `-2`
  to `-99` in order; if all exist, it fails. It never overwrites anything.
- **Format:** CSV and JSON are written as UTF-8 with LF line endings. Numbers use the
  `%.10g` format. Rows are sorted by model, level, window, day scope, then key. Decisions
  never use the rounded file values (section 8).
- **Byte-identical output:** on the **same machine with the same dependency versions**,
  the same data and settings give byte-identical CSV files and a `run.json` that differs
  only in `run_id` and `created_at`. No promise is made across machines or library
  versions.
- Baselines use no randomness. Any future model that does must take its seed from the run
  settings and record it.

### 9.7 Runtime (D23)
- **Target:** a complete backtest stage on the default data in under 60 seconds. It is a
  target, not an enforced limit.
- **Measurement, after implementation:** 5 consecutive runs on the same machine.
- **Workload:** seed 42, 2023-01-01 to 2025-12-31; 13 folds, both baselines, 3 levels,
  both day scopes, signal recovery on; exploratory runs.
- **Timing boundary:** the backtest stage only. Interpreter start-up, data generation and
  test fixtures are excluded.
- **Recorded:** the environment (OS, Python, processor, CPU count, library versions), the
  workload, each run's duration, the median and the maximum.
- **Warning:** a run over 60 seconds shows a warning in the console and in `run.json`
  `diagnostics`.
- **No hard limit,** and no timing assertion in the default test suite.

### 9.8 Incident record (D24)
- **Path:** `docs/incidents/holdout-integrity.md`. A single Git-tracked, append-only
  Markdown file, created by a person at the first incident. The harness never creates or
  writes it.
- **Each entry contains:**
  1. incident ID (`INC-NNN`) and UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`),
  2. the failed integrity check and the harness's diagnostic message,
  3. fingerprints of the log, head record, lock and affected run folders,
  4. the affected `run_id`s and their reported states,
  5. why formal holdout runs are blocked, and since when (UTC),
  6. the human review findings,
  7. the user's explicit approval, quoted with its UTC date, recorded before any
     corrective action,
  8. the exact corrective action with before and after hashes,
  9. the final verification result and status (`open` or `closed`).
- **Rules (as in section 9.4):** repository-relative paths only; no secrets and no raw
  evaluation data beyond what an entry needs; original artifacts are kept; no automatic
  repair, no silent truncation, no deleting or editing earlier entries (corrections are
  dated updates); a consumed holdout is never reset or made usable again.

## 10. `/v1/forecasts`: deferred proposal (D11, not approved, not in scope)

**Update (2026-11-04).** D11 is approved (section 12.2) and the endpoint is served as
below; the criteria AC-FC-API-01 to 05 are binding. The heading and the text below are
kept as written; where they say "not approved" or "would", read "approved" and "does".
Sessions protect it in the public demo like every `/v1` route (spec 014).
Spec 002 D10 and AC-API-17 say `/v1/forecasts` returns 404 in v1. This spec does not
change that and builds no endpoint. Spec 002 section 6 says "Spec 003 may change any of
it", so the notes below refine that planned contract without editing spec 002. Serving it
needs approval of D11 and an approved update to spec 002 (D10, AC-API-17).

`GET /v1/forecasts`

| Parameter | Rule | Error |
|---|---|---|
| `level` | Required. `total`, `category` or `product_region`. | Missing or other value: 422 `invalid_parameter` |
| `category` | Required when `level=category`, otherwise not allowed. | Missing, extra or repeated: 422 `invalid_parameter`. Empty: 422 `invalid_filter`. Not in the data: 422 `invalid_filter` |
| `product_id`, `region_id` | Both required when `level=product_region`, otherwise not allowed. | Same as `category` |
| `cutoff` | Date. Default: dataset `end`. | Not a date: 422 `invalid_date`. Before `start` or after `end`: 422 `date_out_of_range`. Before `start + 6`: 422 `invalid_parameter` (not enough history) |
| `horizon` | Integer 1 to 28. Default 28. | Otherwise: 422 `invalid_parameter` |

Proposed check order, following spec 002 section 3.5: `unknown_parameter`;
`invalid_date`; `invalid_parameter` (level, horizon, missing or extra key parameters);
`invalid_filter` (empty value); `data_unavailable`; `date_out_of_range`;
`invalid_parameter` (not enough history); `invalid_filter` (value not in the data).

Response shape as in spec 002 section 6, with the served model reported as section 6.1
(`version "1.0"`, settings `{"lag_days": 7, "closed_day_fallback": "weekly"}`). Interval
bounds are `null`. The endpoint would never read `expected_demand.parquet` or
`parameters`.

Proposed criteria, to become binding only with D11:

| ID | Criterion |
|---|---|
| AC-FC-API-01 | For each level, the response equals section 6.1 computed by an independent query, for the default cutoff and one other cutoff |
| AC-FC-API-02 | Every row of the parameter table returns the stated status and `error.code`, in spec 002's error body and check order |
| AC-FC-API-03 | Forecasts don't change when every row after `cutoff` is changed in a copy of the data |
| AC-FC-API-04 | Works with `expected_demand.parquet` removed; no response contains `expected_units`, `parameters` or `base_demand` |
| AC-FC-API-05 | The data folder is byte-identical after the tests (as AC-API-16) |

## 11. Acceptance criteria
Tests go in `backend/tests/test_forecasting_*.py` and are named `test_ac_fc_NN_...`.
Unit tests use small hand-made series and temporary folders for results, logs and locks.
Data tests use the session `default_run` fixture from `conftest.py` (seed 42, default
range). Expected values come from the formulas in this spec or an independent DuckDB or
pandas query, never from the code under test. No performance threshold is set for the
baselines.

| ID | Criterion | How to test |
|---|---|---|
| AC-FC-01 | Default calendar | On the default data the harness gives exactly the dates in section 5.2: holdout 2025-10-03 to 2025-12-31 (90 days), holdout cutoff 2025-10-02, the 13 fold cutoffs and windows, and the 4 holdout origins with horizons 28, 28, 28, 6. |
| AC-FC-02 | Calendar for any valid range | For ranges of 730 and 1,096 days: holdout is the last 90 days; 13 cutoffs exactly 28 days apart; test windows are 28 days, back to back, the last ends on the holdout cutoff, none overlaps the holdout; 4 holdout origins as in section 5.1; the earliest fold has at least 276 training days. |
| AC-FC-03 | Series are complete | Every series has one value for every date from `start` to `end`; 0 on closed days and days without sales; series counts are 1, 5 and 250; each `total` and `category` value equals the sum of its `product_region` values; `total` equals an independent `SUM(quantity)` per `order_date`. |
| AC-FC-04 | Seasonal naive formula | On hand-made series with distinct values: horizons 1 to 28 equal section 6.1 with the weekly repeat; a closed source day uses lag 14; a source day whose lag 14 is also closed uses lag 21; with cutoff 2023-01-07 on data starting 2023-01-01, the Sunday forecast is 0 and `zero_fallback_count` counts it. |
| AC-FC-05 | Naive formula | Every forecast equals `y(cutoff)`, including a closed cutoff day (forecast 0). |
| AC-FC-06 | No future data | For each model, each backtest cutoff and each holdout origin, changing every value after that cutoff (in a copy) gives identical forecasts. |
| AC-FC-07 | No hidden inputs | The metadata reader used by model code returns only `start` and the cutoff. With `expected_demand.parquet` deleted and `parameters` removed from `metadata.json` (in a copy), forecasts and section 7.1 metrics are identical. |
| AC-FC-08 | WAPE | Hand cases for both day scopes: perfect forecast gives 0; a known case gives the exact value; `sum A = 0` gives `null`; a closed day changes the `all` value but not the `open` value. |
| AC-FC-09 | MASE (report only) | Hand cases: known `scale_s` and `MASE_s`; pairs with a closed `t` or `t - 7` are left out of `scale_s`; `scale_s = 0` gives `null`; the level mean and median use only defined values. A history with no usable pair gives a `null` scale and MASE (D25). |
| AC-FC-10 | MAE and Bias | Hand cases with exact values for both day scopes; Bias is `null` when `sum A = 0`. A scope with no series-date pair raises `ForecastingError` for MAE and per-series MAE (D26). |
| AC-FC-11 | Backtest ignores the holdout | Changing every value after the holdout cutoff (in a copy) gives byte-identical backtest `metrics.csv` and `series_metrics.csv`. |
| AC-FC-12 | Results record | A run creates exactly one new folder under the chosen results folder with the four files in section 9.2 (a holdout run only after step 4 of section 9.4 is durable; a holdout run refused in steps 1 to 3 creates none); `run.json` has every field in section 9.3; a holdout run also appends exactly two log entries and updates the head record; nothing else is written; every file in the data folder has the same bytes as before. |
| AC-FC-13 | Reproducible | Two runs on the same data, machine and dependency versions give byte-identical CSV files (UTF-8, LF, `%.10g`, sorted rows) and `run.json` files that differ only in `run_id` and `created_at`. |
| AC-FC-14 | Signal recovery is separate | `signal_recovery.csv` matches section 7.6 on a hand case; `metrics.csv` has no signal columns; the gate gives the same answer when signal values change. |
| AC-FC-15 | Acceptance gate | Table-driven cases on hand-made metric tables, each checking the verdict: all conditions met at all levels gives `pass`; each single condition failing at a single level gives `fail`; improvement of exactly 5% and mean RelMAE of exactly 0.95 pass (inclusive); `W_b = 0` fails condition 1; a fold with `null` WAPE or `null` RelMAE is lost and 13 stays the denominator; a tied fold is not won; `null` holdout WAPE or RelMAE fails; a formal backtest pass gives `not decided`; an exploratory run gives `not decided`; with 2 `null`-WAPE folds, mean WAPE averages the other 11 folds (never treating `null` as 0) while wins are still counted out of 13; changing only `n_base_perfect`, `n_cand_perfect` or `n_tie` (same WAPE and RelMAE values) gives the same verdict. |
| AC-FC-16 | Full baseline run | On the default data the backtest stage finishes and records both models, 3 levels, 13 folds plus the mean, for both day scopes, with no `null` WAPE at any level. The duration is recorded per section 9.7; a duration above 60 seconds produces the warning in the console and in `run.json` `diagnostics`; there is no timing assertion. Marked slow. |
| AC-FC-17 | Cutoff-visible inputs | At a cutoff before a product's launch, model code receives no row for it; a `discontinue_date` after the cutoff is null; regions have only `region_id`; metadata has only `start` and the cutoff (no `end`, `row_counts`, `seed`, `parameters`); not-yet-visible series get 0 from the evaluator. The holiday constant equals spec 001 section 5.7 and `metadata.json` `parameters.closed_days` (read by the test only). |
| AC-FC-18 | RelMAE | Hand cases, one per row of the section 7.3 table: (a) baseline error > 0 and candidate error > 0: `r_s` enters the geometric mean with the exact value; (b) baseline error = 0 and candidate error > 0: left out, `n_base_perfect` + 1; (c) baseline error > 0 and candidate error = 0: left out, `n_cand_perfect` + 1; (d) both errors = 0: left out, `n_tie` + 1. Adding a (b), (c) or (d) series to a fold does not change its `RelMAE`. A fold with only (b), (c) and (d) series has `RelMAE` `null` and is not won. A fold with many (c) series but `RelMAE >= 1` from its (a) series is not won. At the `total` level fold RelMAE equals the WAPE ratio. A `NaN` or infinite per-series MAE raises `ForecastingError` and is never counted as a tie (D26). |
| AC-FC-19 | Holdout log and governance | In a temporary log and results folder: the steps of section 9.4 run in order, with file hashes computed before `started` and no observation loaded or scored before `started` is synced and the head record updated; a data file changed after `started` stops the run and the holdout stays consumed; a handled error injected without a crash (a failed `fsync` of the `started` entry, a failed head-record write, a failed run-folder creation, an error in step 5) stops the run, loads no data when the durable point was not reached, and keeps the lock, so the next attempt is refused for that lock; a failed check in step 3 removes the lock; with a valid `started` entry for a run and another line of the log modified so the chain or a field check fails, the log is refused as state F and the status report still lists that run's `started` entry as consumed; a `started` entry without `completed` blocks a new holdout for the same `data_hash` and dates; each of these is refused: a modified middle entry, a deleted entry, two swapped entries, a truncated log, a modified last entry, a head record that doesn't match, a missing head record; after each refusal the log, head record, lock and run folders are byte-identical to before; log states of section 9.4, each set up in a temporary folder: (A) with no log, no head record and no holdout-stage run folder, the run creates the log with exactly the header line and one `started` entry whose `prev_sha256` is the SHA-256 of the header line's UTF-8 bytes without its LF, then a head record whose bytes are exactly `1,<SHA-256 of that entry's bytes without its LF>` and one LF; (B) the same but with a holdout-stage run folder present, (C) a head record but no log, (D) a header-only log, with and without a head record, (E) a log with entries but no head record, (F) an empty log file, a wrong header, a line with the wrong number of fields, a last line without LF, and (G) an unreadable head record (no final LF, a CR, a space, uppercase hex, a leading zero in `seq`, or a second line), and one whose `seq` or hash differs from the last entry: each of B to G is refused before anything is appended, reports its state, creates no log, header or head record, and leaves the log, head record, lock and run folders byte-identical to before; an existing lock is refused; a run stopped after `started` is reported as `interrupted` with no `run.json`, and one stopped after `completed` but before `run.json` is reported as `completed, record incomplete`; `run.json` is never left half-written; the holdout stage is refused without a formal backtest pass for the same configuration hash and `data_hash`; `data_hash` equals an independent SHA-256 over the five A1 file hashes in the order of section 9.4, written as 64 lowercase hex characters; with the same five A1 files, turning signal recovery on or off or removing `expected_demand.parquet` gives the same `data_hash`, so a second holdout on that data is refused; data whose A1 files differ (a different `data_hash`) is not blocked by an earlier `started` entry; a missing A1 file refuses the run in step 3 and appends nothing; a failed clean-tree or decision-seed check in step 3 appends nothing and leaves the holdout not consumed; a first-use attempt refused in steps 1 to 3 leaves no log, head record or run folder, and the next attempt is still classified as state A; no holdout run folder exists before the `started` entry is synced and the head record is written; after a simulated first-use crash in step 4, with a stale lock and these post-crash files set up by the test (no write is assumed to survive): (i) a header-only log and no head record (no `started` bytes written), (ii) the header and a complete `started` line and no head record (as left when the crash came before `fsync` returned), (iii) the header and a partial `started` line without its final LF and no head record, (iv) the header, a complete `started` line and a matching head record, and no run folder; the next attempt is refused for the stale lock, and with the lock removed by the test it is classified as (i) D, (ii) E, (iii) F, or (iv) normal with the run reported `interrupted` and no run folder; (i) to (iii) are refused as integrity failures with every file byte-identical to before, so no retry runs while the incident is open; in (i) and (iii) the status report lists no `started` entry for that run (consumption not established by the log); in (ii) and (iv) the holdout counts as consumed, and once the log is verifiable (in (ii), after the test writes a head record matching the unchanged log, standing for an approved fix) the same `data_hash` is refused in step 3 as consumed; with a crash injected in step 3 (before `started`), the next attempt is refused for the stale lock, and with the lock removed by the test (standing for a handled incident) no `started` entry exists for that `data_hash`, so the attempt is not refused as consumed and still runs every check of section 9.4; when several of states B to G apply, the first in the order B, C, D, F, E, G is reported; the harness never creates or writes `docs/incidents/holdout-integrity.md`. |
| AC-FC-20 | Holdout origins | The configuration hash is identical at all four origins; each origin's fit uses only data up to its cutoff; no run file exists before all four origins are scored (checked by failing the fourth origin on purpose: no metrics files, `started` without `completed`). |
| AC-FC-21 | Inactive series | A series inactive for the whole window is left out of MASE and RelMAE and counted in `n_inactive`, and its errors still count in WAPE. |
| AC-FC-22 | Day scopes | Every metric is reported for `open` and `all`; the gate reads only `open`; a forecast error on a closed day changes `all` metrics only. |
| AC-FC-23 | Run classes | An exploratory run has `decision_grade: false`, `decision: "not decided"` and a `source_manifest`; a formal run is refused when there is no commit or the tree is not clean; while O2 is open every formal run is refused; with fake checkers, each fail-closed case in section 9.5 refuses the run, and a clean result alone, with any other section 9.5 condition missing, still refuses. |
| AC-FC-24 | Run ID collisions | With the run folder already present, the next run uses `-2`; with `-2` to `-99` also present, the run fails; no existing file changes. |
| AC-FC-25 | Decision seed | With made-up inputs (no real decision seed is chosen), the derived seed equals the section 5.4 formula computed independently; each field that breaks its pattern refuses the run; the canonical JSON matches section 5.4, and a float in `settings` is refused; an excluded seed raises `n` by 1 and nothing else does; a `metadata.json` seed that differs from the derived seed refuses the formal run. |
| AC-FC-26 | Clean-tree checker (**PENDING, O2**) | Not binding, not authorized and not run; pygit2 is not validated. Runs only after dependency approval and passes only after a successful run. In temporary repositories, the checker's result matches `git status --porcelain=v1 --untracked-files=all` (tests may call `git`; S603 is exempt only for `tests/**`) for: modified, deleted, renamed and type-changed tracked files; staged changes; untracked non-ignored files; ignored files, including negated patterns such as `!.env.example`; merge conflicts; no repository, a bare repository, no `HEAD`, a repository in a parent folder; `.gitattributes` `eol=lf` with `core.autocrlf` true and false; case-only renames; error handling; and `.git/index` is byte-identical before and after. Result note (2026-11-01): run once under O2 gate 6 with the user's explicit authorization: 56 passed, 0 failed, 0 skipped, 859 deselected (D30, section 13.3). The "PENDING" wording above records the state before that run. |

## 12. Decisions

### 12.1 Approved (confirmed by the user, 2026-10-28)
| ID | Decision |
|---|---|
| D3 | Target is daily units only. |
| D4 | The scoring universe comes from `products` and `regions`; all 250 product-region series are scored; evaluation alone knows the full universe; series not visible at a cutoff get 0 from the evaluator. |
| D6 | 13 backtest folds of 28 days; the 90-day holdout is scored from four sequential origins with horizons 28, 28, 28, 6, refitting at each origin with the frozen configuration. |
| D7 | Fold averages as in section 7.5; level WAPE pooled; RelMAE as in section 7.3. |
| D8 | Candidates are compared with seasonal naive by WAPE and RelMAE; MASE is report only, with closed-day pairs left out of its scale. |
| D9 | Acceptance gate of section 8: per level, at least 5% better mean WAPE, mean RelMAE `<= 0.95`, at least 10 of 13 folds won (WAPE strictly lower and RelMAE strictly below 1, ties not won), holdout WAPE and RelMAE not worse; all three levels must pass; unrounded float64; inclusive thresholds; every `null` case fails or loses the fold as in section 8. |
| D10 | Results files, `run.json` fields, output format and run IDs as in section 9. |
| D12 | Holdout governance and log as in sections 5.3 and 9.4. |
| D13 | Model-visible inputs as in section 4.3. |
| D14 | Exploratory and formal runs as in section 9.5; no commit is created now; no Ruff exception and no workaround around Ruff; formal runs fail closed until O2 is closed. |
| D15 | Seasonal naive weekly fallback for closed source days, with 0 and a counter when no open source day exists; naive unchanged and report only. |
| D17 | Dec 25 and Jan 1 are fixed constants in the forecasting module; `parameters` is never read; seasonal naive declares `uses_holiday_calendar: true`. |
| D18 | A different recorded seed defines a new dataset for a new decision, with a full backtest rerun; a decision seed distinct from 42 is reserved but not selected or run now; seed 42 is for testing the harness and measuring baselines only. |
| D19 | No blocking baseline performance threshold; first-run metrics are recorded; optional warning if seasonal naive does not beat naive at the total level. 60-second runtime target, not enforced, confirmed after measurement. |
| D20 | Baseline versions: `seasonal_naive` `"1.0"` and `naive` `"1.0"`, independent of the package version. |
| D21 | `docs/evaluation.md` is updated in a separate, explicitly authorized task before this spec can become Approved (section 15). Done 2026-10-28: aligned in an explicitly authorized task; approval of this spec is still required separately. |
| D22 | Deterministic decision seed per formal decision, with exact inputs, canonical forms, exclusions and order as in section 5.4; no seed selected now. |
| D23 | Runtime policy of section 9.7: 5 consecutive measured runs after implementation, warning above 60 seconds, no hard limit. |
| D24 | Incident record `docs/incidents/holdout-integrity.md` as in section 9.8, written by a person, never by the harness. |

**Review note (2026-10-28).** The D2, D10, D12 and D22 rows are unchanged. After the
decisions were confirmed, the text they point to was clarified in user-authorized editing
tasks: D10, the model order in `config_hash` (section 9.3); D22, canonical JSON escaping
(section 5.4); D12, the fixed five-file `data_hash`, the log states, the line and
head-record bytes, and holdout run-folder timing (section 9.4). The user explicitly
authorized the fixed five-file holdout identity. The other clarifications were not
separately approved as decisions. On 2026-10-28 the user re-confirmed D10, D12 and D22,
chose numeric version order for D10 (section 9.3), kept the byte-based holdout identity
(section 9.4, Limits), chose the strict rule for logs that cannot be made verifiable, and
chose to keep the lock after handled errors from step 4 onward (section 9.4). For D12 the
user also chose that an identifiable complete `started` entry counts as consumed even when
other parts of the log fail the integrity checks (sections 5.3 and 9.4). These are
decision confirmations only; the spec itself was approved separately on 2026-10-28 (status
line).

### 12.2 Pending, deferred or approved later
| ID | Decision | State |
|---|---|---|
| D1 | This spec covers the baselines, the harness, the gate and the results record. | Pending spec approval. Approved 2026-10-30 by the user's explicit authorization. |
| D2 | Code lives in a new `dealpilot.forecasting` module, run with `python -m dealpilot.forecasting.evaluate` (exact options set at implementation review). No new dependencies, except an optional formal-evaluation extra once it is separately approved under O2 (section 9.5); none is approved now. | Pending spec approval. Approved 2026-10-30 by the user's explicit authorization; the dependency limits and the O2 link are unchanged, and no dependency is approved. Later note (2026-11-01): under this decision's O2 exception, the `formal` extra (pygit2 1.20.1, cffi 2.1.1, pycparser 3.12) was approved (O2 gate 3, section 13.3) and its license accepted for internal use (D29); the text of D2 is unchanged. |
| D25 | MASE scale with no usable pair: `scale_s` is undefined and `MASE_s` is `null`, as when `scale_s = 0` (section 7.2). No effect on the gate. | Approved 2026-10-30 by the user's explicit decision (option A). |
| D26 | An empty scope is an internal error: MAE and per-series MAE stop with `ForecastingError`, and RelMAE refuses non-finite per-series MAE instead of counting it as a tie (section 7.1). | Approved 2026-10-30 by the user's explicit decision (option A). |
| D27 | O2 clean-tree controller: the plan of section 13.3 (strict standard-library index reader, pygit2 controller, three outcomes, Windows compatibility profile, path policy, provenance fields) and its implementation in `dealpilot.forecasting.gitindex` and `dealpilot.forecasting.cleantree`. It does not approve the dependency, its installation, the license or AC-FC-26, and does not close O2. | Plan approved 2026-11-01 by the user's explicit decision (O2 gate 1); implementation authorized 2026-11-01 (O2 gate 2). Gates 3 to 6 pending. Later note (2026-11-01): gate 2 accepted (D28), gate 3 approved and gate 5 recorded (D29); gates 4 and 6 pending (section 13.3). The text of D27 is unchanged. Later note (2026-11-01): gate 4 completed (installation, section 13.3); gate 6 pending and not authorized. |
| D28 | AC-FC-26 type changes under the `o2-windows-v1` profile (section 13.3): a tracked entry can change type only when it is a symlink (mode 120000) or a gitlink (160000) entry, and the controller refuses both in phase A (K4 and the index reader), before pygit2 is loaded. This explicit refusal safely covers unsupported type changes and satisfies the type-changed requirement of AC-FC-26. An unsupported type change must never result in CLEAN. No cross-platform symlink support is required under the approved Windows compatibility profile. This does not change AC-FC-26, approve gates 3 to 6 or close O2. | Approved 2026-11-01 by the user's explicit decision, together with the acceptance of O2 gate 2. |
| D29 | License acceptance for internal use (O2 gate 5) of pygit2 1.20.1, libgit2 1.9.7 (bundled in the pygit2 wheel), cffi 2.1.1 and pycparser 3.12, under six conditions: (1) internal use only; (2) no redistribution to customers; (3) no modification of these libraries; (4) applicable copyright and license notices are preserved; (5) the versions stay pinned (`backend/requirements-formal.lock`); (6) any redistribution or change of use requires a new license review. It does not authorize installation (gate 4) or running AC-FC-26 (gate 6), and does not close O2. | Accepted 2026-11-01 by the user's explicit decision (O2 gate 5). |
| D30 | O2 closure record (2026-11-01). All six O2 gates are complete: plan (D27), implementation (D27, D28), dependency approval, installation (`pip check` clean), license (D29) and AC-FC-26 (56 passed, 0 failed, 0 skipped, 859 deselected) with `pygit2==1.20.1` and bundled `libgit2==1.9.7` verified at runtime. O2 is closed. D27, D28 and D29 stay as recorded, and the D29 license conditions remain applicable. The closure does not authorize any formal evaluation: a first Git commit and a verified clean working tree remain prerequisites (sections 9.5 and 13.3). | Approved 2026-11-01 by the user's explicit decision (official O2 closure). |
| D31 | Implementation review of tranche 2 (D2 "exact options set at implementation review"). Approved choices: (1) the command line runs exploratory backtests and a read-only holdout status only; formal runs are Python calls; (2) `source_manifest` leaves out `__pycache__` and `*.egg-info` (section 9.3 clarification); (3) no run duration in `run.json` (console and `diagnostics` warning only); (4) `n_folds_*` columns on `mean` rows; (5) RelMAE for naive, informational only, never gated; (6) holdout MASE scale up to `H` (section 7.2 clarification); (7) one candidate per run, with the formal backtest pass recomputed from the hashed bytes and compared before any holdout forecast (section 9.4 clarification); (8) a backtest run creates its folder after scoring. No formula, threshold or gate rule changes. This approves no formal run. | Approved 2026-11-01 by the user's explicit decision; condition (7) set by the user. |
| D5 | Replaced by D15 and D17. | Superseded |
| D11 | Whether to serve `/v1/forecasts` (section 10), which also needs a spec 002 update. | Deferred. **Approved 2026-11-04** by the product owner's explicit decision: served exactly as section 10 (parameters, check order, response shape, interval bounds `null`); AC-FC-API-01 to 05 are binding; spec 002 D10 and AC-API-17 amended the same day. Implemented in `dealpilot.forecasting.serving` and `dealpilot.api.v1`, tested in `backend/tests/test_forecasting_api.py`. Seasonal naive is the served baseline; the section 8 gate does not apply to it. This approves no formal run. |

## 13. Questions

### 13.1 Closed
| ID | Question | Answer |
|---|---|---|
| Q1 | How is the holdout scored? | Four sequential origins, 28 + 28 + 28 + 6 days (D6) |
| Q2 | How are closed days handled? | Weekly source fallback (D15), holiday constant (D17), gate on open days (section 7) |
| Q3 | Are launch and stop dates used? | Only when on or before the cutoff (D13); the evaluator gives 0 to series not yet visible |
| Q4 | How is MASE aggregated? | Report only, mean and median; RelMAE drives the gate (D8) |
| Q5 | What is the ship rule? | D9 |
| Q6 | What is `code_version` without a commit? | Exploratory runs only, with a source manifest; formal runs need a commit (D14) |
| Q7 | Results format and run IDs? | CSV and JSON, section 9 (D10) |
| Q8 | Baseline performance threshold? | None; record first-run metrics (D19) |
| Q9 | Is seed 42 enough? | For the harness and baselines only, not for final acceptance (D18) |
| Q10 | Runtime limit? | 60-second target, not enforced (D19) |
| Q11 | Which dataset is used for a final decision? | A reserved decision seed distinct from 42; it is not selected or run now (D18) |
| Q12 | What happens on a run ID collision? | Suffixes `-2` to `-99`, then fail without overwriting (D10) |
| Q13 | Which baseline versions? | Both `"1.0"` (D20) |
| O1 | How is the decision seed chosen? | Derived per decision as in section 5.4 (D22); no seed selected now |
| O3 | How is the runtime target confirmed? | Five measured runs after implementation, warning above 60 seconds, no hard limit (D23) |
| O4 | Where is the incident record? | `docs/incidents/holdout-integrity.md`, section 9.8 (D24) |
| O2 | How the formal-run clean-tree check is implemented with no subprocess in `src/` and no Ruff exception (D14). Proposed: pygit2, as an optional `formal` extra (section 9.5). Stays open until all four gates are approved and completed: (1) dependency approval; (2) confirmed compatibility with Python 3.13 on Windows AMD64 for an exact pinned version; (3) license review; (4) AC-FC-26 authorized, run and passed. Status on 2026-11-01 (O2 approval gates of section 13.3): gate 1, plan, approved; gate 2, implementation, accepted (D27, D28); gate 3, dependency approval, approved; gate 5, license review, internal-use acceptance recorded (D29); gate 4, installation, completed; gate 6, AC-FC-26, pending and not authorized. O2 stays open. | Closed 2026-11-01 by the user's explicit approval (D30): all six gates of section 13.3 complete; AC-FC-26 56 passed, 0 failed, 0 skipped; pygit2 1.20.1 with libgit2 1.9.7 verified at runtime. Formal evaluations are still not authorized (first commit and clean tree required). |

### 13.2 Still open
None. O2 was closed on 2026-11-01 by the user's explicit approval and moved to section 13.1 with its full text (D30).

### 13.3 O2 clean-tree controller (D27)
O2 approval gates, final status on 2026-11-01 (all complete; O2 closed, D30):

| Gate | Subject | Status |
|---|---|---|
| 1 | Plan | Approved 2026-11-01 (D27) |
| 2 | Implementation (files) | Accepted 2026-11-01 (D27, D28) |
| 3 | Dependency approval | Approved 2026-11-01: pygit2 1.20.1, cffi 2.1.1, pycparser 3.12 |
| 4 | Installation | Completed 2026-11-01 (see **Dependency** below) |
| 5 | License review | Internal-use acceptance recorded 2026-11-01 (D29) |
| 6 | AC-FC-26 run | Completed 2026-11-01: passed (56 passed, 0 failed, 0 skipped, 859 deselected) |

O2 is **closed** (D30, closure record below). The closure does **not** authorize formal
forecasting evaluations: no formal run is possible before the repository has a **first
commit** and the checker returns CLEAN on it, and every other section 9.5 condition still
applies.

**Dependency.** `pygit2==1.20.1` in the optional `formal` extra, **internal use only**,
never shipped to customers. `backend/requirements-formal.lock` pins cffi 2.1.1, pycparser
3.12 and pygit2 1.20.1 with the SHA-256 of their CPython 3.13 Windows AMD64 wheels; no
other platform is established. Installation procedure, after `requirements-dev.lock`:
`pip install --require-hashes --only-binary=:all: -r requirements-formal.lock` (no
`--no-deps`), then `pip check`. pygit2 is imported only inside the controller; the API,
the AI layer (mock by default) and exploratory runs never import it.

**Installation record (gate 4, 2026-11-01).** Run with that procedure from `backend/` in
the project virtual environment (Python 3.13). Installed: `pygit2==1.20.1`,
`cffi==2.1.1` and `pycparser==3.12`, each wheel checked against its locked SHA-256.
`pip check` returned `No broken requirements found`. A `pip freeze` comparison before and
after shows that only these three packages were added and that no other package version
changed. Both lockfiles stayed unchanged; their SHA-256 was verified before and after
(`requirements-formal.lock` `873ab6ac6f6249a8e5dbceb24cbd409b3c6294f16692cc951e4dc87e02ac9665`,
`requirements-dev.lock` `d3c103de45d1cab3e430c0c08aedec9ad761e45043c9d1c5afe6c02e6b7656a6`).
The installed packages carry their license files (D29 condition 4). pygit2 was not
imported during installation; the bundled libgit2 version was verified at runtime on
2026-11-01, before the gate 6 run (`pygit2.__version__` 1.20.1, `pygit2.LIBGIT2_VERSION`
1.9.7). The D29 conditions apply unchanged.

**Index reader** (`gitindex.py`, standard library only). Two read-only snapshots of
`.git/index` (stat, one read, stat again, SHA-256), at the start and at the end of the
check; any difference is a refusal and nothing is retried. The trailing SHA-1 checksum is
verified before the content is used; an all-zero checksum (`index.skipHash`) is refused.
Versions 2, 3 and 4 with SHA-1 names; Git writes version 3 only with extended entries,
which are refused. Refused: assume-unchanged, skip-worktree, intent-to-add and every other
extended or reserved bit; gitlinks; modes other than 100644, 100755 and 120000; unsorted
or duplicate entries; a path both merged (stage 0) and conflicted. Conflict stages 1 to 3
are accepted structurally and reported as conflicts. Extensions: only TREE and REUC,
validated strictly; TREE follows `cache-tree.c` (root first with an empty name, siblings
ordered by name length then bytes, canonical numbers, an object name only for valid
nodes, no arithmetic rule between counts); REUC follows `resolve-undo.c` (sorted paths,
three canonical octal modes, one object name per non-zero mode). Every other extension,
optional or required, is refused. TREE and REUC were accepted only after the reader tests
for them in `tests/test_forecasting_gitindex.py` passed on 2026-11-01 (parsing compared
with `git ls-tree` and `git ls-files --resolve-undo` on real repositories, plus crafted
indexes), as the approved plan required.

**Path policy** (index, TREE, REUC and status paths alike). Strict UTF-8 (a string from
pygit2 must re-encode strictly), NFC required and never normalized, no control character,
no backslash, no empty, `.`, `..` or `.git` component (case-insensitive), no leading or
trailing slash, absolute length at most 259 characters. Non-ASCII paths are refused until
the AC-FC-26 parity tests establish them. Diagnostics show only `ascii()` text (at most 200
characters) or hex bytes.

**Controller** (`cleantree.py`): `check_clean_tree(project_root)` returns CLEAN, DIRTY or
REFUSED. Phase A (foundational, stop at the first failure): forbidden `GIT_*` variables
(those Git honours and libgit2 ignores without `GIT_REPOSITORY_OPEN_FROM_ENV`); config files
only libgit2 reads (`%APPDATA%\git`, `%LOCALAPPDATA%\git`, `%PROGRAMDATA%\Git\config`);
ambiguous global or system config; `.git` must be a folder at the root, no `commondir`;
lock files (`*.lock` in `.git`, and at any depth in `refs`, `logs`, `objects/info` and
`objects/pack`); first index snapshot; pygit2 import; opening with `NO_SEARCH` and `workdir`
equal to the root; configuration (any `include.path` or `includeIf.*` at any level, found
both through the public config API and by a standard-library text scan; `extensions.*`;
keys that change index writing; the compatibility profile below); bare, unborn, shallow,
HEAD not on an existing commit (a detached HEAD on a valid commit is accepted), an
unfinished operation, submodules, linked worktrees, sparse checkout. Phase B: status with
untracked files, ignored files excluded; an unknown bit, an unexpected ignored or
unreadable entry, or a path breaking the policy stops with REFUSED; conflicts from the
reader, the pygit2 index and the status must agree. Phase C: HEAD, operation state,
config files (every file libgit2 may read, so a file created during the check is also a
change), lock files and the second index snapshot must be unchanged. Git booleans are
read in any letter case (`true`, `yes`, `on`, `1` and `false`, `no`, `off`, `0`, empty);
any other value of a boolean key is refused, and `core.untrackedcache` and
`core.fsmonitor` are allowed only when they read as false. CLEAN only when
every phase passed with no change and no conflict; DIRTY when the checks passed and there
are changes or conflicts (a conflict during an unfinished operation is REFUSED); REFUSED
otherwise. Expected errors (OSError, ValueError and similar, pygit2.GitError) give
REFUSED; a programming error propagates and a caller treats any exception as not clean.

**Compatibility profile `o2-windows-v1`** (Windows only): `core.autocrlf` true or false,
`core.eol` unset, `core.ignorecase` true, `core.filemode` false, `core.symlinks` false and
no symlink entry, `core.longpaths` unset or false, `core.fscache` allowed, no custom
`core.excludesFile` or `core.attributesFile`, the project's own `.gitattributes` and
`.gitignore` (including `!.env.example` and `!backend/src/dealpilot/data/`). Anything else
is REFUSED as untested. A divergence found by AC-FC-26 fails AC-FC-26; it is resolved only
by fixing the code or narrowing the profile, each with the user's approval, never by
choosing one tool's result. Rename detection: pygit2's public `status()` has no rename
option, so a rename is compared as its two paths, not as a rename record.

**Type changes (AC-FC-26, D28).** In this profile a tracked entry can change type only when it
is a symlink (mode 120000) or a gitlink (160000) entry. Both are refused in phase A (K4 and
the index reader), before pygit2 is loaded, so a type change can never give CLEAN. By the
user's decision of 2026-11-01, this explicit refusal satisfies the type-changed case of
AC-FC-26; no cross-platform symlink support is added. A file replaced by a folder is not
a type change for Git (a deletion and an untracked file) and is compared like any change.

**Concurrency.** The controller locks nothing. It detects changes to the index, HEAD, the
operation state, the configuration and lock files between its first and last checks. It
can't detect a working-tree change made after `status()` read a file, nor an index
changed and restored exactly. Proposal for the future harness: check before and after
each formal run.

**Provenance.** `git_provenance` (section 9.3) also records `outcome`, `head_detached`,
`changed_paths`, `conflict_paths`, `reasons`, `index_version`, `index_sha256`,
`index_extensions`, `effective_config` (`autocrlf`, `eol`, `safecrlf`, `ignorecase`,
`filemode`, `symlinks`, `longpaths`, `fscache`, `excludesFile`, `attributesFile`),
`config_levels_present` (booleans, no paths) and `compatibility_profile`; `clean_tree`
is true only for CLEAN.

**Tests.** `tests/test_forecasting_gitindex.py` (default suite) checks the reader against
`git ls-files -s`, `-v` and `--resolve-undo`, `git ls-tree` and crafted indexes.
`tests/test_forecasting_cleantree.py` holds the default-suite checks (phase A refusals
before pygit2 is imported, including the type-change refusal, and configuration value
parsing; tests that reach the root check run on Windows only and are skipped elsewhere
with a reason) and, under the `formal_checker` marker, AC-FC-26. Parity with `git status
--porcelain=v1 --untracked-files=all -z` (renames as two paths) is compared for: modified
and deleted files; renames staged and made on disk; staged changes and new files;
untracked files; ignored files with the negations `!.env.example` and
`!backend/src/dealpilot/data/`; case-only renames through `git mv` and on disk; a file
replaced by a folder; `eol=lf` with `core.autocrlf` true and false; and a conflict with no
operation. The other AC-FC-26 cases check a stated outcome instead of parity: detached
HEAD gives CLEAN; REFUSED for unfinished operations, includes (local, global, XDG and
system levels), untested profile values, symlink and gitlink entries and type changes,
sparse checkout, worktrees, submodules, no repository, bare, unborn, shallow, sha256 and
reftable repositories, non-ASCII and long untracked paths, and concurrent changes (locks,
HEAD, operation state, index, configuration changed or created); never CLEAN for an
unreadable file. The index SHA-256 is measured just before and just after the controller,
with no `git` command between. All repositories are temporary, outside the project, with
an isolated Git environment. AC-FC-26 ran once, on 2026-11-01 (gate 6), and passed (closure
record below).

**AC-FC-26 guard.** A command-line `-m` replaces the marker filter of `addopts` in
`pyproject.toml`, so `pytest -m "not slow"` alone would select AC-FC-26. To prevent that,
`tests/conftest.py` removes every `formal_checker` test from any run, and says so in the
summary, unless the variable `DEALPILOT_RUN_AC_FC_26` equals exactly `o2-gate-6-approved`;
the `pygit2_isolated` fixture checks the same value again before importing pygit2. The
command of the authorized gate 6 run, from `backend/` in PowerShell:
`$env:DEALPILOT_RUN_AC_FC_26 = "o2-gate-6-approved"; .\.venv\Scripts\python.exe -m pytest -m formal_checker`,
then `Remove-Item Env:DEALPILOT_RUN_AC_FC_26`. The variable is set only for an authorized
run and removed right after it; it is never set anywhere else.

**Closure record (2026-11-01, D30).** O2 was officially closed on 2026-11-01 by the
user's explicit approval, on the evidence of the gate 6 execution report:
- Runtime check before the run: `pygit2==1.20.1`, bundled `libgit2==1.9.7`.
- Collection with the authorization variable: 56 of 915 tests selected, 859 deselected.
- AC-FC-26: **56 passed, 0 failed, 0 skipped, 859 deselected** (about 97 seconds); the
  variable was removed afterwards. Installation and `pip check` had succeeded (gate 4).
- After the run, the project repository was checked: index unchanged, no file staged,
  no commit, no remote; `data/raw` and both lockfiles unchanged.
- **Git observation.** 262 loose objects were found in the project's `.git/objects`. They
  were inspected read-only (`git cat-file`): the objects checked are blobs whose contents
  match current project files. No index, refs, configuration or commit was changed. Their
  creation is attributed to a process outside the tests (they appear in batches since
  2026-10-28, right after file edits; every AC-FC-26 repository is temporary and outside
  the project). These objects must not be deleted, pruned, repacked or otherwise
  modified.
- The D29 license conditions remain applicable.
- The closure does **not** authorize any formal forecasting evaluation. The first Git
  commit and a verified clean working tree remain prerequisites, together with every
  other section 9.5 condition and a separate authorization.

## 14. Risks
- **Holiday constant drift.** If spec 001 section 5.7 changes, the constant in the
  forecasting module becomes wrong. AC-FC-17 compares them.
- **Unprotected log before the first commit.** A full rewrite of `evals/holdout-log.csv`
  together with its local head record
  cannot be detected until the file is committed (section 9.4).
- **Strict gate.** Four conditions at three levels, with heavy noise at the
  `product_region` level, may mean no simple model can pass.
- **Correlated folds.** Neighboring folds are not independent, so 10 of 13 won folds is
  weaker evidence than it looks.
- **Mid-window launches.** A product launching inside a window gets the same forced 0
  from the evaluator for both models before it becomes visible, which pulls `RelMAE`
  toward 1 for those series.
- **No formal runs yet.** The repository has no commits, so only exploratory runs are
  possible until the user makes the first commit.
- **Data changes.** A generator change (spec 001) makes earlier results not comparable.
  File hashes in `run.json` make this visible.
- **API conflict.** Serving `/v1/forecasts` breaks AC-API-17 unless spec 002 is updated
  first (D11).
- **Dependency license.** The license of pygit2 1.20.1, its bundled libgit2 1.9.7, cffi
  2.1.1 and pycparser 3.12 is accepted for internal use only (D29, O2 gate 5). The risk
  remains if the use changes: any redistribution to customers, modification of these
  libraries or change of use needs a new license review first.
- **Git and libgit2 disagreement.** pygit2 may judge line endings (`core.autocrlf` versus
  `.gitattributes`), ignore rules or case-only renames differently from the `git` command.
  AC-FC-26 must show they agree before formal runs rely on it. It passed on 2026-11-01
  for the `o2-windows-v1` profile with pygit2 1.20.1 and libgit2 1.9.7 (D30); other
  versions, profiles or platforms are not covered by that run.
- **Repository-owner check.** libgit2 checks that the repository belongs to the current
  user; on some drives this can fail and block formal runs (fail closed).
- **Missing commit.** Formal runs and decision seeds (section 5.4) need a commit, and the
  repository has none yet.

## 15. Alignment with `docs/evaluation.md`
`docs/evaluation.md` was aligned with this spec on 2026-10-28 in a separate, explicitly
authorized task (D21). Where it summarizes this spec, this spec is authoritative. The
table records the former inconsistencies and where each is now addressed.

| `docs/evaluation.md` | Said before | This spec | State |
|---|---|---|---|
| Section 1 | Holdout is the last 90 days, used once | Four sequential origins with refitting and no tuning; consumed holdout and new seed rules (sections 5.1, 5.3) | Resolved 2026-10-28 |
| Section 1 | At least 6 cutoffs | 13 cutoffs (section 5.1) | Resolved 2026-10-28 |
| Section 2 | Seasonal naive is lag 7 repeated forward | Weekly fallback for closed source days (section 6.1) | Resolved 2026-10-28 |
| Section 2 | Beat seasonal naive on WAPE and MASE across folds, not worse on holdout | Gate on WAPE and RelMAE with 5%, 10 of 13 and all three levels (section 8) | Resolved 2026-10-28 |
| Section 3 | MASE below 1.0 means better than the baseline | MASE is report only; comparison uses RelMAE (sections 7.2, 7.3) | Resolved 2026-10-28 |
| Section 3 | Metrics per fold, per level, average | Also per day scope; open days drive the gate (section 7) | Resolved 2026-10-28 |
| Section 4 | Holidays may be future inputs | The fixed calendar is a declared input of seasonal naive; model-visible inputs listed (sections 4.3, 6.3) | Resolved 2026-10-28 |
| Section 4 | If the holdout is looked at, a new one must be chosen | New dataset with a new recorded seed and a full backtest (section 5.3, D18) | Resolved 2026-10-28 |
| Section 5 | Every run records the git commit | Exploratory runs use a source manifest; formal runs need a commit; holdout log (section 9) | Resolved 2026-10-28 |
| Section 5 | Same data and settings give the same numbers | Byte-identical only on the same machine with the same dependency versions (section 9.6) | Resolved 2026-10-28 |
| Section 5 | No decision seed, clean-tree rule or formal-run authorization | Decision seed (section 5.4, D22); clean tree as one prerequisite, never sufficient alone (section 9.5, D14, O2) | Resolved 2026-10-28 |
| Section 5 | Only `evals/results/` and `docs/` named | Holdout log, hash chain, head record and lock (section 9.4); runtime warning (section 9.7, D23); incident record (section 9.8, D24) | Resolved 2026-10-28 |
