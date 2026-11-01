"""
AC-17 — Expected demand is correct.

Spec §8, AC-17:
  (a) One row per product, region and date, with no nulls and no negatives.
  (b) Exactly 0 on closed days and outside the active period, above 0 everywhere else.
  (c) Recomputing from spec §5.1 using output tables and metadata.json matches
      within relative error 1e-9.
  (d) Total observed units / total expected units in [0.98, 1.02].

Spec §6.2: 50 x 5 x 1,096 = 274,000 rows by default.
Spec §6.3: expected_demand.parquet is NEVER a model input.
  It is read here ONLY in the evaluation role — as specified.

AC-17(c) takes every fixed value from the spec (conftest.SPEC_PARAMS and
REGION_SIZE_WEIGHTS), never from generator-written parameters. From generator output it
reads only drawn values: base(p) from metadata.json, plus product lifecycle dates,
categories and promotions from the output tables. If base_demand is missing, it fails.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from conftest import REGION_SIZE_WEIGHTS, SPEC_PARAMS, as_ns_dates

START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2025-12-31")
TOTAL_ROWS = 50 * 5 * 1_096  # 274,000
CLOSED_MMDD = {int(md.replace("-", "")) for md in SPEC_PARAMS["closed_days"]}  # {1225, 101}


def _is_closed(dates: pd.Series) -> pd.Series:
    return (dates.dt.month * 100 + dates.dt.day).isin(CLOSED_MMDD)


def _with_products(tables: dict) -> pd.DataFrame:
    """expected_demand joined to product category and lifecycle dates, with is_active."""
    ed = tables["expected_demand"].copy()
    ed["date"] = as_ns_dates(ed["date"])  # same unit as promo dates
    cols = ["product_id", "category", "launch_date", "discontinue_date"]
    products = tables["products"][cols].copy()
    products["launch_date"] = pd.to_datetime(products["launch_date"])
    products["discontinue_date"] = pd.to_datetime(products["discontinue_date"])
    df = ed.merge(products, on="product_id", how="left")
    df["is_active"] = (df["date"] >= df["launch_date"]) & (
        df["discontinue_date"].isna() | (df["date"] < df["discontinue_date"])
    )
    return df


# ---------------------------------------------------------------------------
# AC-17(a): shape, nulls, negatives
# ---------------------------------------------------------------------------

def test_ac_17a_row_count(tables: dict) -> None:
    """AC-17(a): expected_demand has exactly 274,000 rows (50 x 5 x 1,096)."""
    n = len(tables["expected_demand"])
    assert n == TOTAL_ROWS, f"expected_demand has {n} rows, expected {TOTAL_ROWS}"


def test_ac_17a_full_coverage(tables: dict) -> None:
    """AC-17(a): exactly one row per product, region and date from --start to --end.

    Every ID must exist in products/regions, every date must be in the inclusive range,
    and no (date, product, region) may repeat. Given that, a row count equal to the full
    grid size means every combination is present, without building the grid.
    """
    ed = tables["expected_demand"]
    products = set(tables["products"]["product_id"])
    regions = set(tables["regions"]["region_id"])
    days = pd.date_range(START, END)  # inclusive of both ends

    assert set(ed["product_id"]) == products, (
        f"product_ids differ from products: extra {sorted(set(ed['product_id']) - products)}, "
        f"missing {sorted(products - set(ed['product_id']))}"
    )
    assert set(ed["region_id"]) == regions, (
        f"region_ids differ from regions: extra {sorted(set(ed['region_id']) - regions)}, "
        f"missing {sorted(regions - set(ed['region_id']))}"
    )
    dates = as_ns_dates(ed["date"])
    outside = ~dates.isin(days)
    assert not outside.any(), (
        f"{outside.sum()} rows dated outside {START.date()}..{END.date()}: "
        f"{sorted(dates[outside].dt.date.unique())[:10]}"
    )
    keys = pd.DataFrame(
        {"date": dates, "product_id": ed["product_id"], "region_id": ed["region_id"]}
    )
    dupes = keys[keys.duplicated(keep=False)]
    assert dupes.empty, f"{len(dupes)} rows repeat a (date, product, region):\n{dupes.head(10)}"
    grid = len(days) * len(products) * len(regions)
    assert len(ed) == grid, f"expected_demand has {len(ed)} rows; the full grid has {grid}"


def test_ac_17a_no_nulls(tables: dict) -> None:
    """AC-17(a): no nulls in expected_demand."""
    ed = tables["expected_demand"]
    for col in ed.columns:
        assert ed[col].notna().all(), f"Null values in expected_demand.{col}"


def test_ac_17a_no_negatives(tables: dict) -> None:
    """AC-17(a): expected_units >= 0 everywhere."""
    assert (tables["expected_demand"]["expected_units"] >= 0).all()


# ---------------------------------------------------------------------------
# AC-17(b): zeros on closed days and outside active period; positive elsewhere
# ---------------------------------------------------------------------------

def test_ac_17b_zero_on_closed_days(tables: dict) -> None:
    """AC-17(b): expected_units = 0 on Dec 25 and Jan 1."""
    ed = tables["expected_demand"]
    closed = _is_closed(pd.to_datetime(ed["date"]))
    bad = ed[closed & (ed["expected_units"] != 0)]
    assert bad.empty, f"{len(bad)} rows have non-zero expected_units on closed days"


def test_ac_17b_zero_outside_active_period(tables: dict) -> None:
    """AC-17(b): expected_units = 0 for inactive products (before launch or after discontinue)."""
    df = _with_products(tables)
    before_launch = df["date"] < df["launch_date"]
    bad_before = df[before_launch & (df["expected_units"] != 0)]
    assert bad_before.empty, f"{len(bad_before)} rows have non-zero expected_units before launch"

    after_disc = df["discontinue_date"].notna() & (df["date"] >= df["discontinue_date"])
    bad_after = df[after_disc & (df["expected_units"] != 0)]
    assert bad_after.empty, (
        f"{len(bad_after)} rows have non-zero expected_units after discontinuation"
    )


def test_ac_17b_positive_on_open_active_days(tables: dict) -> None:
    """AC-17(b): expected_units > 0 on open days within the active period."""
    df = _with_products(tables)
    should_be_positive = df["is_active"] & ~_is_closed(df["date"])
    bad = df[should_be_positive & (df["expected_units"] <= 0)]
    assert bad.empty, f"{len(bad)} rows have expected_units <= 0 on open, active days"


# ---------------------------------------------------------------------------
# AC-17(c): recomputation from §5.1 formula
# ---------------------------------------------------------------------------

def _yearly(category: pd.Series, dates: pd.Series) -> np.ndarray:
    """§5.5: straight line between the monthly anchors (15th), counting real calendar days."""
    years = range(dates.dt.year.min() - 1, dates.dt.year.max() + 2)
    day = SPEC_PARAMS["yearly_anchor_day"]
    anchor_dates = pd.to_datetime([f"{y}-{m:02d}-{day:02d}" for y in years for m in range(1, 13)])
    x = dates.to_numpy().astype("datetime64[D]").astype(float)
    xp = anchor_dates.to_numpy().astype("datetime64[D]").astype(float)
    curve = category.map(SPEC_PARAMS["yearly_curve_by_category"]).to_numpy()
    out = np.full(len(dates), np.nan)
    for name, anchors in SPEC_PARAMS["yearly_anchors"].items():
        mask = curve == name
        out[mask] = np.interp(x[mask], xp, np.tile(anchors, len(years)))
    return out


def _promo_factors(promotions: pd.DataFrame, region_ids: list[str]) -> pd.DataFrame:
    """One row per (product, region, date) under a promo (lift) or in its post-window (dip)."""
    rows = []
    post_days = range(1, SPEC_PARAMS["promo_post_window_days"] + 1)
    for promo in promotions.itertuples():
        regions = region_ids if pd.isna(promo.region_id) else [promo.region_id]
        lift = SPEC_PARAMS["promo_lift_base"] + SPEC_PARAMS["promo_lift_per_discount"] * float(
            promo.discount_pct
        )
        end = pd.Timestamp(promo.end_date)
        days = [(d, lift) for d in pd.date_range(promo.start_date, end)] + [
            (end + pd.Timedelta(days=k), SPEC_PARAMS["promo_dip_factor"]) for k in post_days
        ]
        rows += [(promo.product_id, r, d, f) for r in regions for d, f in days]
    return pd.DataFrame(rows, columns=["product_id", "region_id", "date", "promo_factor"])


def test_ac_17c_recomputation_matches(tables: dict) -> None:
    """
    AC-17(c): recomputing expected_units from spec §5.1 matches expected_demand.parquet
    within relative error 1e-9.
    """
    base = tables["metadata"].get("parameters", {}).get("base_demand")
    assert isinstance(base, dict), "metadata.json has no parameters.base_demand; cannot recompute"

    promo = _promo_factors(tables["promotions"], list(REGION_SIZE_WEIGHTS))
    clash = promo[promo.duplicated(["product_id", "region_id", "date"], keep=False)]
    assert clash.empty, f"§5.6 rule 3: more than one promo factor on these rows:\n{clash.head(10)}"

    df = _with_products(tables).merge(promo, on=["product_id", "region_id", "date"], how="left")
    d = df["date"]
    base_f = df["product_id"].map(base)
    assert base_f.notna().all(), "base_demand is missing some product_ids"

    trend = (1 + df["category"].map(SPEC_PARAMS["trend_rates"])) ** (
        (d - START).dt.days / SPEC_PARAMS["trend_days_per_year"]
    )
    computed = (
        (~_is_closed(d)).to_numpy()
        * df["is_active"].to_numpy()
        * base_f.to_numpy()
        * df["region_id"].map(REGION_SIZE_WEIGHTS).to_numpy()
        * trend.to_numpy()
        * np.asarray(SPEC_PARAMS["weekly_multipliers"])[d.dt.day_of_week.to_numpy()]
        * _yearly(df["category"], d)
        * df["promo_factor"].fillna(1.0).to_numpy()
    )
    actual = df["expected_units"].to_numpy(dtype=float)

    rel_err = np.abs(computed - actual) / np.where(actual == 0, 1.0, actual)
    bad = ((actual == 0) != (computed == 0)) | ~(rel_err <= 1e-9)
    report = df.loc[bad, ["product_id", "region_id", "date", "expected_units"]].assign(
        computed=computed[bad], rel_err=rel_err[bad]
    )
    assert not bad.any(), (
        f"AC-17(c): {bad.sum()} rows differ from §5.1. First 10:\n"
        + report.head(10).to_string(index=False)
    )


# ---------------------------------------------------------------------------
# AC-17(d): total observed / total expected in [0.98, 1.02]
# ---------------------------------------------------------------------------

def test_ac_17d_observed_to_expected_ratio(tables: dict) -> None:
    """AC-17(d): total observed units / total expected units in [0.98, 1.02]."""
    total_expected = tables["expected_demand"]["expected_units"].sum()
    assert total_expected > 0, "Total expected units is zero"
    total_observed = tables["order_lines"]["quantity"].sum()

    ratio = total_observed / total_expected
    assert 0.98 <= ratio <= 1.02, (
        f"AC-17(d) observed/expected ratio {ratio:.4f} outside [0.98, 1.02]  "
        f"(total_observed={total_observed}, total_expected={total_expected:.1f})"
    )
