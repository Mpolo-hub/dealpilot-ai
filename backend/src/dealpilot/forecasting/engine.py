"""Forecasting and scoring for the evaluation harness (spec 003 sections 4 to 8).

Model code sees only `VisibleInputs` (section 4.3). The evaluator places each model's
forecasts into the full scoring universe; a series the model cannot see at the cutoff gets
0 (section 4.2). Every result here is in memory; `records` writes files.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np

from dealpilot.forecasting import metrics as m
from dealpilot.forecasting.baselines import NAIVE, SEASONAL_NAIVE, ModelInfo, naive, seasonal_naive
from dealpilot.forecasting.gate import LevelScores, WindowScore, mean_relmae, mean_wape
from dealpilot.forecasting.inputs import EvalData, VisibleInputs, visible_inputs
from dealpilot.forecasting.series import LEVELS
from dealpilot.forecasting.split import ForecastingError, Window, date_range

REFERENCE = SEASONAL_NAIVE.name  # the gate's baseline (section 8)
MEAN, HOLDOUT = "mean", "holdout"


@dataclass(frozen=True)
class LevelForecast:
    keys: tuple  # exactly the visible keys of the level, in the order given
    values: np.ndarray  # float64 [series, horizon]
    zero_fallback_count: int = 0


class Model(Protocol):
    info: ModelInfo

    def forecast(self, inputs: VisibleInputs, level: str, horizon: int) -> LevelForecast: ...


@dataclass(frozen=True)
class SeriesModel:
    """A model that forecasts every visible series of a level on its own."""
    info: ModelInfo
    function: Callable

    def forecast(self, inputs: VisibleInputs, level: str, horizon: int) -> LevelForecast:
        keys, history = inputs.history[level]
        values = np.zeros((len(keys), horizon), dtype=np.float64)
        fallback = 0
        for i in range(len(keys)):
            result = self.function(history[i], inputs.start, inputs.cutoff, horizon)
            values[i] = result.values
            fallback += result.zero_fallback_count
        return LevelForecast(keys, values, fallback)


BASELINES = (SeriesModel(SEASONAL_NAIVE, seasonal_naive), SeriesModel(NAIVE, naive))


def window_name(window: Window) -> str:
    return f"fold_{window.index:02d}"


# --------------------------------------------------------------------------- forecasting

@dataclass
class WindowForecasts:
    """Forecasts of every model for one scored window, over the full universe."""
    days: tuple[date, ...]
    train_end: date  # last training day used for the MASE scale
    values: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)  # model, level
    zero_fallback: dict[str, int] = field(default_factory=dict)  # model


def _place(data: EvalData, level: str, result: LevelForecast, visible_keys: tuple,
           horizon: int) -> np.ndarray:
    if tuple(result.keys) != tuple(visible_keys):
        raise ForecastingError(f"the model must forecast exactly the visible {level} keys")
    values = np.asarray(result.values, dtype=np.float64)
    if values.shape != (len(visible_keys), horizon) or not np.isfinite(values).all():
        raise ForecastingError(f"the model gave a malformed {level} forecast")
    universe = data.series.keys[level]
    out = np.zeros((len(universe), horizon), dtype=np.float64)  # not visible: 0 (4.2)
    row = {key: i for i, key in enumerate(universe)}
    for j, key in enumerate(visible_keys):
        out[row[key]] = values[j]
    return out


def forecast_origins(data: EvalData, models: Sequence[Model],
                     origins: Sequence[Window]) -> WindowForecasts:
    """Fit and forecast at each origin in turn; the origins' days form one window."""
    days = tuple(d for w in origins for d in date_range(w.first, w.last))
    result = WindowForecasts(days, origins[0].cutoff)
    for model in models:
        parts: dict[str, list[np.ndarray]] = {level: [] for level in LEVELS}
        fallback = 0
        for window in origins:
            inputs = visible_inputs(data, window.cutoff)
            for level in LEVELS:
                forecast = model.forecast(inputs, level, window.horizon)
                parts[level].append(_place(data, level, forecast, inputs.history[level][0],
                                           window.horizon))
                fallback += forecast.zero_fallback_count
        result.values[model.info.name] = {level: np.concatenate(parts[level], axis=1)
                                          for level in LEVELS}
        result.zero_fallback[model.info.name] = fallback
    return result


