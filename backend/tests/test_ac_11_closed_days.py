"""
AC-11 — Closed days are closed.

Spec §8, AC-11:
  "Zero orders on every Dec 25 and Jan 1."

Spec §5.7: open(d) = 0 on December 25 and January 1.
"""
from __future__ import annotations

import pandas as pd

CLOSED_DATES = [
    # All Dec 25 and Jan 1 within the default range 2023-01-01 to 2025-12-31
    "2023-01-01",
    "2023-12-25",
    "2024-01-01",
    "2024-12-25",
    "2025-01-01",
    "2025-12-25",
]


def test_ac_11_no_orders_on_closed_days(tables: dict) -> None:
    """AC-11: zero orders on every Dec 25 and Jan 1 in the date range."""
    orders = tables["orders"].copy()
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    closed = pd.to_datetime(CLOSED_DATES)

    bad = orders[orders["order_date"].isin(closed)]
    assert bad.empty, (
        f"Found {len(bad)} orders on closed days:\n"
        + bad[["order_id", "order_date"]].to_string(index=False)
    )


def test_ac_11_closed_days_in_expected_demand_are_zero(tables: dict) -> None:
    """AC-11 (expected_demand): expected_units = 0 on every closed day."""
    ed = tables["expected_demand"].copy()
    ed["date"] = pd.to_datetime(ed["date"])
    closed = pd.to_datetime(CLOSED_DATES)

    bad = ed[ed["date"].isin(closed) & (ed["expected_units"] != 0)]
    assert bad.empty, (
        f"Found {len(bad)} expected_demand rows with non-zero units on closed days"
    )
