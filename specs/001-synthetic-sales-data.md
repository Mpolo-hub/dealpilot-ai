# Spec 001: Synthetic Sales Data

Status: Approved v3 (2026-10-27). P2 is approved subject to empirical validation (section 9).
Owner: DealPilot AI team

## 1. Goal
Generate realistic, fully synthetic daily sales data that the analytics and forecasting
modules can be built and tested against. The data must contain known, measurable patterns
(trend, weekly and yearly seasonality, promotions, noise) so we can check that our models
find them. Alongside the noisy sales, the generator writes the **true expected demand**,
so evals can measure how close a forecast gets to the real signal.

## 2. Non-goals
- No real customer data, names, emails, or addresses. All values are made up.
- No dirty data (duplicates, missing values, bad formats) in this version. Dirty-data
  injection is a later spec.
- No returns, refunds, inventory, or stockouts.
- No multiple currencies. Everything is in USD.
- No `--scale` option (decided 2026-10-27).

## 3. Interface
One command, one seed, one output folder:

```
python -m dealpilot.data.generate --seed 42 --start 2023-01-01 --end 2025-12-31 --out data/raw
```

| Option | Default | Rule |
|---|---|---|
| `--seed` | `42` | Any integer from 0 upward. A negative seed is refused with an error and nothing is written (decision 2026-10-30). All randomness comes from this one seed. |
| `--start` | `2023-01-01` | The range, counting both end dates, must be 730 to 1096 days. |
| `--end` | `2025-12-31` | Must be after `--start`. |
| `--out` | `data/raw` | Created if missing. Existing files are overwritten. |

Output files:
- `regions.parquet`, `products.parquet`, `customers.parquet`, `promotions.parquet`,
  `orders.parquet`, `order_lines.parquet` (section 4)
- `expected_demand.parquet` (section 6)
- `metadata.json`: seed, date range, row counts, generator version, and every parameter
  in section 5

Target runtime: under 60 seconds on a normal laptop with default settings.

### 3.1 metadata.json fields
`metadata.json` is one JSON object with the fields below. Extra fields are allowed.

| Field | Type | Value |
|---|---|---|
| `seed` | integer | The `--seed` used |
| `start`, `end` | string, `YYYY-MM-DD` | The `--start` and `--end` used |
| `generator_version` | string, not empty | Version of the generator that wrote the files |
| `row_counts` | object | One entry per output table (`regions`, `products`, `customers`, `promotions`, `orders`, `order_lines`, `expected_demand`) giving its row count |
| `parameters` | object | The section 5 parameters listed below |

**Fixed parameters** in `parameters`. Each must equal the value shown, copied from
section 5. They add no new behavior.

| Field | Value | Source |
|---|---|---|
| `base_total_units` | `250` | 5.2 |
| `base_category_share` | `0.20` | 5.2 |
| `base_lognormal_sigma` | `0.5` | 5.2 |
| `base_max_share` | `0.06` | 5.2 |
| `trend_rates` | `{"Electronics": 0.15, "Home": 0.08, "Office": 0.06, "Outdoor": 0.10, "Apparel": 0.00}` | 5.3 |
| `trend_days_per_year` | `365.25` | 5.3 |
| `weekly_multipliers` | `[0.85, 0.90, 0.95, 1.00, 1.10, 1.25, 0.95]` (Mon to Sun) | 5.4 |
| `yearly_anchor_day` | `15` | 5.5 |
| `yearly_anchors` | `{"standard": [0.90, 0.80, 0.88, 0.95, 1.00, 0.98, 0.95, 1.00, 0.98, 1.03, 1.13, 1.20], "outdoor": [0.80, 0.85, 0.95, 1.05, 1.15, 1.25, 1.25, 1.15, 1.05, 0.95, 0.85, 0.80]}` (Jan to Dec) | 5.5 |
| `yearly_curve_by_category` | `{"Electronics": "standard", "Home": "standard", "Office": "standard", "Outdoor": "outdoor", "Apparel": "standard"}` | 5.5 |
| `promo_lift_base` | `1.15` | 5.6 |
| `promo_lift_per_discount` | `1.5` | 5.6 |
| `promo_dip_factor` | `0.90` | 5.6 |
| `promo_pre_window_days` | `14` | 5.6 |
| `promo_post_window_days` | `7` | 5.6 |
| `promo_max_concurrent` | `3` | 5.6 rule 4 |
| `promo_min_pre_window_units` | `14` | 5.6 rule 5 |
| `closed_days` | `["12-25", "01-01"]` (MM-DD) | 5.7 |
| `noise_nb_size` | `2` | 5.1, size k |
| `price_increase_min` | `0.02` | 5.8 |
| `price_increase_max` | `0.04` | 5.8 |