# --------------------------------------------------------------------------- scoring

def _members(data: EvalData, level: str) -> list[list[tuple[date, date | None]]]:
    """Product (launch, stop) dates of each series of a level (evaluation only)."""
    dates = {p.product_id: (p.launch_date, p.discontinue_date) for p in data.products}
    keys = data.series.keys[level]
    if level == "product_region":
        return [[dates[product_id]] for product_id, _ in keys]
    if level == "category":
        category_of = {p.product_id: p.category for p in data.products}
        return [[dates[p] for p in dates if category_of[p] == key] for key in keys]
    return [list(dates.values())]


def inactive_mask(data: EvalData, level: str, first: date, last: date) -> np.ndarray:
    return np.array([m.is_inactive(products, first, last) for products in
                     _members(data, level)], dtype=bool)


def _actual(data: EvalData, level: str, days: Sequence[date]) -> np.ndarray:
    cols = [(d - data.start).days for d in days]
    return data.series.values[level][:, cols]


def _expected(data: EvalData, level: str, days: Sequence[date]) -> np.ndarray:
    cols = [(d - data.start).days for d in days]
    pr = data.expected[:, cols]
    if level == "product_region":
        return pr
    if level == "total":
        return pr.sum(axis=0, keepdims=True)
    category_of = {p.product_id: p.category for p in data.products}
    keys = data.series.keys["category"]
    out = np.zeros((len(keys), len(cols)), dtype=np.float64)
    for i, (product_id, _) in enumerate(data.series.keys["product_region"]):
        out[keys.index(category_of[product_id])] += pr[i]
    return out


def _scales(data: EvalData, level: str, train_end: date) -> list[float | None]:
    n = (train_end - data.start).days + 1
    return [m.mase_scale(row[:n], data.start) for row in data.series.values[level]]


@dataclass
class WindowScores:
    """Everything scored for one window (a fold, or the whole holdout)."""
    name: str
    metric_rows: list[dict] = field(default_factory=list)
    series_rows: list[dict] = field(default_factory=list)
    signal_rows: list[dict] = field(default_factory=list)
    gate: dict[str, dict[str, dict[str, WindowScore]]] = field(default_factory=dict)
    n_inactive: dict[str, int] = field(default_factory=dict)  # level
    zero_fallback: dict[str, int] = field(default_factory=dict)  # model


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else float(numerator / denominator)


def score_window(data: EvalData, name: str, forecasts: WindowForecasts,
                 signal: bool) -> WindowScores:
    days = forecasts.days
    first, last = days[0], days[-1]
    out = WindowScores(name, zero_fallback=dict(forecasts.zero_fallback))
    models = list(forecasts.values)
    for level in LEVELS:
        actual = _actual(data, level, days)
        inactive = inactive_mask(data, level, first, last)
        eligible = ~inactive
        out.n_inactive[level] = int(inactive.sum())
        scales = _scales(data, level, forecasts.train_end)
        expected = _expected(data, level, days) if signal else None
        for scope in m.SCOPES:
            mask = m.scope_mask(days, scope)
            per_series = {model: m.series_mae(forecasts.values[model][level], actual, mask)
                          for model in models}
            for model in models:
                f = forecasts.values[model][level]
                mase_mean, mase_median = m.mase(f, actual, mask, scales, eligible)
                row = {"model": model, "level": level, "window": name, "scope": scope,
                       "wape": m.wape(f, actual, mask), "mae": m.mae(f, actual, mask),
                       "bias": m.bias(f, actual, mask), "mase_mean": mase_mean,
                       "mase_median": mase_median, "relmae": None,
                       "n_inactive": out.n_inactive[level], "n_tie": None,
                       "n_base_perfect": None, "n_cand_perfect": None}
                if model != REFERENCE:
                    rel = m.relmae(per_series[model], per_series[REFERENCE], eligible)
                    row.update(relmae=rel.value, n_tie=rel.n_tie,
                               n_base_perfect=rel.n_base_perfect,
                               n_cand_perfect=rel.n_cand_perfect)
                    out.gate.setdefault(model, {}).setdefault(level, {})[scope] = WindowScore(
                        row["wape"], m.wape(forecasts.values[REFERENCE][level], actual, mask),
                        rel.value)
                out.metric_rows.append(row)
                if level == "product_region":
                    out.series_rows.extend(_series_rows(
                        data, model, name, scope, per_series, scales, inactive))
                if signal:
                    f_masked, x_masked = f[:, mask], expected[:, mask]
                    a_masked = actual[:, mask]
                    out.signal_rows.append({
                        "model": model, "level": level, "window": name, "scope": scope,
                        "signal_wape": _ratio(np.abs(f_masked - x_masked).sum(),
                                              x_masked.sum()),
                        "noise_floor": _ratio(np.abs(x_masked - a_masked).sum(),
                                              a_masked.sum())})
    return out


