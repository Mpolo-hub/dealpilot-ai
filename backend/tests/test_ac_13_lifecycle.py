"""
AC-13 — Product lifecycle works.

Spec §8, AC-13:
  "At least 4 products have first sale after --start;
   at least 2 have last sale before --end."

Spec §4:
  Exactly 5 products have launch_date > --start (late launches).
  Exactly 3 products have discontinue_date set (and are not among the 5 late launches).
"""
from __future__ import annotations

import pandas as pd

START_DATE = pd.Timestamp("2023-01-01")
END_DATE = pd.Timestamp("2025-12-31")
# §4: late launches are at or after --start + 90 days; discontinuations at or before --end - 90.
LIFECYCLE_MARGIN = pd.Timedelta(days=90)


def _sale_span(tables: dict) -> pd.DataFrame:
    """First and last order_date per product."""
    lines = tables["order_lines"][["order_id", "product_id"]].merge(
        tables["orders"][["order_id", "order_date"]], on="order_id", how="left"
    )
    lines["order_date"] = pd.to_datetime(lines["order_date"])
    return lines.groupby("product_id")["order_date"].agg(["min", "max"])


def test_ac_13_late_launches_have_first_sale_after_start(tables: dict) -> None:
    """AC-13: at least 4 late-launch products have their first sale >= --start + 90 days.

    Only products with launch_date after --start count, so a continuing product with a
    run of zero-sale days can't make this pass. A late launch with no sales counts as a miss.
    """
    products = tables["products"]
    late_ids = products.loc[pd.to_datetime(products["launch_date"]) > START_DATE, "product_id"]
    first_sale = _sale_span(tables)["min"].reindex(late_ids)
    late = (first_sale >= START_DATE + LIFECYCLE_MARGIN).sum()
    assert late >= 4, (
        f"Only {late} late-launch products have first sale >= --start + 90 days; "
        f"expected at least 4. First sales: {first_sale.to_dict()}"
    )


def test_ac_13_discontinued_have_last_sale_before_end(tables: dict) -> None:
    """AC-13: at least 2 discontinued products have their last sale <= --end - 90 days.

    Only products with a discontinue_date count, so a product with no sales near --end by
    chance can't make this pass. A discontinued product with no sales counts as a miss.
    """
    products = tables["products"]
    disc_ids = products.loc[products["discontinue_date"].notna(), "product_id"]
    last_sale = _sale_span(tables)["max"].reindex(disc_ids)
    early_exit = (last_sale <= END_DATE - LIFECYCLE_MARGIN).sum()
    assert early_exit >= 2, (
        f"Only {early_exit} discontinued products have last sale <= --end - 90 days; "
        f"expected at least 2. Last sales: {last_sale.to_dict()}"
    )


def test_ac_13_product_table_lifecycle_counts(tables: dict) -> None:
    """Spec §4: exactly 5 late launches and exactly 3 discontinued products."""
    products = tables["products"].copy()
    products["launch_date"] = pd.to_datetime(products["launch_date"])

    late_launches = products[products["launch_date"] > START_DATE]
    discontinued = products[products["discontinue_date"].notna()]

    assert len(late_launches) == 5, f"Expected 5 late launches, got {len(late_launches)}"
    assert len(discontinued) == 3, f"Expected 3 discontinued products, got {len(discontinued)}"

    # The 3 discontinued must not overlap with the 5 late launches (spec §4)
    overlap = set(late_launches["product_id"]) & set(discontinued["product_id"])
    assert not overlap, f"Discontinued products overlap with late launches: {overlap}"


def test_ac_13_lifecycle_spread_across_categories(tables: dict) -> None:
    """Spec §4: lifecycle products (8 total) spread at most 2 per category."""
    products = tables["products"].copy()
    products["launch_date"] = pd.to_datetime(products["launch_date"])

    lifecycle_ids = set(products[products["launch_date"] > START_DATE]["product_id"]) | \
                    set(products[products["discontinue_date"].notna()]["product_id"])
    lifecycle_prods = products[products["product_id"].isin(lifecycle_ids)]

    by_category = lifecycle_prods.groupby("category").size()
    violations = by_category[by_category > 2]
    assert violations.empty, (
        f"Categories with more than 2 lifecycle products: {violations.to_dict()}"
    )