**Drawn values** in `parameters`. These come from the seed, so they are checked by
structure and by the section 5 rules they must meet, not against fixed numbers.

| Field | Structure | Valid values |
|---|---|---|
| `base_demand` | Object with exactly the 50 `product_id`s as keys, each mapped to its `base(p)` as a number | Every value is above 0 (lognormal draws). Section 5.2 holds: over the 45 products active on `--start`, `sum(base(p) * size_weight(r))` across all regions is 250; each category's share of that is 20%; no product's sum across regions is more than 6% of 250. |

Section 5.10's method is not binding, so it has no field here.

AC-16 checks every field in this section. AC-17(c) takes fixed values from section 5
(and region weights from section 4), never from this file. From this file it uses only
`base_demand`.

## 4. Tables

### regions (5 rows, fixed)
| region_id | name | size_weight |
|---|---|---|
| R01 | North | 0.28 |
| R02 | South | 0.22 |
| R03 | East | 0.20 |
| R04 | West | 0.16 |
| R05 | Central | 0.14 |

### products (exactly 50 rows)
| Column | Type | Notes |
|---|---|---|
| product_id | string, PK | `P001` to `P050` |
| name | string | Made-up names |
| category | string | Electronics, Home, Office, Outdoor, Apparel. Exactly 10 products each. |
| list_price | decimal(10,2) | Price at `--start`. Between 5.00 and 1500.00 |
| launch_date | date | `--start` for 45 products. Exactly 5 launch later, between `--start` + 90 days and `--end` - 180 days. |
| discontinue_date | date, nullable | Exactly 3 products (not among the 5 late launches). Between `--start` + 180 days and `--end` - 90 days. First day the product is no longer sold. |

Lifecycle products (the 5 late launches plus the 3 discontinued ones) are spread across
categories: at most 2 per category.

A product is **active** on day d when `launch_date <= d` and either there is no
`discontinue_date` or `d < discontinue_date`.

**Continuing products** are the products where `launch_date = --start` and
`discontinue_date` is null. By the counts above there are exactly 50 - 5 - 3 = **42**, and
every category has at least 8. AC-06, AC-08 and AC-12(b) measure on this set.

### customers (exactly 2,000 rows)
| Column | Type | Notes |
|---|---|---|
| customer_id | string, PK | `C00001` to `C02000` |
| region_id | string, FK -> regions | Split by `size_weight` |
| segment | string | Consumer (about 70%), SMB (about 25%), Enterprise (about 5%) |
| signup_date | date | 60% before `--start` (up to 3 years before). 40% spread across the range. |

The 60% who sign up before `--start` mean every region has active customers on day one.

### promotions (exactly 40 rows)
| Column | Type | Notes |
|---|---|---|
| promo_id | string, PK | `PR001` to `PR040` |
| product_id | string, FK -> products | One product per promo |
| region_id | string, FK -> regions, nullable | Null means all regions. About half are all-region. |
| start_date, end_date | date | 3 to 14 days long, both days included |
| discount_pct | decimal(4,2) | One of 0.10, 0.15, 0.20, 0.25, 0.30 |

Placement rules are in section 5.6.

### orders (header, one row per order)
| Column | Type | Notes |
|---|---|---|
| order_id | string, PK | `O0000001` onward, in date order |
| order_date | date | |
| customer_id | string, FK -> customers | A customer whose `signup_date <= order_date` |
| region_id | string, FK -> regions | Always the customer's region |
| channel | string | Online (about 60%), Store (about 40%) |

### order_lines (one row per product in an order)
| Column | Type | Notes |
|---|---|---|
| order_id | string, FK -> orders | |
| line_no | int | 1 to 5. PK is (order_id, line_no). |
| product_id | string, FK -> products | Unique within an order |
| quantity | int | 1 or more |
| unit_price | decimal(10,2) | That year's list price (section 5.8), before discount |
| discount_pct | decimal(4,2) | Promo discount if a promo is active for that product, region and day, else 0.00. Plus 0.05 if the customer is Enterprise. Max 0.35. |
| line_total | decimal(12,2) | `quantity * unit_price * (1 - discount_pct)`, computed in decimal and rounded half-up to cents |
| promo_id | string, FK -> promotions, nullable | Set when a promo is active for that product, region and day |

## 5. Demand model (binding)
All parameters below are written to `metadata.json`.

### 5.1 Formula
For product p, region r and day d:

```
expected(p, r, d) = open(d) * active(p, d) * base(p) * size_weight(r)
                    * trend(p, d) * weekly(d) * yearly(p, d) * promo(p, r, d)

observed units(p, r, d) ~ NegativeBinomial(mean = expected(p, r, d), size k = 2)
```

