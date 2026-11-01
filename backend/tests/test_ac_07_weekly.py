"""
AC-07 — Weekly pattern is visible.

Spec §8, AC-07:
  "Average daily units by weekday (closed days removed): Saturday is highest,
   Monday is lowest, Sat/Mon is between 1.30 and 1.65."

Spec §8.1: closed days = Dec 25, Jan 1. Average daily units over a period = total units
over the open days in it / number of open days in it, so open days with no sales count as 0.
Spec §5.4: weekday multipliers — Mon 0.85, Sat 1.25, ratio = 1.25/0.85 ≈ 1.471.
"""
from __future__ import annotations

import pandas as pd

from conftest import as_ns_dates, open_days


def _avg_daily_units_by_weekday(tables: dict) -> pd.Series:
    """Average daily units per weekday (0=Mon .. 6=Sun) over every open day in the range."""
    lines = tables["order_lines"].merge(
        tables["orders"][["order_id", "order_date"]], on="order_id", how="left"
    )
    lines["order_date"] = as_ns_dates(lines["order_date"])
    # Reindexing on the open-day calendar drops closed days and fills no-sale days with 0
    daily = lines.groupby("order_date")["quantity"].sum().reindex(open_days(), fill_value=0)
    return daily.groupby(daily.index.day_of_week).mean()


def test_ac_07_saturday_highest(tables: dict) -> None:
    """AC-07: Saturday has the highest average daily units across all weekdays."""
    avg_by_day = _avg_daily_units_by_weekday(tables)
    assert avg_by_day.idxmax() == 5, (
        f"Saturday (5) is not the highest weekday; highest is {avg_by_day.idxmax()}"
    )


def test_ac_07_monday_lowest(tables: dict) -> None:
    """AC-07: Monday has the lowest average daily units across all weekdays."""
    avg_by_day = _avg_daily_units_by_weekday(tables)
    assert avg_by_day.idxmin() == 0, (
        f"Monday (0) is not the lowest weekday; lowest is {avg_by_day.idxmin()}"
    )


def test_ac_07_sat_mon_ratio(tables: dict) -> None:
    """AC-07: Sat/Mon ratio of average daily units is between 1.30 and 1.65."""
    avg_by_day = _avg_daily_units_by_weekday(tables)
    ratio = avg_by_day[5] / avg_by_day[0]
    assert 1.30 <= ratio <= 1.65, (
        f"AC-07 Sat/Mon ratio {ratio:.4f} outside [1.30, 1.65]"
    )
