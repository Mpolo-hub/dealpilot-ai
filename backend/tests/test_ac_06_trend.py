"""
AC-06 — Trend is up.

Spec §8, AC-06 (P1 approved):
  "Continuing products, all regions: total units over calendar year 2025 divided
   by total over calendar year 2023 is between 1.10 and 1.25."

Spec §4: continuing products = launch_date == --start AND discontinue_date is null.
Exactly 42 such products.
Spec §8.1: closed days (Dec 25, Jan 1) are removed from the aggregation.
"""
from __future__ import annotations

import pandas as pd

CLOSED_MONTH_DAY = {(12, 25), (1, 1)}


def _is_closed(d: pd.Timestamp) -> bool:
    return (d.month, d.day) in CLOSED_MONTH_DAY


def test_ac_06_trend_ratio_in_range(tables: dict) -> None:
    """AC-06: 2025/2023 unit ratio for continuing products in [1.10, 1.25]."""
    products = tables["products"].copy()  # tables is session-shared; don't mutate it
    order_lines = tables["order_lines"]
    orders = tables["orders"]

    # Identify continuing products: launch_date == start, discontinue_date null
    start_date = pd.Timestamp("2023-01-01")
    products["launch_date"] = pd.to_datetime(products["launch_date"])
    continuing = products[
        (products["launch_date"] == start_date) & products["discontinue_date"].isna()
    ]["product_id"]
    assert len(continuing) == 42, f"Expected 42 continuing products, got {len(continuing)}"

    # Join order_lines -> orders to get order_date
    lines_with_date = order_lines.merge(
        orders[["order_id", "order_date"]], on="order_id", how="left"
    )
    lines_with_date["order_date"] = pd.to_datetime(lines_with_date["order_date"])

    # Filter to continuing products
    filtered = lines_with_date[lines_with_date["product_id"].isin(continuing)]

    # Exclude closed days
    filtered = filtered[~filtered["order_date"].apply(_is_closed)]

    # Sum quantity by year
    filtered["year"] = filtered["order_date"].dt.year
    by_year = filtered.groupby("year")["quantity"].sum()

    units_2023 = by_year.get(2023, 0)
    units_2025 = by_year.get(2025, 0)

    assert units_2023 > 0, "No units in 2023 for continuing products"
    assert units_2025 > 0, "No units in 2025 for continuing products"

    ratio = units_2025 / units_2023
    assert 1.10 <= ratio <= 1.25, (
        f"AC-06 trend ratio {ratio:.4f} outside [1.10, 1.25]  "
        f"(units_2023={units_2023}, units_2025={units_2025})"
    )
