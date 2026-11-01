"""
AC-10 — Post-promo dip exists.  (P2 approved, SLOW TEST)

Spec §8, AC-10:
  "Seeds 1 to 10 (default range). D = sum(y) / sum(cf) over every post-window
   day of every pair in C, with sums taken across all 10 seeds before dividing.
   Pass if 0.85 <= D <= 0.95. Per-seed D is reported but doesn't gate.
   Marked as a slow test."

Spec §8.1:
  cf(p, r, d) on post-window days = expected_units / 0.90  (the 10% dip factor).
  Post-window = 7 days immediately after the promo ends.
  The existing single-value --seed CLI option is used; generator is invoked 10 times.

Spec §6.3 + §8.1: expected_demand.parquet is read only for evaluation;
  it is never a model input.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from conftest import DEFAULT_END, DEFAULT_START, as_ns_dates, load_tables, run_generator_ok

DIP_FACTOR = 0.90  # spec §5.6
POST_WINDOW_DAYS = 7  # spec §5.6


def _load_tables_for_seed(seed: int, tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Run the generator for one seed and return the tables AC-10 needs."""
    out = tmp_path_factory.mktemp(f"seed_{seed}_ac10")
    run_generator_ok(seed, DEFAULT_START, DEFAULT_END, out)
    tables = load_tables(out, ["promotions", "order_lines", "orders", "regions", "expected_demand"])
    with open(out / "metadata.json", encoding="utf-8") as f:
        tables["metadata"] = json.load(f)
    return tables


def _compute_post_window_sums(tables: dict, seed: int) -> tuple[float, float, float]:
    """
    For one seed run, return (sum_y, sum_cf, per_seed_D).
    sum_y = total observed units on post-window days.
    sum_cf = total cf on post-window days.
    Fails (never skips) if C is empty or any post-window day lacks a positive cf.
    """
    promotions = tables["promotions"].copy()
    order_lines = tables["order_lines"]
    orders = tables["orders"]
    expected_demand = tables["expected_demand"].copy()
    all_regions = set(tables["regions"]["region_id"])

    promotions["end_date"] = as_ns_dates(promotions["end_date"])
    expected_demand["date"] = as_ns_dates(expected_demand["date"])

    # Build post-window rows: 7 days after promo end for each (promo, region) pair
    rows: list[dict] = []
    for _, promo in promotions.iterrows():
        regions = all_regions if pd.isna(promo["region_id"]) else {promo["region_id"]}
        for day_offset in range(1, POST_WINDOW_DAYS + 1):
            post_date = promo["end_date"] + pd.Timedelta(days=day_offset)
            for region_id in regions:
                rows.append({
                    "product_id": promo["product_id"],
                    "region_id": region_id,
                    "date": post_date,
                })
    assert rows, (
        f"AC-10 seed {seed}: C has no post-window days ({len(promotions)} promotions), "
        f"so D cannot be computed"
    )
    post_df = pd.DataFrame(rows)
    post_df["date"] = as_ns_dates(post_df["date"])

    # cf = expected_units / 0.90 on post-window days
    post_df = post_df.merge(expected_demand, on=["product_id", "region_id", "date"], how="left")
    post_df["cf"] = post_df["expected_units"] / DIP_FACTOR

    # y: observed units
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

    post_df = post_df.merge(observed, on=["product_id", "region_id", "date"], how="left")
    post_df["quantity"] = post_df["quantity"].fillna(0)

    # Every post-window day in C must have cf > 0: §5.6 rules 1-2 keep whole windows inside
    # the range, on open days, while the product is active. A missing (NaN) or zero cf
    # means required data is absent, so fail instead of dropping the row.
    invalid = post_df[~(post_df["cf"] > 0)]
    assert invalid.empty, (
        f"AC-10 seed {seed}: {len(invalid)} of {len(post_df)} post-window days in C have "
        f"missing or non-positive cf. First 10:\n"
        + invalid[["product_id", "region_id", "date", "expected_units"]]
        .head(10).to_string(index=False)
    )

    sum_y = float(post_df["quantity"].sum())
    sum_cf = float(post_df["cf"].sum())
    assert sum_cf > 0, f"AC-10 seed {seed}: sum(cf) is {sum_cf}, so per-seed D is undefined"
    return sum_y, sum_cf, sum_y / sum_cf


@pytest.mark.slow
def test_ac_10_post_promo_dip_pooled(tmp_path_factory: pytest.TempPathFactory) -> None:
    """
    AC-10 (SLOW): pooled D = sum(y)/sum(cf) across seeds 1–10 on post-window days.
    Threshold: 0.85 <= D <= 0.95.
    Per-seed D is computed and reported diagnostically but does not gate.
    """
    total_y = 0.0
    total_cf = 0.0
    per_seed_results: list[tuple[int, float, float, float]] = []

    for seed in range(1, 11):
        tables = _load_tables_for_seed(seed, tmp_path_factory)
        sum_y, sum_cf, d_seed = _compute_post_window_sums(tables, seed)
        total_y += sum_y
        total_cf += sum_cf
        per_seed_results.append((seed, sum_y, sum_cf, d_seed))

    # Log per-seed diagnostics (always, regardless of gate)
    print("\nAC-10 per-seed diagnostics (diagnostic only, do not gate):")
    print(f"{'Seed':>6}  {'sum_y':>10}  {'sum_cf':>10}  {'D':>8}")
    for seed, sy, sc, d in per_seed_results:
        print(f"{seed:>6}  {sy:>10.1f}  {sc:>10.1f}  {d:>8.4f}")

    assert total_cf > 0, "total sum(cf) across all 10 seeds is zero"
    D = total_y / total_cf
    print(f"\nPooled D = {D:.4f}  (total_y={total_y:.1f}, total_cf={total_cf:.1f})")

    assert 0.85 <= D <= 0.95, (
        f"AC-10 post-promo dip D={D:.4f} outside [0.85, 0.95].  "
        f"Investigate: check generator dip factor (should be 0.90) and threshold bounds. "
        f"Do NOT silently weaken the threshold — report this failure."
    )
