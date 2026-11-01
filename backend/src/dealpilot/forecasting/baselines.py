"""Seasonal naive and naive (spec 003 sections 6.1 and 6.2).

Both see only the history from `start` to the cutoff (section 4.3) and forecast one series
for horizons 1 to `horizon`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from dealpilot.forecasting.split import ForecastingError, is_open


@dataclass(frozen=True)
class ModelInfo:
    name: str
    version: str
    settings: dict
    uses_holiday_calendar: bool
    uses_planned_promotions: bool


SEASONAL_NAIVE = ModelInfo("seasonal_naive", "1.0",
                           {"lag_days": 7, "closed_day_fallback": "weekly"}, True, False)
NAIVE = ModelInfo("naive", "1.0", {}, False, False)


@dataclass(frozen=True)
class Forecast:
    values: np.ndarray  # float64, index h - 1
    zero_fallback_count: int = 0


def _check(history: np.ndarray, start: date, cutoff: date, horizon: int) -> np.ndarray:
    history = np.asarray(history)
    if history.ndim != 1 or len(history) != (cutoff - start).days + 1:
        raise ForecastingError("history must have one value for every day from start to cutoff")
    if horizon < 1:
        raise ForecastingError("horizon must be at least 1")
    return history


def seasonal_naive(history: np.ndarray, start: date, cutoff: date, horizon: int) -> Forecast:
    """Last observed week repeated forward, with the weekly closed-day fallback (D15)."""
    history = _check(history, start, cutoff, horizon)
    values = np.zeros(horizon, dtype=np.float64)
    zero_fallback = 0
    for h in range(1, horizon + 1):
        source = cutoff - timedelta(days=6 - (h - 1) % 7)  # s0
        while source >= start and not is_open(source):
            source -= timedelta(days=7)
        if source >= start:
            values[h - 1] = history[(source - start).days]
        else:
            zero_fallback += 1  # no open source day on or after start: forecast 0
    return Forecast(values, zero_fallback)


def naive(history: np.ndarray, start: date, cutoff: date, horizon: int) -> Forecast:
    """`y(cutoff)` for every horizon, with no closed-day handling."""
    history = _check(history, start, cutoff, horizon)
    return Forecast(np.full(horizon, float(history[-1])))
