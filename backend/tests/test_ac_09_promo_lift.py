"""
AC-09 — Promotions lift sales.  (P2 approved)

Spec §8, AC-09:
  "Seed 42. L = sum(y) / sum(cf) over every promo day of every pair in C.
   Sums are taken over all rows first, then divided once. Pass if 1.20 <= L <= 1.70."

Spec §8.1:
  C = set of (promo, region) pairs.
  cf(p, r, d) on promo days = expected_units / lift, where lift = 1.15 + 1.5 * discount_pct.
  One pooled ratio L, not a median of per-pair ratios.

Spec §6.3: expected_demand.parquet must not be used as a model input.
  It is used here only in the evaluation/test role, as specified.
"""
from __future__ import annotations

import pandas as pd

from conftest import as_ns_dates


def _build_promo_region_days(
    promotions: pd.DataFrame,
    all_region_ids: set[str],
) -> pd.DataFrame:
    """
    Expand promotions to one row per (promo_id, product_id, region_id, date).
    For null region_id (all-region promos), emit one row per region.
    """
    promotions = promotions.copy()
    promotions["start_date"] = pd.to_datetime(promotions["start_date"])
    promotions["end_date"] = pd.to_datetime(promotions["end_date"])

    rows: list[dict] = []
    for _, promo in promotions.iterrows():
        regions = all_region_ids if pd.isna(promo["region_id"]) else {promo["region_id"]}
        dates = pd.date_range(promo["start_date"], promo["end_date"])
        for region_id in regions:
            for date in dates:
                rows.append({
                    "promo_id": promo["promo_id"],
                    "product_id": promo["product_id"],
                    "region_id": region_id,
                    "date": date,
                    "discount_pct": float(promo["discount_pct"]),
                })
    return pd.DataFrame(rows)


def test_ac_09_promo_lift_ratio(tables: dict) -> None:
    """AC-09: pooled L = sum(y)/sum(cf) over all promo days in C; 1.20 <= L <= 1.70."""
    promotions = tables["promotions"]
    order_lines = tables["order_lines"]
    orders = tables["orders"]
    expected_demand = tables["expected_demand"]
    all_regions = set(tables["regions"]["region_id"])

    # Expand C: (promo, region, date) for every promo day
    promo_days = _build_promo_region_days(promotions, all_regions)
    assert not promo_days.empty, (
        f"AC-09: C has no promo days ({len(promotions)} promotions), so L cannot be computed"
    )
    promo_days["date"] = as_ns_dates(promo_days["date"])

    # cf(p, r, d) = expected_units / lift  where lift = 1.15 + 1.5 * discount_pct
    promo_days["lift"] = 1.15 + 1.5 * promo_days["discount_pct"]
    expected_demand = expected_demand.copy()
    expected_demand["date"] = as_ns_dates(expected_demand["date"])

    cf_df = promo_days.merge(
        expected_demand,
        on=["product_id", "region_id", "date"],
        how="left",
    )
    cf_df["cf"] = cf_df["expected_units"] / cf_df["lift"]

    # Every promo day in C must have cf > 0: §5.6 rules 1-2 keep promos on open, active
    # days. A missing (NaN) or non-positive cf means required data is absent, so fail
    # instead of letting sum() skip it.
    invalid = cf_df[~(cf_df["cf"] > 0)]
    assert invalid.empty, (
        f"AC-09: {len(invalid)} of {len(cf_df)} promo days in C have missing or "
        f"non-positive cf. First 10:\n"
        + invalid[["promo_id", "product_id", "region_id", "date", "expected_units"]]
        .head(10).to_string(index=False)
    )

    # y: observed units = sum of order_line quantities for that (product, region, date)
    lines_with_date = order_lines.merge(
        orders[["order_id", "order_date", "region_id"]],
        on="order_id", how="left",
    )
    lines_with_date["order_date"] = as_ns_dates(lines_with_date["order_date"])
    observed = (
        lines_with_date
        .groupby(["product_id", "region_id", "order_date"])["quantity"]
        .sum()
        .reset_index()
        .rename(columns={"order_date": "date"})
    )

    cf_df = cf_df.merge(
        observed, on=["product_id", "region_id", "date"], how="left"
    )
    cf_df["quantity"] = cf_df["quantity"].fillna(0)

    sum_y = cf_df["quantity"].sum()
    sum_cf = cf_df["cf"].sum()

    assert sum_cf > 0, f"AC-09: sum(cf) is {sum_cf}, so L is undefined"
    L = sum_y / sum_cf

    assert 1.20 <= L <= 1.70, (
        f"AC-09 promo lift L={L:.4f} outside [1.20, 1.70]  "
        f"(sum_y={sum_y:.1f}, sum_cf={sum_cf:.1f})"
    )
