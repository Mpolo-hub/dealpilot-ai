"""
AC-08 — Yearly pattern is visible.

Spec §8, AC-08 (P1 approved, continuing products only):
  Standard categories (Electronics, Home, Office, Apparel):
    For each calendar year 2023, 2024, 2025:
    avg daily units Dec 1–31 (excl Dec 25) / avg daily units Feb 1–last Feb day
    must be in [1.30, 1.75].

  Outdoor category:
    For each calendar year 2023, 2024, 2025:
    avg daily units Jun 1–Jul 31 / avg daily units (Jan 1–31 + Dec 1–31, excl closed days)
    must be > 1.20.

Spec §8.1: closed days removed = Dec 25, Jan 1.
Spec §4: continuing products = launch_date == 2023-01-01 AND discontinue_date is null.
"""
from __future__ import annotations

import calendar

import pandas as pd
import pytest

STANDARD_CATS = {"Electronics", "Home", "Office", "Apparel"}
OUTDOOR_CAT = "Outdoor"
CLOSED_MONTH_DAY = {(12, 25), (1, 1)}


def _avg_daily_units(df: pd.DataFrame, year: int, month_start: int, day_start: int,
                     month_end: int, day_end: int) -> float:
    """Average daily units over an inclusive date range, excluding closed days."""
    start = pd.Timestamp(year, month_start, day_start)
    end = pd.Timestamp(year, month_end, day_end)
    mask = (
        (df["order_date"] >= start)
        & (df["order_date"] <= end)
        & ~df["order_date"].apply(lambda d: (d.month, d.day) in CLOSED_MONTH_DAY)
    )
    period_df = df[mask]
    if period_df.empty:
        return 0.0
    # Number of open days in period
    all_days = pd.date_range(start, end)
    open_days = [d for d in all_days if (d.month, d.day) not in CLOSED_MONTH_DAY]
    return period_df["quantity"].sum() / len(open_days)


@pytest.fixture(scope="module")
def continuing_lines_by_cat(tables) -> dict[str, pd.DataFrame]:
    """Return order_lines+order_date for continuing products, split by standard/outdoor."""
    products = tables["products"].copy()
    products["launch_date"] = pd.to_datetime(products["launch_date"])
    start = pd.Timestamp("2023-01-01")
    continuing = products[
        (products["launch_date"] == start) & products["discontinue_date"].isna()
    ][["product_id", "category"]]

    order_lines = tables["order_lines"]
    orders = tables["orders"]
    lines = order_lines.merge(orders[["order_id", "order_date"]], on="order_id", how="left")
    lines["order_date"] = pd.to_datetime(lines["order_date"])
    lines = lines.merge(continuing, on="product_id", how="inner")
    return lines


def test_ac_08_standard_dec_feb_ratio(continuing_lines_by_cat: pd.DataFrame) -> None:
    """AC-08: standard-category Dec/Feb ratio in [1.30, 1.75] for each of 2023, 2024, 2025."""
    lines = continuing_lines_by_cat[continuing_lines_by_cat["category"].isin(STANDARD_CATS)]
    errors: list[str] = []
    for year in (2023, 2024, 2025):
        last_feb_day = 29 if calendar.isleap(year) else 28
        dec_avg = _avg_daily_units(lines, year, 12, 1, 12, 31)
        feb_avg = _avg_daily_units(lines, year, 2, 1, 2, last_feb_day)
        if feb_avg == 0:
            errors.append(f"{year}: zero units in February")
            continue
        ratio = dec_avg / feb_avg
        if not (1.30 <= ratio <= 1.75):
            errors.append(
                f"{year}: Dec/Feb ratio {ratio:.4f} outside [1.30, 1.75] "
                f"(dec_avg={dec_avg:.2f}, feb_avg={feb_avg:.2f})"
            )
    assert not errors, "AC-08 standard Dec/Feb failures:\n" + "\n".join(errors)


def test_ac_08_outdoor_summer_winter_ratio(continuing_lines_by_cat: pd.DataFrame) -> None:
    """AC-08: Outdoor Jun–Jul avg / (Jan + Dec avg) > 1.20 for each of 2023, 2024, 2025."""
    lines = continuing_lines_by_cat[continuing_lines_by_cat["category"] == OUTDOOR_CAT]
    errors: list[str] = []
    for year in (2023, 2024, 2025):
        # Summer: Jun 1 – Jul 31
        summer_start = pd.Timestamp(year, 6, 1)
        summer_end = pd.Timestamp(year, 7, 31)
        summer_mask = (
            (lines["order_date"] >= summer_start)
            & (lines["order_date"] <= summer_end)
            & ~lines["order_date"].apply(lambda d: (d.month, d.day) in CLOSED_MONTH_DAY)
        )
        summer_df = lines[summer_mask]
        summer_open_days = [
            d for d in pd.date_range(summer_start, summer_end)
            if (d.month, d.day) not in CLOSED_MONTH_DAY
        ]
        summer_avg = (
            summer_df["quantity"].sum() / len(summer_open_days) if summer_open_days else 0.0
        )

        # Winter: Jan 1–31 + Dec 1–31 of same year (excl closed days)
        jan_start, jan_end = pd.Timestamp(year, 1, 1), pd.Timestamp(year, 1, 31)
        dec_start, dec_end = pd.Timestamp(year, 12, 1), pd.Timestamp(year, 12, 31)
        winter_mask = (
            (
                ((lines["order_date"] >= jan_start) & (lines["order_date"] <= jan_end))
                | ((lines["order_date"] >= dec_start) & (lines["order_date"] <= dec_end))
            )
            & ~lines["order_date"].apply(lambda d: (d.month, d.day) in CLOSED_MONTH_DAY)
        )
        winter_df = lines[winter_mask]
        jan_open = [
            d for d in pd.date_range(jan_start, jan_end)
            if (d.month, d.day) not in CLOSED_MONTH_DAY
        ]
        dec_open = [
            d for d in pd.date_range(dec_start, dec_end)
            if (d.month, d.day) not in CLOSED_MONTH_DAY
        ]
        winter_open_days = len(jan_open) + len(dec_open)
        winter_avg = winter_df["quantity"].sum() / winter_open_days if winter_open_days else 0.0

        if winter_avg == 0:
            errors.append(f"{year}: zero Outdoor units in winter")
            continue
        ratio = summer_avg / winter_avg
        if ratio <= 1.20:
            errors.append(
                f"{year}: Outdoor summer/winter ratio {ratio:.4f} not > 1.20 "
                f"(summer_avg={summer_avg:.2f}, winter_avg={winter_avg:.2f})"
            )
    assert not errors, "AC-08 Outdoor failures:\n" + "\n".join(errors)
