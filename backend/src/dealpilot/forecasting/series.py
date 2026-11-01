"""Daily unit series for the three levels (spec 003 sections 4.1 and 4.2).

Evaluation-side code: the scoring universe comes from `products` and `regions`, not from
which keys have sales, so every product-region pair gets a series even with no sales.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

from dealpilot.forecasting.split import ForecastingError, date_range

LEVELS = ("total", "category", "product_region")
TOTAL_KEY = "total"


@dataclass(frozen=True)
class SeriesSet:
    """`values[level]` is an int64 array [series, day]; `keys[level]` names its rows."""
    days: tuple[date, ...]
    keys: dict[str, tuple]
    values: dict[str, np.ndarray]

    def series(self, level: str, key) -> np.ndarray:
        return self.values[level][self.keys[level].index(key)]


def build_series(con: duckdb.DuckDBPyConnection, start: date, end: date) -> SeriesSet:
    """Series for every date from `start` to `end`; 0 where a key has no sales (A6).

    `con` must expose the spec 001 tables `orders`, `order_lines`, `products` and `regions`
    (as tables or views). Only `quantity`, `order_date`, `region_id`, `product_id` and
    `category` are read.
    """
    if end < start:
        raise ForecastingError("end must not be before start")
    days = date_range(start, end)
    products = con.execute(
        "SELECT product_id, category FROM products ORDER BY product_id").fetchall()
    regions = [r[0] for r in con.execute(
        "SELECT region_id FROM regions ORDER BY region_id").fetchall()]
    pairs = [(p, r) for p, _ in products for r in regions]
    row = {pair: i for i, pair in enumerate(pairs)}
    values = np.zeros((len(pairs), len(days)), dtype=np.int64)

    sales = con.execute(
        "SELECT l.product_id, o.region_id, o.order_date, SUM(l.quantity) "
        "FROM order_lines l JOIN orders o ON o.order_id = l.order_id "
        "WHERE o.order_date BETWEEN ? AND ? GROUP BY 1, 2, 3",
        [start, end],
    ).fetchall()
    for product_id, region_id, day, units in sales:
        i = row.get((product_id, region_id))
        if i is None:
            raise ForecastingError(
                f"sales for {product_id}/{region_id} are outside the products/regions universe")
        values[i, (day - start).days] += int(units)

    categories = sorted({c for _, c in products})
    category_of = {p: c for p, c in products}
    by_category = np.zeros((len(categories), len(days)), dtype=np.int64)
    for (p, _), i in row.items():
        by_category[categories.index(category_of[p])] += values[i]
    total = values.sum(axis=0, keepdims=True)
    return SeriesSet(
        days=tuple(days),
        keys={"total": (TOTAL_KEY,), "category": tuple(categories),
              "product_region": tuple(pairs)},
        values={"total": total, "category": by_category, "product_region": values},
    )
