"""Spec 003 baselines on hand-made series (AC-FC-04, AC-FC-05)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from dealpilot.forecasting.baselines import NAIVE, SEASONAL_NAIVE, naive, seasonal_naive
from dealpilot.forecasting.split import ForecastingError


def _history(start: date, cutoff: date) -> np.ndarray:
    """Distinct values: day i holds 1000 + i, closed days included."""
    return 1000.0 + np.arange((cutoff - start).days + 1)


def _value(history: np.ndarray, start: date, day: date) -> float:
    return history[(day - start).days]


def test_ac_fc_04_weekly_repeat() -> None:
    start, cutoff = date(2023, 2, 1), date(2023, 3, 16)  # no closed day nearby
    y = _history(start, cutoff)
    result = seasonal_naive(y, start, cutoff, 28)
    expected = [_value(y, start, cutoff - timedelta(days=6) + timedelta(days=(h - 1) % 7))
                for h in range(1, 29)]
    assert result.values.tolist() == expected
    assert result.values[0] == _value(y, start, cutoff - timedelta(days=6))  # lag 7
    assert result.values[6] == _value(y, start, cutoff)  # day c + 7 gets y(c)
    assert result.values[7] == result.values[0]  # day c + 8 again gets y(c - 6)
    assert result.zero_fallback_count == 0


def test_ac_fc_04_closed_source_uses_lag_14() -> None:
    start, cutoff = date(2023, 11, 1), date(2023, 12, 27)  # source week Dec 21 to 27
    y = _history(start, cutoff)
    result = seasonal_naive(y, start, cutoff, 28)
    h = (date(2023, 12, 25) - (cutoff - timedelta(days=6))).days + 1  # Dec 25 is closed
    for k in range(h, 29, 7):
        assert result.values[k - 1] == _value(y, start, date(2023, 12, 18))
    assert result.zero_fallback_count == 0


def test_ac_fc_04_closed_lag_14_uses_lag_21() -> None:
    start, cutoff = date(2023, 11, 1), date(2024, 1, 3)  # source week Dec 28 to Jan 3
    y = _history(start, cutoff)
    result = seasonal_naive(y, start, cutoff, 28)
    h = (date(2024, 1, 1) - (cutoff - timedelta(days=6))).days + 1  # Jan 1 closed, Dec 25 too
    for k in range(h, 29, 7):
        assert result.values[k - 1] == _value(y, start, date(2023, 12, 18))


def test_ac_fc_04_no_open_source_gives_zero_and_counts_it() -> None:
    start, cutoff = date(2023, 1, 1), date(2023, 1, 7)  # Sunday source 2023-01-01 is closed
    y = _history(start, cutoff)
    week = seasonal_naive(y, start, cutoff, 7)
    assert week.values[0] == 0  # the Sunday forecast (c + 1 = 2023-01-08)
    assert week.values[1:].tolist() == y[1:].tolist()
    assert week.zero_fallback_count == 1
    month = seasonal_naive(y, start, cutoff, 28)
    assert month.zero_fallback_count == 4  # one per affected forecast value
    assert month.values[[0, 7, 14, 21]].tolist() == [0, 0, 0, 0]


def test_ac_fc_05_naive_repeats_cutoff_value() -> None:
    start, cutoff = date(2023, 2, 1), date(2023, 3, 16)
    y = _history(start, cutoff)
    assert naive(y, start, cutoff, 28).values.tolist() == [y[-1]] * 28


def test_ac_fc_05_closed_cutoff_day_gives_zero() -> None:
    start, cutoff = date(2023, 11, 1), date(2023, 12, 25)
    y = _history(start, cutoff)
    y[-1] = 0  # no sales on the closed day
    result = naive(y, start, cutoff, 6)
    assert result.values.tolist() == [0.0] * 6
    assert result.zero_fallback_count == 0


@pytest.mark.parametrize("model", [seasonal_naive, naive])
def test_ac_fc_04_05_history_must_end_at_cutoff(model) -> None:
    start, cutoff = date(2023, 2, 1), date(2023, 3, 16)
    with pytest.raises(ForecastingError):
        model(_history(start, cutoff)[:-1], start, cutoff, 28)  # one day short
    with pytest.raises(ForecastingError):
        model(_history(start, cutoff), start, cutoff, 0)


def test_ac_fc_04_05_model_declarations() -> None:
    assert (SEASONAL_NAIVE.name, SEASONAL_NAIVE.version, SEASONAL_NAIVE.settings) == (
        "seasonal_naive", "1.0", {"lag_days": 7, "closed_day_fallback": "weekly"})
    assert SEASONAL_NAIVE.uses_holiday_calendar and not SEASONAL_NAIVE.uses_planned_promotions
    assert (NAIVE.name, NAIVE.version, NAIVE.settings) == ("naive", "1.0", {})
    assert not NAIVE.uses_holiday_calendar and not NAIVE.uses_planned_promotions
