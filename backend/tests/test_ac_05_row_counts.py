"""
AC-05 — Row counts are in range.

Spec §8, AC-05:
  "5 regions, 50 products, 1,800-2,200 customers, 30-50 promotions,
   150k-400k order lines."

Note: The spec says exactly 40 promotions (§4). The AC-05 range 30–50 is the
acceptance test tolerance. Both are checked here.
"""
from __future__ import annotations


def test_ac_05_region_count(tables: dict) -> None:
    """AC-05: exactly 5 regions."""
    assert len(tables["regions"]) == 5


def test_ac_05_product_count(tables: dict) -> None:
    """AC-05: exactly 50 products."""
    assert len(tables["products"]) == 50


def test_ac_05_customer_count(tables: dict) -> None:
    """AC-05: 1,800 to 2,200 customers."""
    n = len(tables["customers"])
    assert 1_800 <= n <= 2_200, f"customer count {n} outside [1800, 2200]"


def test_ac_05_customer_count_exact(tables: dict) -> None:
    """Spec §4: exactly 2,000 customers."""
    assert len(tables["customers"]) == 2_000, "Expected exactly 2,000 customers per §4"


def test_ac_05_promotion_count_range(tables: dict) -> None:
    """AC-05: 30 to 50 promotions."""
    n = len(tables["promotions"])
    assert 30 <= n <= 50, f"promotion count {n} outside [30, 50]"


def test_ac_05_promotion_count_exact(tables: dict) -> None:
    """Spec §4: exactly 40 promotions."""
    assert len(tables["promotions"]) == 40, "Expected exactly 40 promotions per §4"


def test_ac_05_order_line_count(tables: dict) -> None:
    """AC-05: 150,000 to 400,000 order lines."""
    n = len(tables["order_lines"])
    assert 150_000 <= n <= 400_000, f"order_line count {n} outside [150k, 400k]"
