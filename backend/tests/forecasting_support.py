"""A small, hand-made spec 001 shaped dataset for spec 003 harness tests.

730 days (the shortest valid range), 2 regions and 5 products in 2 categories, with one
discontinued product, one launch inside the backtest and one inside the holdout. Values
follow a fixed formula, so the dataset is the same on every run and is written in well
under a second.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dealpilot.forecasting.baselines import Forecast, ModelInfo, seasonal_naive
from dealpilot.forecasting.engine import SeriesModel

START, END = date(2023, 1, 1), date(2024, 12, 30)  # 730 days; H = 2024-10-01
REGIONS = ("R01", "R02")
# (product_id, category, launch_date, discontinue_date)
PRODUCTS = (
    ("P001", "Home", START, None),
    ("P002", "Home", START, date(2023, 9, 1)),  # inactive in every test window
    ("P003", "Toys", START, None),
    ("P004", "Toys", date(2024, 10, 20), None),  # launches inside the holdout
    ("P005", "Toys", date(2024, 5, 10), None),  # launches inside the backtest
)
CLOSED = ((12, 25), (1, 1))
SEED = 42


def is_open(day: date) -> bool:
    return (day.month, day.day) not in CLOSED


def active(product: tuple, day: date) -> bool:
    _, _, launch, stop = product
    return launch <= day and (stop is None or day < stop)


def quantity(day_index: int, p: int, r: int, day: date) -> int:
    """A 42-day cycle (6-day and weekly parts) plus a small term outside that cycle."""
    cycle = 1 + (day_index * 7 + p * 3 + r * 5) % 6 + (3 if day.weekday() >= 5 else 0)
    return cycle + (1 if (day_index * day_index + p + r) % 5 == 0 else 0)


def write_dataset(folder: Path, seed: int = SEED, start: date = START, end: date = END) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    orders, lines, expected = [], [], []
    for i, day in enumerate(days):
        for r, region in enumerate(REGIONS):
            order_id = f"O{i:04d}{r}"
            day_lines = []
            for p, product in enumerate(PRODUCTS):
                units = 0
                if active(product, day) and is_open(day):
                    units = quantity(i, p, r, day)
                    day_lines.append((order_id, product[0], units))
                expected.append((day, product[0], region, float(units) + 0.5 * (units > 0)))
            if day_lines:
                orders.append((order_id, day, region))
                lines.extend(day_lines)
    tables = {
        "regions": pa.table({"region_id": list(REGIONS), "name": ["North", "South"],
                             "size_weight": [0.6, 0.4]}),
        "products": pa.table({
            "product_id": [p[0] for p in PRODUCTS], "name": [p[0] for p in PRODUCTS],
            "category": [p[1] for p in PRODUCTS], "list_price": [9.5] * len(PRODUCTS),
            "launch_date": pa.array([p[2] for p in PRODUCTS], pa.date32()),
            "discontinue_date": pa.array([p[3] for p in PRODUCTS], pa.date32())}),
        "orders": pa.table({"order_id": [o[0] for o in orders],
                            "order_date": pa.array([o[1] for o in orders], pa.date32()),
                            "region_id": [o[2] for o in orders]}),
        "order_lines": pa.table({"order_id": [x[0] for x in lines],
                                 "product_id": [x[1] for x in lines],
                                 "quantity": pa.array([x[2] for x in lines], pa.int64())}),
        "expected_demand": pa.table({
            "date": pa.array([x[0] for x in expected], pa.date32()),
            "product_id": [x[1] for x in expected], "region_id": [x[2] for x in expected],
            "expected_units": [x[3] for x in expected]}),
    }
    for name, table in tables.items():
        pq.write_table(table, folder / f"{name}.parquet")
    metadata = {"seed": seed, "start": start.isoformat(), "end": end.isoformat(),
                "generator_version": "test", "row_counts": {k: v.num_rows
                                                           for k, v in tables.items()},
                "parameters": {"closed_days": ["12-25", "01-01"], "base_demand": {"x": 1}}}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return folder


def folder_bytes(folder: Path) -> dict[str, bytes]:
    """Every file under a folder, by relative path (to prove nothing changed)."""
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


CANDIDATE_INFO = ModelInfo("weekly_copy", "1.0", {"note": "seasonal naive under test"},
                           True, False)


def candidate_model() -> SeriesModel:
    """A candidate for tests only: seasonal naive's forecasts under another name."""
    return SeriesModel(CANDIDATE_INFO, seasonal_naive)


@dataclass(frozen=True)
class FakeClean:
    """A clean-tree result stand-in (section 9.5 fake checker)."""
    outcome: str = "CLEAN"
    clean: bool = True
    commit: str | None = "a" * 40
    reasons: tuple = ()
    checker: str = "fake"
    checker_version: str = "0"
    libgit2_version: str = "0"

    def provenance(self) -> dict:
        return {"outcome": self.outcome, "clean_tree": self.clean, "commit": self.commit}


LAG_INFO = ModelInfo("six_week_copy", "1.0", {"lag_days": 42}, True, False)


def six_week_copy(history, start: date, cutoff: date, horizon: int) -> Forecast:
    """The value 42 days earlier (an earlier open day 42 days back if closed), else 0."""
    values = np.zeros(horizon, dtype=np.float64)
    for h in range(1, horizon + 1):
        source = cutoff + timedelta(days=h - 42)
        while source >= start and not is_open(source):
            source -= timedelta(days=42)
        if source >= start:
            values[h - 1] = history[(source - start).days]
    return Forecast(values)


def passing_candidate() -> SeriesModel:
    """A candidate for tests only that beats seasonal naive on this dataset's 42-day cycle,
    so a formal backtest can pass gate conditions 1 to 3."""
    return SeriesModel(LAG_INFO, six_week_copy)