`open` and `active` are 1 or 0. When `expected` is 0, observed units are 0. With size
k = 2 the variance is `expected + expected^2 / 2`, which is always above the mean.

### 5.2 Base demand
- The 45 products active on `--start` add up to **250 units per day**:
  `sum(base(p) * size_weight(r))` over those products and all regions equals 250.
- Each category's products active on `--start` share 20% of that total. Within a
  category, shares are drawn from a lognormal (sigma 0.5).
- A late-launch product draws its base from the same lognormal as the rest of its
  category, on top of the 250.
- No product's base is more than 6% of the 250.

### 5.3 Trend
`trend(p, d) = (1 + g[category(p)]) ^ (days since --start / 365.25)`

| Electronics | Home | Office | Outdoor | Apparel |
|---|---|---|---|---|
| 0.15 | 0.08 | 0.06 | 0.10 | 0.00 |

Average of the five rates: 7.8% per year.

### 5.4 Weekly seasonality
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|
| 0.85 | 0.90 | 0.95 | 1.00 | 1.10 | 1.25 | 0.95 |

The seven values average exactly 1.00.

### 5.5 Yearly seasonality
Each month has an **anchor value on its 15th day**. For any other day, take a straight
line between the two nearest anchors, counting real calendar days. Dec 15 connects to
Jan 15 of the next year, so the curve has no jumps. Leap years work the same way.

| Curve | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Standard (Electronics, Home, Office, Apparel) | 0.90 | 0.80 | 0.88 | 0.95 | 1.00 | 0.98 | 0.95 | 1.00 | 0.98 | 1.03 | 1.13 | 1.20 |
| Outdoor | 0.80 | 0.85 | 0.95 | 1.05 | 1.15 | 1.25 | 1.25 | 1.15 | 1.05 | 0.95 | 0.85 | 0.80 |

Example: Dec 1 is 16 of the 30 days from Nov 15 to Dec 15, so
`yearly = 1.13 + (1.20 - 1.13) * 16 / 30 = 1.1673`.

The standard curve peaks on Dec 15 at 1.20 and bottoms out on Feb 15 at 0.80. A single
sine wave can't do that, because its high and low points are always 6 months apart.
That's why this curve uses anchors.

### 5.6 Promotions
`promo(p, r, d)`:
- `lift = 1.15 + 1.5 * discount_pct` while the promo is active. This gives 1.30 at 10%
  off and 1.60 at 30% off (a 30% to 60% lift).
- `dip = 0.90` for the 7 days after the promo ends, because buyers bought early. This
  10% dip is the intended market behavior.
- `1.00` otherwise.

Each promo has a **window**: 14 days before it (the pre-window), the promo days, and 7
days after (the post-window). Placement rules:
1. The whole window is inside the date range and inside the product's active period.
2. A window has no closed days (section 5.7).
3. Windows for the same product and region never overlap. An all-region promo counts
   for every region. Because of this, a product-region-day has at most one promo factor.
4. At most 3 promos are active on any day.
5. In every region the promo covers, expected units in the pre-window are at least 14
   (about 1 per day). Small products are too noisy to measure a lift on.

If the generator can't place all 40 promos under these rules, it fails with an error.
It never quietly makes fewer.

### 5.7 Closed days
`open(d) = 0` on December 25 and January 1, and `1` on every other day.

### 5.8 Prices
On each January 1 after the first year, each product's price goes up by a random 2% to 4%:
`new price = round_half_up(old price * (1 + rate), 2)`.
Prices don't change demand in this version.

### 5.9 How the parts interact
| Situation | expected | observed | Orders | Notes |
|---|---|---|---|---|
| Closed day | 0 | 0 | none | Applies to every product and region |
| Product not active yet, or discontinued | 0 | 0 | no lines for it | |
| Promo day | x lift | NB around expected | lines carry `promo_id` and the discount | Only on open days, inside the active period |
| 7 days after promo | x dip (0.90) | NB around expected | no promo discount | |
| Enterprise customer | no effect | no effect | extra 0.05 discount | Discounts happen after demand, so they don't change units |

### 5.10 From units to orders (method not binding)
For each region and day, the observed units of each product are split into lines. Each
line's quantity is `min(units left, 1 + Poisson(0.5))`, so the average quantity is 1.5
or less. Lines are then grouped into orders of 1 to 5 lines with different products. Each
order goes to a random customer in that region who has already signed up.
**Binding:** the sum of `quantity` for a product, region and day must equal that day's
observed units.

## 6. True expected demand