def _series_rows(data: EvalData, model: str, window: str, scope: str,
                 per_series: dict[str, np.ndarray], scales: list[float | None],
                 inactive: np.ndarray) -> list[dict]:
    rows = []
    mae_model, mae_ref = per_series[model], per_series[REFERENCE]
    for i, (product_id, region_id) in enumerate(data.series.keys["product_region"]):
        scale = scales[i]
        eligible = not inactive[i]
        r = None
        if model != REFERENCE and eligible and mae_model[i] > 0 and mae_ref[i] > 0:
            r = float(mae_model[i] / mae_ref[i])
        rows.append({"model": model, "window": window, "scope": scope,
                     "product_id": product_id, "region_id": region_id,
                     "mae": float(mae_model[i]), "scale": scale,
                     "mase": None if scale is None or not eligible
                     else float(mae_model[i] / scale),
                     "r": r, "eligible": eligible, "inactive": bool(inactive[i])})
    return rows


def _mean(values: list[float | None]) -> tuple[float | None, int]:
    defined = [v for v in values if v is not None]
    return (math.fsum(defined) / len(defined) if defined else None), len(defined)


def mean_rows(folds: Sequence[WindowScores]) -> list[dict]:
    """Section 7.5 averages over the 13 folds, per model, level and day scope."""
    grouped: dict[tuple, list[dict]] = {}
    for fold in folds:
        for row in fold.metric_rows:
            grouped.setdefault((row["model"], row["level"], row["scope"]), []).append(row)
    out = []
    for (model, level, scope), rows in grouped.items():
        mae_value, n_mae = _mean([r["mae"] for r in rows])
        bias_value, n_bias = _mean([r["bias"] for r in rows])
        mase_value, n_mase = _mean([r["mase_mean"] for r in rows])
        median_value, _ = _mean([r["mase_median"] for r in rows])
        out.append({"model": model, "level": level, "window": MEAN, "scope": scope,
                    "wape": mean_wape([r["wape"] for r in rows]), "mae": mae_value,
                    "bias": bias_value, "mase_mean": mase_value, "mase_median": median_value,
                    "relmae": None if model == REFERENCE
                    else mean_relmae([r["relmae"] for r in rows]),
                    "n_folds_wape": sum(r["wape"] is not None for r in rows),
                    "n_folds_mae": n_mae, "n_folds_bias": n_bias, "n_folds_mase": n_mase})
    return out


def level_scores(folds: Sequence[WindowScores], holdout: WindowScores | None,
                 candidate: str) -> dict[str, LevelScores]:
    """Gate inputs for one candidate (section 8)."""
    return {level: LevelScores([fold.gate[candidate][level] for fold in folds],
                               holdout.gate[candidate][level] if holdout else None)
            for level in LEVELS}
