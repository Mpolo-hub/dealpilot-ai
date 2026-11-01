"""Metrics for one level and one window (spec 003 sections 7.1 to 7.4).

Arrays are [series, day] for the window's days. Every metric exists for two day scopes:
`open` (closed days removed; the only scope the gate reads) and `all` (reported only).
`None` stands for the spec's `null`. Values are unrounded float64.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

import numpy as np

from dealpilot.forecasting.split import ForecastingError, date_range, open_mask

SCOPES = ("open", "all")


def scope_mask(days: Sequence[date], scope: str) -> np.ndarray:
    if scope == "open":
        return open_mask(list(days))
    if scope == "all":
        return np.ones(len(days), dtype=bool)
    raise ForecastingError(f"unknown day scope: {scope}")


def _pairs(forecast, actual, mask) -> tuple[np.ndarray, np.ndarray]:
    f = np.asarray(forecast, dtype=np.float64)
    a = np.asarray(actual, dtype=np.float64)
    if f.shape != a.shape or f.ndim != 2 or f.shape[1] != len(mask):
        raise ForecastingError("forecast and actual must be [series, day] arrays of one shape")
    return f[:, mask], a[:, mask]


def wape(forecast, actual, mask) -> float | None:
    """sum |F - A| / sum A, pooled over series and dates; null when sum A = 0."""
    f, a = _pairs(forecast, actual, mask)
    total = a.sum()
    return None if total == 0 else float(np.abs(f - a).sum() / total)


def _require_pairs(a: np.ndarray) -> None:
    """D26: section 5.1 windows always hold open days, so an empty scope is a bug."""
    if a.size == 0:
        raise ForecastingError("empty scope: no series-date pair to score (internal error)")


def mae(forecast, actual, mask) -> float:
    """mean |F - A| over all series-date pairs in scope; never null (D26)."""
    f, a = _pairs(forecast, actual, mask)
    _require_pairs(a)
    return float(np.abs(f - a).mean())


def bias(forecast, actual, mask) -> float | None:
    """sum (F - A) / sum A; null when sum A = 0."""
    f, a = _pairs(forecast, actual, mask)
    total = a.sum()
    return None if total == 0 else float((f - a).sum() / total)


def series_mae(forecast, actual, mask) -> np.ndarray:
    """Mean absolute error per series over the days in scope."""
    f, a = _pairs(forecast, actual, mask)
    _require_pairs(a)
    return np.abs(f - a).mean(axis=1)


def mase_scale(train, start: date) -> float | None:
    """scale_s over training days t with t - 7 >= start, leaving out closed t or t - 7.

    `train` holds one series from `start` to the cutoff. A zero scale gives `None`
    (MASE_s is then null); so does a history with no usable pair (D25).
    """
    y = np.asarray(train, dtype=np.float64)
    if len(y) <= 7:
        return None
    is_open_day = open_mask(date_range(start, start + timedelta(days=len(y) - 1)))
    usable = is_open_day[7:] & is_open_day[:-7]
    diffs = np.abs(y[7:] - y[:-7])[usable]
    if diffs.size == 0:
        return None
    scale = math.fsum(diffs.tolist()) / diffs.size
    return None if scale == 0 else scale


def mase(forecast, actual, mask, scales: Sequence[float | None],
         eligible: np.ndarray) -> tuple[float | None, float | None]:
    """Mean and median of MASE_s over eligible series with a defined MASE_s (report only)."""
    errors = series_mae(forecast, actual, mask)
    values = [float(errors[i] / s) for i, s in enumerate(scales)
              if eligible[i] and s is not None]
    if not values:
        return None, None
    return math.fsum(values) / len(values), float(median(values))


@dataclass(frozen=True)
class RelMAE:
    value: float | None
    n_included: int
    n_base_perfect: int
    n_cand_perfect: int
    n_tie: int
    n_inactive: int


def relmae(mae_candidate, mae_baseline, eligible) -> RelMAE:
    """Section 7.3: geometric mean of MAE_c,s / MAE_b,s over eligible series with both > 0."""
    c = np.asarray(mae_candidate, dtype=np.float64)
    b = np.asarray(mae_baseline, dtype=np.float64)
    eligible = np.asarray(eligible, dtype=bool)
    if not c.shape == b.shape == eligible.shape:
        raise ForecastingError("per-series MAE arrays and the eligible mask must match")
    if not (np.isfinite(c).all() and np.isfinite(b).all()):
        # D26: NaN or infinity means a bug upstream; never count it as a tie.
        raise ForecastingError("per-series MAE must be finite (internal error)")
    logs, base_perfect, cand_perfect, tie = [], 0, 0, 0
    for mc, mb in zip(c[eligible], b[eligible]):
        if mb > 0 and mc > 0:
            logs.append(math.log(mc / mb))
        elif mb == 0 and mc > 0:
            base_perfect += 1
        elif mb > 0 and mc == 0:
            cand_perfect += 1
        else:
            tie += 1
    value = math.exp(math.fsum(logs) / len(logs)) if logs else None
    return RelMAE(value, len(logs), base_perfect, cand_perfect, tie,
                  int((~eligible).sum()))


def is_active_in_window(launch: date, discontinue: date | None, first: date,
                        last: date) -> bool:
    """Spec 001 section 4: active on d when launch <= d and (no stop date or d < stop)."""
    return launch <= last and (discontinue is None or discontinue > first)


def is_inactive(products: Sequence[tuple[date, date | None]], first: date, last: date) -> bool:
    """Section 7.4: a series is inactive only if every product in it is inactive."""
    return not any(is_active_in_window(launch, stop, first, last) for launch, stop in products)


@dataclass(frozen=True)
class WindowMetrics:
    wape: float | None
    mae: float | None
    bias: float | None


def window_metrics(forecast, actual, days: Sequence[date]) -> dict[str, WindowMetrics]:
    """WAPE, MAE and Bias for both day scopes of one level and window."""
    out = {}
    for scope in SCOPES:
        mask = scope_mask(days, scope)
        out[scope] = WindowMetrics(wape(forecast, actual, mask), mae(forecast, actual, mask),
                                   bias(forecast, actual, mask))
    return out