### 6.1 What it is
`expected(p, r, d)` from section 5.1. It is the average number of units sales would
show if the same day could be replayed many times. It includes every effect (trend,
seasonality, promos, the dip, closed days, product lifecycle) but no noise.

### 6.2 How it's stored
`expected_demand.parquet`, one row for every product, region and date in the range,
zeros included (50 x 5 x 1,096 = 274,000 rows by default):

| Column | Type | Notes |
|---|---|---|
| date | date | |
| product_id | string, FK -> products | |
| region_id | string, FK -> regions | |
| expected_units | float64 | 0 or more. Not rounded. |

PK is (date, product_id, region_id). It is kept separate from the sales tables. Nothing
in `orders` or `order_lines` is derived from this file after the noise draw.

### 6.3 How it's used
There are two separate uses, and they are reported separately.

**A. Generator tests.** AC-12 and AC-17 use it as the true mean. If P2 is approved,
AC-09 and AC-10 also use it.

**B. Signal-recovery evaluation (synthetic data only).** On a forecast test window:
- **Signal WAPE** = `sum(abs(forecast - expected)) / sum(expected)`. This shows how
  close a model gets to the real signal.
- **Noise floor** = `sum(abs(expected - observed)) / sum(observed)`, which is the
  observed-sales WAPE of a perfect forecast. It shows how much room is left.

Rules:
- **Separate reporting.** Signal recovery goes in its own table, labeled "Signal recovery
  (synthetic only)". It is never mixed with, averaged into, or traded off against the
  observed-sales metrics in `docs/evaluation.md`.
- **Shipping uses observed sales only.** The ship rule (beat seasonal naive on observed
  sales) doesn't change. Signal recovery is for diagnosis.
- **Never a model input.** Training, features, tuning and model selection must not read
  this file. Only evaluation code reads it, and only for test windows. This is the same
  as the leakage rule for `metadata.json`.

## 7. Data quality rules (binding)
- **DQ-01** Every primary key is unique and not null.
- **DQ-02** Every foreign key points to an existing row.
- **DQ-03** No nulls except the columns marked nullable.
- **DQ-04** `quantity` is an integer of 1 or more. `unit_price` and `line_total` are above 0.
- **DQ-05** `discount_pct` is between 0.00 and 0.35.
- **DQ-06** `line_total` equals the formula in section 4 to the cent.
- **DQ-07** Every `order_date` is within `--start` and `--end`.
- **DQ-08** No order before the customer's `signup_date`.
- **DQ-09** No line for a product before its `launch_date` or on or after its `discontinue_date`.
- **DQ-10** `promo_id` is set exactly when a promo for that product covers that region
  and `order_date`. `discount_pct` equals that promo's discount (or 0.00 if there is no
  promo), plus 0.05 for Enterprise customers.
- **DQ-11** `orders.region_id` matches the customer's region.
- **DQ-12** Every order has at least one line.
- **DQ-13** Money values have at most 2 decimals.

## 8. Acceptance criteria
All checks use the default settings (`--seed 42`, 2023-01-01 to 2025-12-31) unless the
criterion says otherwise. Section 8.1 defines the terms. Appendix A shows why each range
can be met.

