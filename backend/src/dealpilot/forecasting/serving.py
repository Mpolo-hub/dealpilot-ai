"""Serve the seasonal naive baseline for one series (spec 003 section 10, D11 approved
2026-11-04; spec 002 D10 amended the same day).

Only observed sales from the dataset `start` to the cutoff are read, so data after the
cutoff can never reach the forecast (AC-FC-API-03). `expected_demand.parquet`,
`metadata.json` `parameters` and `regions.size_weight` are never read (AC-FC-API-04). The
served model is seasonal naive "1.0" (section 6.1); the acceptance gate does not apply to
the baseline itself. Interval bounds are null: the baseline gives no ranges.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb
import numpy as np

from dealpilot.forecasting.baselines import SEASONAL_NAIVE, seasonal_naive

MIN_HISTORY_DAYS = 6  # the cutoff must be on or after start + 6 (section 10)
MAX_HORIZON = 28
_BASE_SQL = ("SELECT o.order_date, SUM(l.quantity) FROM order_lines l "
             "JOIN orders o ON o.order_id = l.order_id "
             "JOIN products p ON p.product_id = l.product_id "
             "WHERE o.order_date BETWEEN ? AND ? ")
# One fixed statement per level; key values are always parameters.
_HISTORY_SQL = {
    "total": _BASE_SQL + "GROUP BY 1",
    "category": _BASE_SQL + "AND p.category = ? GROUP BY 1",
    "product_region": _BASE_SQL + "AND l.product_id = ? AND o.region_id = ? GROUP BY 1",
}


@dataclass(frozen=True)
class SeriesKey:
    """`level` and its key fields: none, `category`, or `product_id` and `region_id`."""
    level: str
    category: str | None = None
    product_id: str | None = None
    region_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        if self.level == "category":
            return {"category": self.category or ""}
        if self.level == "product_region":
            return {"product_id": self.product_id or "", "region_id": self.region_id or ""}
        return {}


def history(con: duckdb.DuckDBPyConnection, key: SeriesKey, start: date,
            cutoff: date) -> np.ndarray:
    """Daily units from `start` to `cutoff` for the key, 0 on days without sales (A6).

    The query has fixed SQL; key values are DuckDB parameters. Rows after the cutoff are
    filtered out in SQL, so they are never read into Python.
    """
    params: list = [start, cutoff]
    if key.level == "category":
        params.append(key.category)
    elif key.level == "product_region":
        params += [key.product_id, key.region_id]
    sql = _HISTORY_SQL[key.level]
    values = np.zeros((cutoff - start).days + 1, dtype=np.int64)
    for day, units in con.execute(sql, params).fetchall():
        values[(day - start).days] = int(units)
    return values


def forecast_response(con: duckdb.DuckDBPyConnection, key: SeriesKey, start: date,
                      cutoff: date, horizon: int) -> dict:
    """The response body of spec 002 section 6 as refined by spec 003 section 10."""
    result = seasonal_naive(history(con, key, start, cutoff), start, cutoff, horizon)
    return {
        "level": key.level,
        "key": key.as_dict(),
        "cutoff": cutoff.isoformat(),
        "horizon": horizon,
        "model": {"name": SEASONAL_NAIVE.name, "version": SEASONAL_NAIVE.version,
                  "settings": dict(SEASONAL_NAIVE.settings)},
        "uses_planned_promotions": SEASONAL_NAIVE.uses_planned_promotions,
        "points": [
            {"date": (cutoff + timedelta(days=h)).isoformat(),
             "forecast": float(result.values[h - 1]), "lower_80": None, "upper_80": None}
            for h in range(1, horizon + 1)
        ],
    }
