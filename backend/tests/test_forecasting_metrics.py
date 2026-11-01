"""Spec 003 metrics on hand-made arrays (AC-FC-08, 09, 10, 18, 21, 22).

Expected values are worked out by hand from the section 7 formulas.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from dealpilot.forecasting.gate import WindowScore, fold_won
from dealpilot.forecasting.metrics import (
    SCOPES,
    bias,
    is_active_in_window,
    is_inactive,
    mae,
    mase,
    mase_scale,
    relmae,
    scope_mask,
    series_mae,
    wape,
    window_metrics,
)
from dealpilot.forecasting.split import ForecastingError

# Window Dec 23 to 27, 2024: day index 2 (Dec 25) is closed.
DAYS = [date(2024, 12, 23) + timedelta(days=i) for i in range(5)]
OPEN = scope_mask(DAYS, "open")
ALL = scope_mask(DAYS, "all")
A = np.array([[10, 20, 0, 30, 40]])
F = np.array([[12, 18, 4, 30, 36]])  # |F - A| = 2, 2, 4, 0, 4; F - A = 2, -2, 4, 0, -4


def test_ac_fc_22_scope_masks() -> None:
    assert OPEN.tolist() == [True, True, False, True, True]
    assert ALL.tolist() == [True] * 5
    with pytest.raises(ForecastingError):
        scope_mask(DAYS, "weekdays")


def test_ac_fc_08_wape_known_values() -> None:
    assert wape(F, A, OPEN) == 8 / 100
    assert wape(F, A, ALL) == 12 / 100  # the closed day changes `all`, not `open`


def test_ac_fc_08_wape_perfect_and_null() -> None:
    assert wape(A, A, OPEN) == 0 and wape(A, A, ALL) == 0
    zeros = np.zeros((2, 5))
    assert wape(F.repeat(2, axis=0), zeros, OPEN) is None
    assert wape(F.repeat(2, axis=0), zeros, ALL) is None


def test_ac_fc_08_wape_is_pooled_over_series() -> None:
    a = np.array([[10, 10, 0, 10, 10], [0, 0, 0, 0, 100]])
    f = np.array([[20, 10, 0, 10, 10], [0, 0, 0, 0, 50]])
    assert wape(f, a, OPEN) == (10 + 50) / (40 + 100)  # not the mean of 0.25 and 0.5


def test_ac_fc_10_mae_and_bias() -> None:
    assert mae(F, A, OPEN) == 8 / 4
    assert mae(F, A, ALL) == 12 / 5
    assert bias(F, A, OPEN) == -4 / 100
    assert bias(F, A, ALL) == 0 / 100
    zeros = np.zeros((1, 5))
    assert bias(F, zeros, OPEN) is None and bias(F, zeros, ALL) is None
    assert mae(F, zeros, OPEN) == (12 + 18 + 30 + 36) / 4  # MAE is never null


def test_ac_fc_08_10_shape_mismatch_is_refused() -> None:
    with pytest.raises(ForecastingError):
        wape(F, A[:, :4], OPEN)
    with pytest.raises(ForecastingError):
        mae(F[0], A[0], OPEN)


# --------------------------------------------------------------------------- MASE

MASE_START = date(2024, 12, 18)  # index 7 = Dec 25, index 14 = Jan 1 (both closed)
MASE_TRAIN = [10, 12, 9, 11, 10, 13, 8, 50, 14, 10, 12, 10, 16, 7, 60, 11]


def test_ac_fc_09_scale_leaves_out_closed_pairs() -> None:
    # Pairs (t, t-7): (7,0) t closed and (14,7) both closed are left out. The rest:
    # |14-12| + |10-9| + |12-11| + |10-10| + |16-13| + |7-8| + |11-14| = 11 over 7 pairs.
    assert mase_scale(MASE_TRAIN, MASE_START) == 11 / 7


def test_ac_fc_09_zero_scale_is_null() -> None:
    assert mase_scale([5] * 20, date(2024, 3, 1)) is None
    assert mase_scale([5] * 7, date(2024, 3, 1)) is None  # no pair with t - 7 >= start


def test_ac_fc_09_mase_known_value_and_level_mean_median() -> None:
    a = np.array([[10, 10, 0, 10, 10], [10, 10, 0, 10, 10], [10, 10, 0, 10, 10],
                  [10, 10, 0, 10, 10]])
    f = np.array([[12, 10, 9, 10, 10], [10, 14, 0, 10, 10], [10, 10, 0, 16, 10],
                  [99, 99, 0, 99, 99]])
    # open-day MAE per series: 0.5, 1.0, 1.5, 89; scales 2.0, null, 0.5, 1.0.
    eligible = np.array([True, True, True, False])  # series 4 is inactive
    mean, med = mase(f, a, OPEN, [2.0, None, 0.5, 1.0], eligible)
    assert (mean, med) == ((0.25 + 3.0) / 2, (0.25 + 3.0) / 2)
    mean3, med3 = mase(f, a, OPEN, [2.0, 4.0, 0.5, 1.0], np.array([True] * 3 + [False]))
    assert mean3 == (0.25 + 0.25 + 3.0) / 3 and med3 == 0.25
    assert mase(f, a, OPEN, [None] * 4, np.ones(4, dtype=bool)) == (None, None)


# --------------------------------------------------------------------------- RelMAE

def test_ac_fc_18_a_both_errors_positive() -> None:
    r = relmae([2.0, 3.0], [4.0, 1.0], [True, True])
    assert r.value == math.exp((math.log(0.5) + math.log(3.0)) / 2)
    assert r.value == pytest.approx(math.sqrt(1.5))
    assert (r.n_included, r.n_base_perfect, r.n_cand_perfect, r.n_tie) == (2, 0, 0, 0)


@pytest.mark.parametrize(("c", "b", "counter"), [
    (1.0, 0.0, "n_base_perfect"),  # (b) baseline perfect: candidate loss
    (0.0, 1.0, "n_cand_perfect"),  # (c) candidate perfect: candidate win
    (0.0, 0.0, "n_tie"),  # (d) tie
])
def test_ac_fc_18_bcd_left_out_and_counted(c: float, b: float, counter: str) -> None:
    base = relmae([2.0, 3.0], [4.0, 1.0], [True, True])
    more = relmae([2.0, 3.0, c], [4.0, 1.0, b], [True, True, True])
    assert more.value == base.value  # adding the series does not change RelMAE
    assert getattr(more, counter) == 1
    assert more.n_included == 2


def test_ac_fc_18_only_bcd_series_is_null_and_not_won() -> None:
    r = relmae([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [True, True, True])
    assert r.value is None
    assert (r.n_base_perfect, r.n_cand_perfect, r.n_tie) == (1, 1, 1)
    assert not fold_won(WindowScore(0.1, 0.5, r.value))


def test_ac_fc_18_many_candidate_perfect_series_do_not_win_the_fold() -> None:
    r = relmae([2.0] + [0.0] * 20, [2.0] + [1.0] * 20, [True] * 21)
    assert r.value == 1.0 and r.n_cand_perfect == 20
    assert not fold_won(WindowScore(0.1, 0.5, r.value))  # RelMAE >= 1


def test_ac_fc_18_total_level_relmae_equals_wape_ratio() -> None:
    actual = np.array([[100, 120, 0, 90, 110]])
    candidate = np.array([[95, 125, 7, 99, 100]])
    baseline = np.array([[80, 140, 0, 70, 130]])
    r = relmae(series_mae(candidate, actual, OPEN), series_mae(baseline, actual, OPEN), [True])
    ratio = wape(candidate, actual, OPEN) / wape(baseline, actual, OPEN)
    assert r.value == pytest.approx(ratio, rel=1e-12)


def test_ac_fc_18_mismatched_arrays_are_refused() -> None:
    with pytest.raises(ForecastingError):
        relmae([1.0, 2.0], [1.0], [True, True])


# --------------------------------------------------------------------------- inactive

def test_ac_fc_21_inactive_series_excluded_but_errors_count() -> None:
    first, last = DAYS[0], DAYS[-1]
    lifecycle = [(date(2023, 1, 1), None), (date(2023, 1, 1), date(2024, 6, 1))]  # 2nd stopped
    eligible = np.array([not is_inactive([p], first, last) for p in lifecycle])
    assert eligible.tolist() == [True, False]
    a = np.array([[10, 10, 0, 10, 10], [0, 0, 0, 0, 0]])
    f = np.array([[12, 10, 0, 10, 10], [5, 0, 0, 0, 0]])  # a forecast on the inactive one
    base = np.array([[14, 10, 0, 10, 10], [0, 0, 0, 0, 0]])
    r = relmae(series_mae(f, a, OPEN), series_mae(base, a, OPEN), eligible)
    assert r.n_inactive == 1 and r.n_included == 1 and r.n_base_perfect == 0
    assert r.value == 0.5 / 1.0
    assert mase(f, a, OPEN, [1.0, 1.0], eligible) == (0.5, 0.5)
    assert wape(f, a, OPEN) == (2 + 5) / 40  # its error still counts in WAPE


@pytest.mark.parametrize(("launch", "stop", "active"), [
    ("2024-12-27", None, True),  # launches on the last day
    ("2024-12-28", None, False),  # launches after the window
    ("2023-01-01", "2024-12-23", False),  # first day no longer sold = first window day
    ("2023-01-01", "2024-12-24", True),  # still sold on the first day
])
def test_ac_fc_21_active_in_window_edges(launch: str, stop: str | None, active: bool) -> None:
    stop_date = date.fromisoformat(stop) if stop else None
    assert is_active_in_window(date.fromisoformat(launch), stop_date, DAYS[0], DAYS[-1]) is active


def test_ac_fc_21_aggregate_inactive_only_if_every_product_is() -> None:
    gone = (date(2023, 1, 1), date(2024, 1, 1))
    live = (date(2023, 1, 1), None)
    assert is_inactive([gone, gone], DAYS[0], DAYS[-1])
    assert not is_inactive([gone, live], DAYS[0], DAYS[-1])


# --------------------------------------------------------------------------- day scopes

def test_ac_fc_22_every_metric_for_both_scopes() -> None:
    m = window_metrics(F, A, DAYS)
    assert tuple(m) == SCOPES == ("open", "all")
    assert (m["open"].wape, m["open"].mae, m["open"].bias) == (0.08, 2.0, -0.04)
    assert (m["all"].wape, m["all"].mae, m["all"].bias) == (0.12, 2.4, 0.0)


def test_ac_fc_22_closed_day_error_changes_all_only() -> None:
    before = window_metrics(A, A, DAYS)
    f = A.copy()
    f[0, 2] = 25  # error on the closed day only
    after = window_metrics(f, A, DAYS)
    assert after["open"] == before["open"]
    assert after["all"] != before["all"]
    r_open = relmae(series_mae(f, A, OPEN), series_mae(F, A, OPEN), [True])
    assert r_open.n_cand_perfect == 1  # on open days the candidate is still perfect


# --------------------------------------------------------------------------- D25, D26

CLOSED_ONLY = [date(2024, 12, 25), date(2025, 1, 1)]  # a fully closed scope (hand-made)


def test_ac_fc_10_fully_closed_mask_is_empty() -> None:
    assert scope_mask(CLOSED_ONLY, "open").tolist() == [False, False]


def test_ac_fc_10_mae_empty_scope_is_refused() -> None:
    mask = scope_mask(CLOSED_ONLY, "open")
    with pytest.raises(ForecastingError, match="empty scope"):
        mae(np.array([[1, 2]]), np.array([[1, 1]]), mask)
    with pytest.raises(ForecastingError, match="empty scope"):
        mae(np.zeros((0, 5)), np.zeros((0, 5)), OPEN)  # no series at all


def test_ac_fc_10_series_mae_empty_scope_is_refused() -> None:
    mask = scope_mask(CLOSED_ONLY, "open")
    with pytest.raises(ForecastingError, match="empty scope"):
        series_mae(np.array([[1, 2]]), np.array([[1, 1]]), mask)


def test_ac_fc_09_mase_empty_scope_is_refused() -> None:
    mask = scope_mask(CLOSED_ONLY, "open")
    with pytest.raises(ForecastingError, match="empty scope"):
        mase(np.array([[1, 2]]), np.array([[1, 1]]), mask, [1.0], np.array([True]))


def test_ac_fc_09_no_usable_pair_gives_null_scale_and_mase() -> None:
    """D25: a 7-day history has no pair with t - 7 >= start."""
    scale = mase_scale([3, 1, 4, 1, 5, 9, 2], date(2024, 3, 1))
    assert scale is None
    assert mase(F, A, OPEN, [scale], np.array([True])) == (None, None)


@pytest.mark.parametrize(("c", "b"), [
    ([float("nan"), 1.0], [1.0, 1.0]),
    ([1.0, 1.0], [1.0, float("nan")]),
    ([float("inf"), 1.0], [1.0, 1.0]),
    ([1.0, 1.0], [float("-inf"), 1.0]),
])
def test_ac_fc_18_relmae_refuses_non_finite(c, b) -> None:
    with pytest.raises(ForecastingError, match="finite"):
        relmae(c, b, [True, True])


def test_ac_fc_18_nan_is_never_a_tie() -> None:
    """Before D26 a NaN pair fell through to the tie branch."""
    with pytest.raises(ForecastingError):
        relmae([float("nan")], [float("nan")], [True])


def test_ac_fc_22_all_closed_window_metrics_are_refused() -> None:
    with pytest.raises(ForecastingError, match="empty scope"):
        window_metrics(np.array([[1, 2]]), np.array([[1, 1]]), CLOSED_ONLY)


def test_ac_fc_10_normal_values_unchanged_after_d26() -> None:
    assert (mae(F, A, OPEN), mae(F, A, ALL)) == (2.0, 2.4)
    assert series_mae(F, A, OPEN).tolist() == [2.0]
    r = relmae([2.0, 2.0, 0.0, 0.0], [2.0, 0.0, 1.0, 0.0], [True] * 4)
    assert (r.value, r.n_base_perfect, r.n_cand_perfect, r.n_tie) == (1.0, 1, 1, 1)
    assert not fold_won(WindowScore(0.4, 0.5, r.value))  # exactly 1 is not a win
    assert fold_won(WindowScore(0.4, 0.5, math.nextafter(1.0, 0.0)))