| ID | Criterion | How to test |
|---|---|---|
| AC-01 | All 7 Parquet files and `metadata.json` are written to `--out`. | Files exist and load with DuckDB. |
| AC-02 | Every DQ rule in section 7 passes. | One SQL or pandas check per rule. Zero failing rows. |
| AC-03 | Same seed gives identical data. | Run twice with seed 42. All 7 tables are equal, row by row. |
| AC-04 | A different seed gives different data. | Seed 42 vs seed 7: `order_lines` differ. |
| AC-05 | Row counts are in range. | 5 regions, 50 products, 1,800-2,200 customers, 30-50 promotions, 150k-400k order lines. |
| AC-06 | Trend is up. | Continuing products, all regions: total units over calendar year 2025 divided by total over calendar year 2023 is between 1.10 and 1.25 (8% for 2 years is about 1.17). |
| AC-07 | Weekly pattern is visible. | Average daily units by weekday (closed days removed): Saturday is highest, Monday is lowest, Sat/Mon is between 1.30 and 1.65. |
| AC-08 | Yearly pattern is visible. | Continuing products, all regions, for each calendar year 2023, 2024 and 2025. Standard categories: average daily units over Dec 1-31 (closed days removed) divided by Feb 1 to the last day of February is between 1.30 and 1.75. Outdoor: average daily units over Jun 1 to Jul 31 divided by the average over Jan 1-31 plus Dec 1-31 of the same year (closed days removed) is above 1.20. |
| AC-09 | Promotions lift sales. | Seed 42. `L = sum(y) / sum(cf)` over every promo day of every pair in `C`. Sums are taken over all rows first, then divided once. Pass if 1.20 <= L <= 1.70. |
| AC-10 | Post-promo dip exists. | Seeds 1 to 10 (default range). `D = sum(y) / sum(cf)` over every post-window day of every pair in `C`, with sums taken across all 10 seeds before dividing. Pass if 0.85 <= D <= 0.95. Per-seed `D` is reported but doesn't gate. Marked as a slow test. |
| AC-11 | Closed days are closed. | Zero orders on every Dec 25 and Jan 1. |
| AC-12 | Noise is real but not too big. | (a) Overdispersion statistic `OD` (section 8.2) is above 1.2. (b) Residual coefficient of variation `CV_res` (section 8.2) is between 0.02 and 0.25. |
| AC-13 | Product lifecycle works. | At least 4 of the late-launch products (section 4) have their first sale at least 90 days after `--start`. At least 2 of the discontinued products (section 4) have their last sale at least 90 days before `--end`. Only those products are counted, so days with no sales by chance can't make the check pass. Both limits follow from section 4: late launches start from `--start` + 90 days, and discontinued products stop by `--end` - 90 days. |
| AC-14 | Range limits are enforced. | A range under 730 days or over 1096 days fails with a clear error and writes nothing. |
| AC-15 | Runs fast enough. | Default run finishes in under 60 seconds. |
| AC-16 | Patterns in metadata. | `metadata.json` holds the seed, date range, row counts and every parameter from section 5. |
| AC-17 | Expected demand is correct. | (a) One row per product, region and date, with no nulls and no negatives. (b) Exactly 0 on closed days and outside the active period, above 0 everywhere else. (c) Recomputing it from section 5.1 using the output tables and `metadata.json` matches within a relative error of 1e-9. (d) Total observed units divided by total expected units is between 0.98 and 1.02. |

AC-12 thresholds are provisional. They stay as they are until the first real generator
run. Any change after that needs a spec update and approval.

### 8.1 Test definitions
These pin down terms the table uses. They don't change any threshold.
- **Daily units**: total `quantity` across the products and regions in scope for one date.
- **Year, month**: calendar year and calendar month.
- **Closed days removed**: Dec 25 and Jan 1 are left out of averages and counts.
- **Average daily units over a period**: total units over the open days in the period,
  divided by the number of open days in it.
- **Continuing products**: defined in section 4 (exactly 42).
- **C** (AC-09 and AC-10): the set of (promo, region) pairs — one entry per promo for
  each region it covers, so an all-region promo contributes 5 pairs. With 40 promos and
  roughly half all-region, `|C|` is approximately 120. This is a count of pairs, not a
  count of independently gated comparisons. AC-09 and AC-10 each produce **one pooled
  ratio** (L and D respectively), not a median of per-pair ratios.
- **cf(p, r, d)** — counterfactual expected demand: `expected_units` from
  `expected_demand.parquet` with that row's promo factor neutralised to 1.00.
  - On promo days: `cf = expected / lift`  (lift defined in section 5.6).
  - On post-window days: `cf = expected / 0.90`  (the 10% dip factor).
  - Section 5.6 rule 3 guarantees at most one promo factor per row, so `cf` is always
    well defined.
  - `cf` is derived from `expected_demand.parquet`, `promotions.parquet` and
    `metadata.json`. AC-17(c) validates those inputs independently.
- **AC-10 slow-test group — multi-seed execution**: the slow pytest test invokes the
  generator **separately** for each of seeds 1 through 10 (using the existing single-value
  `--seed` CLI option, not a new option). It accumulates `sum(y)` and `sum(cf)` across
  all ten runs and divides once to obtain the single pooled D ratio. Per-seed D values
  are computed and logged as diagnostics but do not individually gate acceptance.
  The 10% post-promo dip target (section 5.6) and the threshold 0.85 <= D <= 0.95 are
  unchanged.

### 8.2 AC-12 statistics
Let `y(p, r, d)` be observed units and `mu(p, r, d)` be `expected_units`.

**(a) Overdispersion statistic**
- Rows: `S = { (p, r, d) in the range : mu(p, r, d) > 0 }`, all 50 products.
- Rows where `mu = 0` (closed days and inactive products) are left out. AC-17(b) already
  checks that `y = 0` on them, and they would add nothing to either sum.
- `OD = sum over S of (y - mu)^2 / sum over S of mu`.
- If `S` is empty the test fails. That can't happen with default settings.
- Reference point: Poisson noise gives `OD` around 1.0. Noise with size k gives
  `1 + sum(mu^2) / (k * sum(mu))`.

**(b) Residual coefficient of variation**
1. Scope: continuing products, all regions, open days only. Lifecycle products are left
   out because a mid-month launch would add a step that isn't noise.
