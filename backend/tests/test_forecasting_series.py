"""Spec 003 series building (AC-FC-03) on small hand-made tables in DuckDB.

The universe has the default shape (5 regions, 50 products in 5 categories) so the series
counts are 1, 5 and 250, but only a few hand-written orders over 14 days.
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import numpy as np
import pyarrow as pa
import pytest

from dealpilot.forecasting.series import build_series
from dealpilot.forecasting.split import ForecastingError

START, END = date(2024, 12, 20), date(2025, 1, 2)  # includes Dec 25 and Jan 1
CATEGORIES = ["Electronics", "Grocery", "Home", "Sports", "Toys"]
PRODUCTS = [f"P{i:03d}" for i in range(1, 51)]
REGIONS = [f"R0{i}" for i in range(1, 6)]
# (order_id, order_date, region_id, [(product_id, quantity), ...])
ORDERS = [
    ("O1", date(2024, 12, 20), "R01", [("P001", 3), ("P002", 1), ("P001", 2)]),
    ("O2", date(2024, 12, 20), "R01", [("P001", 4)]),
    ("O3", date(2024, 12, 23), "R05", [("P050", 7), ("P011", 1)]),
    ("O4", date(2024, 12, 26), "R03", [("P025", 2)]),
    ("O5", date(2025, 1, 2), "R02", [("P001", 5), ("P049", 6)]),
    ("O6", date(2024, 12, 19), "R01", [("P001", 100)]),  # before start: ignored
    ("O7", date(2025, 1, 3), "R01", [("P001", 100)]),  # after end: ignored
]


def _connection(orders=ORDERS, products=PRODUCTS) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("products", pa.table({
        "product_id": products,
        "category": [CATEGORIES[i // 10 % 5] for i in range(len(products))],
    }))
    con.register("regions", pa.table({"region_id": REGIONS}))
    con.register("orders", pa.table({
        "order_id": [o[0] for o in orders],
        "order_date": pa.array([o[1] for o in orders], pa.date32()),
        "region_id": [o[2] for o in orders],
    }))
    lines = [(o[0], p, q) for o in orders for p, q in o[3]]
    con.register("order_lines", pa.table({
        "order_id": [x[0] for x in lines],
        "product_id": [x[1] for x in lines],
        "quantity": pa.array([x[2] for x in lines], pa.int64()),
    }))
    return con


def test_ac_fc_03_series_are_complete() -> None:
    con = _connection()
    s = build_series(con, START, END)
    n_days = (END - START).days + 1
    assert len(s.days) == n_days and s.days[0] == START and s.days[-1] == END
    assert {level: len(keys) for level, keys in s.keys.items()} == {
        "total": 1, "category": 5, "product_region": 250}
    for level, values in s.values.items():
        assert values.shape == (len(s.keys[level]), n_days)
        assert values.dtype == np.int64

    pr = s.series("product_region", ("P001", "R01"))
    assert pr[0] == 3 + 2 + 4  # summed over lines and orders of one day
    assert pr[(date(2025, 1, 2) - START).days] == 0  # P001 sold in R02 that day, not R01
    assert s.series("product_region", ("P001", "R02"))[-1] == 5
    assert s.series("product_region", ("P003", "R04")).sum() == 0  # never sold: all zeros
    for closed in (date(2024, 12, 25), date(2025, 1, 1)):
        assert (s.values["product_region"][:, (closed - START).days] == 0).all()


def test_ac_fc_03_levels_add_up() -> None:
    s = build_series(_connection(), START, END)
    pr = s.values["product_region"]
    category_of = {p: CATEGORIES[i // 10 % 5] for i, p in enumerate(PRODUCTS)}
    for c, category in enumerate(s.keys["category"]):
        rows = [i for i, (p, _) in enumerate(s.keys["product_region"])
                if category_of[p] == category]
        assert (s.values["category"][c] == pr[rows].sum(axis=0)).all()
    assert (s.values["total"][0] == pr.sum(axis=0)).all()


def test_ac_fc_03_total_matches_independent_sum() -> None:
    con = _connection()
    s = build_series(con, START, END)
    rows = con.execute(
        "SELECT o.order_date, SUM(l.quantity) FROM order_lines l "
        "JOIN orders o USING (order_id) WHERE o.order_date BETWEEN ? AND ? GROUP BY 1",
        [START, END]).fetchall()
    expected = np.zeros(len(s.days), dtype=np.int64)
    for day, units in rows:
        expected[(day - START).days] = units
    assert (s.values["total"][0] == expected).all()
    assert s.values["total"].sum() == 3 + 1 + 2 + 4 + 7 + 1 + 2 + 5 + 6


def test_ac_fc_03_sales_outside_the_universe_are_refused() -> None:
    orders = [("O1", START, "R01", [("P999", 1)])]
    with pytest.raises(ForecastingError, match="universe"):
        build_series(_connection(orders=orders), START, END)


def test_ac_fc_03_end_before_start_is_refused() -> None:
    with pytest.raises(ForecastingError):
        build_series(_connection(), END, START - timedelta(days=1))
