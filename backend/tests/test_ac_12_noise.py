"""
AC-12 — Noise is real but not too big.

Spec §8, AC-12 (P3 approved in principle, thresholds provisional):
  (a) Overdispersion statistic OD > 1.2.
  (b) Residual coefficient of variation CV_res in [0.02, 0.25].

Spec §8.2 (exact algorithms — binding):

  (a) OD:
    S = { (p, r, d) : mu(p, r, d) > 0 }  — all 50 products.
    OD = sum_S (y - mu)^2 / sum_S mu.

  (b) CV_res:
    1. Scope: continuing products (42), all regions, open days only.
    2. Y(d) = daily quantity sum in scope.
    3. M(m) = mean Y(d) over open days of calendar month m.
    4. W(w) = mean of Y(d)/M(m(d)) over all open days with weekday w.
    5. e(d) = Y(d) / (M(m(d)) * W(w(d))).
    6. CV_res = sd(e, ddof=1) / mean(e).

Note: AC-12 thresholds are provisional until first real generator run.
A threshold failure must be reported and investigated, not silently widened.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from conftest import as_ns_dates, open_days


def test_ac_12a_overdispersion(tables: dict) -> None:
    """AC-12(a): OD = sum((y-mu)^2) / sum(mu) > 1.2, over all rows where mu > 0."""
    ed = tables["expected_demand"].copy()
    ed["date"] = as_ns_dates(ed["date"])

    order_lines = tables["order_lines"]
    orders = tables["orders"]

    # Observed units: sum quantity by (product_id, region_id, order_date)
    lines_with_date = order_lines.merge(
        orders[["order_id", "order_date", "region_id"]], on="order_id", how="left"
    )
    lines_with_date["order_date"] = as_ns_dates(lines_with_date["order_date"])
    observed = (
        lines_with_date
        .groupby(["product_id", "region_id", "order_date"])["quantity"]
        .sum()
        .reset_index()
        .rename(columns={"order_date": "date"})
    )

    # Merge with expected demand on (product_id, region_id, date)
    merged = ed.merge(observed, on=["product_id", "region_id", "date"], how="left")
    merged["quantity"] = merged["quantity"].fillna(0)

    # S = rows where mu > 0
    S = merged[merged["expected_units"] > 0]
    assert not S.empty, "Set S is empty — no rows with mu > 0"

    y = S["quantity"].values
    mu = S["expected_units"].values
    OD = np.sum((y - mu) ** 2) / np.sum(mu)

    assert OD > 1.2, (
        f"AC-12(a) OD={OD:.4f} <= 1.2. "
        f"Threshold is provisional — report and investigate, do not widen."
    )


def test_ac_12b_residual_cv(tables: dict) -> None:
    """AC-12(b): CV_res = sd(e)/mean(e) in [0.02, 0.25] for continuing products, open days."""
    products = tables["products"].copy()
    products["launch_date"] = pd.to_datetime(products["launch_date"])
    start = pd.Timestamp("2023-01-01")
    continuing_ids = set(
        products[
            (products["launch_date"] == start) & products["discontinue_date"].isna()
        ]["product_id"]
    )
    assert len(continuing_ids) == 42, f"Expected 42 continuing products, got {len(continuing_ids)}"

    order_lines = tables["order_lines"]
    orders = tables["orders"]

    lines = order_lines.merge(
        orders[["order_id", "order_date"]], on="order_id", how="left"
    )
    lines["order_date"] = as_ns_dates(lines["order_date"])
    # Scope: continuing products
    lines = lines[lines["product_id"].isin(continuing_ids)]

    # Y(d) = daily units in scope on every open day in the range; no sales counts as 0.
    # Reindexing on the open-day calendar also drops closed days.
    Y = (
        lines.groupby("order_date")["quantity"].sum()
        .reindex(open_days(), fill_value=0)
        .rename("Y")
        .rename_axis("date")
        .reset_index()
    )
    Y["year_month"] = Y["date"].dt.to_period("M")
    Y["weekday"] = Y["date"].dt.day_of_week

    # M(m) = mean Y(d) over open days of calendar month m
    M = Y.groupby("year_month")["Y"].mean().rename("M")
    Y = Y.merge(M.reset_index(), on="year_month", how="left")
    assert (Y["M"] > 0).all(), "Some M(m) = 0 — test would be invalid"

    # W(w) = mean of Y(d)/M(m(d)) over all open days with weekday w
    Y["ratio"] = Y["Y"] / Y["M"]
    W = Y.groupby("weekday")["ratio"].mean().rename("W")
    Y = Y.merge(W.reset_index(), on="weekday", how="left")

    # e(d) = Y(d) / (M(m(d)) * W(w(d)))
    Y["e"] = Y["Y"] / (Y["M"] * Y["W"])

    e = Y["e"].values
    cv_res = np.std(e, ddof=1) / np.mean(e)

    assert 0.02 <= cv_res <= 0.25, (
        f"AC-12(b) CV_res={cv_res:.4f} outside [0.02, 0.25]. "
        f"Threshold is provisional — report and investigate, do not widen."
    )