2. `Y(d)` = daily units in that scope. On open days its expected value is always above 0.
3. `M(m)` = average of `Y(d)` over the open days of calendar month m (year and month).
4. `W(w)` = average of `Y(d) / M(m(d))` over all open days with weekday w.
5. `e(d) = Y(d) / (M(m(d)) * W(w(d)))` for each open day.
6. `CV_res = sd(e) / mean(e)`, where sd uses n - 1, over all open days in the range.

If any `M(m)` is 0, the test fails. That can't happen with default settings.

## 9. Decisions
| Date | Decision |
|---|---|
| 2026-10-27 | Keep `docs/evaluation.md`. |
| 2026-10-27 | No `--scale` option yet. |
| 2026-10-27 | Write true expected demand per product, region and day, separate from observed sales (section 6). |
| 2026-10-27 | **P1 approved:** AC-06 and AC-08 measure on the 42 continuing products, with the windows spelled out. |
| 2026-10-27 | **P3 approved in principle:** AC-12 uses the statistics in section 8.2. Thresholds stay as they are until a real generator run. |
| 2026-10-27 | Post-promo dip stays at 10%. Signal recovery is reported separately from observed-sales performance. Expected demand is never a model input. |
| 2026-10-27 | **P2 approved** (subject to empirical validation): AC-09 and AC-10 adopt the pooled counterfactual method (section 10). AC-09 uses seed 42 with a volume-weighted ratio L; AC-10 uses seeds 1–10 with a pooled ratio D. The 10% post-promo dip target is unchanged. AC-10 thresholds tighten from "below 1.00" to 0.85–0.95 (stricter, not weaker). Thresholds must not be silently weakened without a spec update and explicit approval. **Empirical-validation rules:** (a) Tests may be written before the generator is implemented. (b) Validate AC-09 and AC-10 thresholds on the first real generator run. (c) If a threshold fails, report the failure and investigate; do not silently adjust. (d) The generator is not considered compliant until all mandatory acceptance criteria pass. |
| 2026-10-27 | **metadata.json schema approved** (section 3.1): field names, fixed values copied from section 5, and `base_demand` checked by structure and the section 5.2 rules. No new behavior. AC-17(c) recomputes from spec constants and reads only `base_demand` from metadata. |
| 2026-10-27 | **AC-13 wording approved:** count only late-launch and discontinued products, with the 90-day limits taken from section 4. Thresholds (4 and 2) unchanged. |
| 2026-10-30 | **Seed range decided by the user:** `--seed` accepts 0 and positive integers only. A negative seed (numpy's generator cannot use one) is refused with a clear error and nothing is written; booleans and non-integers are refused too. Output for every accepted seed is unchanged. Earlier text said "Any integer" (section 3). |

## 10. Approved change: P2 — pooled counterfactual tests for AC-09 and AC-10

### P2 (revised): approved 2026-10-27, subject to empirical validation
Applied. AC-09 and AC-10 in section 8 now use the wording below. The definitions
of `C` and `cf` in section 8.1 are normative. The rationale and power analysis below
are retained for reference.

**Why the current AC-10 can't work.** In one dataset the dip affects about 840
product-region-days (120 comparisons x 7 days), with about 1,100 expected units. The
noise on the pooled log ratio is at least 0.040 (Appendix A.4). A 10% dip is a log
change of 0.105, so a single dataset holds only about 2.6 SE of signal. No test on one
seed can both pass reliably when the dip is there and fail reliably when it's missing.
This is a limit of how much data there is, not of how the test is written.

**Applied wording (reference copy).** The text below is the wording now in effect in
section 8. It is kept here alongside the rationale for traceability. The normative
definitions of `C` and `cf` are in section 8.1.

Definitions:
- `C` is the set of (promo, region) pairs from section 8.1.
- `cf(p, r, d)` is the **counterfactual expected demand**: `expected` with that row's
  promo factor set to 1.00.
  - On promo days: `cf = expected / lift`.
  - On post-window days: `cf = expected / 0.90`.
- Section 5.6 rule 3 means each row has at most one promo factor, so `cf` is always
  well defined.
- `cf` is computed from `expected_demand.parquet`, `promotions.parquet` and
  `metadata.json`. AC-17(c) checks those inputs on their own.

| ID | Criterion | How to test |
|---|---|---|
| AC-09 | Promotions lift sales. | Seed 42. `L = sum(y) / sum(cf)` over every promo day of every pair in `C`. Sums are taken over all rows first, then divided once. Pass if 1.20 <= L <= 1.70. |
| AC-10 | Post-promo dip exists. | Seeds 1 to 10 (default range). `D = sum(y) / sum(cf)` over every post-window day of every pair in `C`, with sums taken across all 10 seeds before dividing. Pass if 0.85 <= D <= 0.95. Per-seed `D` is reported but doesn't gate. Marked as a slow test. |

Why this design:
- **Counterfactual instead of the pre-window.** The pre-window has its own noise, and
  its weekday mix, season and trend differ from the post-window's. The counterfactual
  comes from the formula, so it has no noise and no drift.
- **Several seeds.** The dip is a property of the generator, not of seed 42. Ten seeds
  give about 10 times the data, so the SE drops by about 3.2 times.
- **The dip stays at 10%.** The market behavior doesn't change.
- **Thresholds.**
  - AC-09 keeps 1.20 to 1.70.
  - AC-10 goes from "below 1.00" to "0.85 to 0.95". That is **stricter**: it catches a
    missing dip and also a dip that's too strong.
- **Expected power** (Appendix A.4):

  | Case | Margin |
  |---|---|
  | AC-09 if lift is right | at least 5 SE |
  | AC-10 if dip is right | about 4 SE |
  | AC-10 if dip is missing | about 4 SE (the test fails, as it should) |

- **Cost.** 10 generator runs, at most about 10 minutes. These run in the slow test
  group, not on every save.

Fallback if multi-seed tests aren't acceptable: change the AC-10 check to
`D < 1.00` on seed 42 only. That gives about 2.6 SE, roughly a 1 in 200 chance of a
false failure, and a weak ability to catch a missing dip.

## Appendix A: Why the ranges can be met
These are hand estimates from the formulas in section 5. Real numbers come from the
first generator run. If a check fails, we fix the generator or approve a spec change.
We don't widen a range to make a check pass.

Noise on a pooled sum: with `N` rows of mean `mu` each, the relative variance of
`sum(y)` is about `1/sum(mu) + h/(N*k)`, where `h` is about 1.28 for lognormal sigma 0.5
(products of different sizes). For a ratio to a noise-free `cf`, that relative variance
is also the variance of the log ratio.

### A.1 AC-08 (yearly, standard curve)
Average of the standard curve over December, without Dec 25:
- Dec 1-14 runs from 1.1673 to 1.1977: average 1.1825, sum 16.555.
- Dec 15-31 runs from 1.2000 down to 1.0452 (it drops 0.30 over the 31 days to Jan 15):
  average 1.1226, sum 19.084.
- Take out Dec 25 (1.1032): (16.555 + 19.084 - 1.103) / 30 = **1.1512**.

Average over February (28 days):
- Feb 1-14 runs from 0.8452 to 0.8032: sum 11.539.
- Feb 15-28 runs from 0.8000 to 0.8371: sum 11.460.
- Total 22.999 / 28 = **0.8214**. (The leap year 2024 gives 0.8217.)

Yearly ratio: 1.1512 / 0.8214 = **1.401**.

Other effects:
- **Trend from mid-Feb to mid-Dec** (0.835 years): average of (1+g)^0.835 over the four
  standard categories, weighted by their share that year: **1.060** (2023) to **1.065**
  (2025). Continuing-product shares move this by less than 0.005.
- **Weekday mix**: February is exactly 4 weeks (1.000). December has 3 extra days and
  loses Dec 25:
  - 2023: +Fri, Sat, Sun, -Mon = 1.015
  - 2024: +Sun, Mon, Tue, -Wed = 0.992
  - 2025: +Mon, Tue, Wed, -Thu = 0.990

Expected ratio:

| Year | Ratio |
|---|---|
| 2023 | 1.401 x 1.060 x 1.015 = 1.508 |
| 2024 | 1.401 x 1.062 x 0.992 = 1.476 |
| 2025 | 1.401 x 1.065 x 0.990 = 1.477 |

Worst-case promo effect:
- 3 promos at once, each on a product with 7.5% of standard-category demand, a 1.6 lift,
  for 14 days of a month: about +/-6.8% on that month.
- Month-total noise: about +/-2%.
- Range: **1.36 to 1.64**, inside 1.30-1.75.
- Continuing products only, so launches and discontinued products don't affect it.

Outdoor:
- June-July average: 1.2372.
- Jan + Dec average, without closed days: 0.8066.
- Ratio **1.53**. Trend cancels because the summer months sit between January and December.
- Worst-case promos (3 big Outdoor promos in December) give about 1.36. The threshold is
  above 1.20.

### A.2 AC-06 (trend)
- 2023 and 2025 both have 365 days, and the extra weekday is a Sunday in 2023 and a
  Wednesday in 2025, both 0.95. So the weekday mix is identical.
- Seasonality and closed days repeat every year, so they cancel.
- With equal category shares the ratio is the average of (1+g)^2 =
  (1.3225 + 1.1664 + 1.1236 + 1.2100 + 1.0000) / 5 = **1.165**.
- Continuing products can shift the category shares. At most 2 lifecycle products per
  category, and each holds at most 6% of the total, so a category keeps at least 8% of
  the 20%. The extremes:
  - Electronics drops to 0.09 of continuing demand: **1.143**.
  - Apparel drops to 0.09: **1.187**.
- Promo differences between years (about +/-1%) and noise (+/-0.4%) give a full range of
  about **1.13 to 1.20**, inside 1.10-1.25.

### A.3 AC-07 (weekly)
- Each weekday shows up 156 or 157 times, spread over all seasons, so trend and
  seasonality cancel.
- Sat/Mon = 1.25 / 0.85 = **1.471**, give or take about 1.5%.
- Monday is lowest: Tue/Mon is 1.059, against about 0.9% noise on that difference, so
  more than 6 SE.

### A.4 AC-09 and AC-10 (promos)
Current wording (median of about 120 per-comparison ratios against the pre-window):
- The noise on the log of one comparison's ratio is about 0.50, so the SE of the median
  is about 0.058.
- AC-09: median lift is about 1.45. Margin to 1.20 is 3.3 SE, to 1.70 is 2.7 SE. Tight.
- AC-10: expected 0.90 against a limit of 1.00 is a log margin of 0.105, about 1.8 SE.
  **Can't be justified.**

P2 revised (pooled counterfactual):
- AC-09:
  - N is about 1,020 promo rows, with sum(cf) about 1,530 and sum(mu) about 2,220.
  - SE = sqrt(1/2220 + 1.28/2040) = **0.033**.
  - L is the volume-weighted average lift: typically 1.41 to 1.49, and at most 1.30 to
    1.60.
  - Margins: typical **at least 5 SE**. Even in the worst case where every promo is 10%
    off, 1.30 vs 1.20 is 2.4 SE. With 40 promos and random discounts, that case is very
    unlikely.
- AC-10, one seed:
  - N is about 840, with sum(mu) about 1,130.
  - SE = sqrt(1/1130 + 1.28/1680) = **0.041**.
  - Total separation between 0.90 and 1.00 is 0.105 / 0.041 = **2.6 SE**.
- AC-10, 10 seeds:
  - SE = 0.041 / sqrt(10) = **0.013**.
  - Dip right (0.90): 0.95 is log 0.054 away (**4.2 SE**) and 0.85 is log 0.057 away
    (**4.4 SE**).
  - Dip missing (1.00): 0.95 is log 0.051 away (**3.9 SE**), so the test fails as it should.

### A.5 AC-12 (noise), AC-17(d), AC-05 (volume)
Volume:
- Expected units for the range: about 250 x 1.12 (average trend) x 0.99 (average
  seasonality) x 1,090 open days = about **300k**. Lifecycle changes this by a few
  percent.
- Average line quantity is between 1.0 and 1.5, so order lines come to **200k to 300k**.
  AC-05's range is 150k-400k.

AC-12(a):
- E[OD] = `1 + sum(mu^2) / (2 sum(mu))`, which is at least `1 + (mean mu over S) / 2`.
- Mean mu over S is about 300k / 265k = 1.13, so E[OD] is at least **1.57**.
- With about 265k rows, OD's own noise is well under 0.01.
- Threshold: above 1.2.

AC-12(b):
- 42 continuing products x 5 regions = 210 rows a day, with Y(d) about 260.
- Noise variance is about 260 + 210 x 1.97 / 2 = 467, so the CV is about **0.083**.
- Within-month changes in the yearly curve (December runs 1.05 to 1.20) add about
  0.03-0.045. Promo spikes add about 0.02-0.03.
- Total: about **0.09**, at most about 0.12.
- The lowest it can go is Poisson noise alone, 1/sqrt(330) = **0.055**.
- Range 0.02 to 0.25. The thresholds stay as they are until a real run, as decided.

AC-17(d):
- 300k units with variance about 550k: SE about 0.25%. The range of +/-2% is 8 SE.

### A.6 Why AC-06 and AC-08 use continuing products
- AC-06: the 5 late launches add demand to 2025 that 2023 doesn't have, and the 3
  discontinued products do the opposite. Each product can hold up to 6% of demand. Five
  launches at 6% would turn 1.165 into about 1.5, above 1.25.
- AC-08: 3 standard-category products discontinued between February and December of the
  same year can take up to 22% out of December. That would turn 1.36 into about 1.06,
  below 1.30.
- Measuring on the 42 continuing products takes this effect out and leaves the
  thresholds alone.
