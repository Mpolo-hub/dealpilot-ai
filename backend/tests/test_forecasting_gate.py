"""Spec 003 acceptance gate on hand-made metric tables (AC-FC-15, plus the gate part of 22).

Baseline fold WAPE is 0.5. A winning candidate has fold WAPE 0.475 (exactly a 5%
improvement in float64) and fold RelMAE 0.85, unless a case says otherwise.
"""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from dealpilot.forecasting.gate import (
    LevelScores,
    WindowScore,
    evaluate_gate,
    mean_relmae,
    mean_wape,
)
from dealpilot.forecasting.metrics import relmae
from dealpilot.forecasting.series import LEVELS
from dealpilot.forecasting.split import ForecastingError

WIN = WindowScore(wape_candidate=0.475, wape_baseline=0.5, relmae=0.85)
HOLDOUT = WindowScore(wape_candidate=0.45, wape_baseline=0.5, relmae=0.9)
BAD = WindowScore(9.0, 0.1, 9.0)  # only ever used in the `all` scope


def _scope(open_score: WindowScore) -> dict[str, WindowScore]:
    return {"open": open_score, "all": BAD}


def _level(folds=None, holdout=HOLDOUT) -> LevelScores:
    folds = folds or [WIN] * 13
    return LevelScores([_scope(f) for f in folds],
                       None if holdout is None else _scope(holdout))


def _gate(overrides: dict | None = None, run_class="formal", stage="holdout"):
    levels = {level: _level() for level in LEVELS}
    levels.update(overrides or {})
    return evaluate_gate(levels, run_class, stage)


def test_ac_fc_15_all_conditions_at_all_levels_pass() -> None:
    result = _gate()
    assert result.accepted and result.decision == "pass"
    for verdict in result.levels.values():
        assert verdict.conditions == {1: True, 2: True, 3: True, 4: True}
        assert verdict.wins == 13


FAILING_LEVEL = {
    1: _level(folds=[replace(WIN, wape_candidate=0.48)] * 13),  # 4% improvement
    2: _level(folds=[replace(WIN, relmae=0.96)] * 13),  # still won (0.96 < 1)
    3: _level(folds=[WIN] * 9 + [replace(WIN, relmae=1.0)] * 4),  # 9 wins
    4: _level(holdout=replace(HOLDOUT, wape_candidate=0.55)),
}


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("condition", [1, 2, 3, 4])
def test_ac_fc_15_single_condition_failing_at_single_level(level: str, condition: int) -> None:
    result = _gate({level: FAILING_LEVEL[condition]})
    assert not result.accepted and result.decision == "fail"
    failed = {lv: [c for c, ok in v.conditions.items() if not ok]
              for lv, v in result.levels.items()}
    assert failed == {lv: ([condition] if lv == level else []) for lv in LEVELS}


def test_ac_fc_15_thresholds_are_inclusive() -> None:
    exact = WindowScore(wape_candidate=0.475, wape_baseline=0.5, relmae=0.95)
    result = _gate({level: _level(folds=[exact] * 13) for level in LEVELS})
    verdict = result.levels["total"]
    assert 1 - verdict.mean_wape_candidate / verdict.mean_wape_baseline >= 0.05
    assert verdict.mean_relmae == 0.95
    assert result.decision == "pass"


def test_ac_fc_15_zero_baseline_wape_fails_condition_1() -> None:
    zero = WindowScore(wape_candidate=0.0, wape_baseline=0.0, relmae=0.85)
    verdict = _gate({"total": _level(folds=[zero] * 13)}).levels["total"]
    assert verdict.conditions[1] is False


def test_ac_fc_15_null_folds_are_lost_out_of_13() -> None:
    null_wape = WindowScore(None, None, 0.85)
    null_rel = replace(WIN, relmae=None)
    ten = _gate({"total": _level(folds=[WIN] * 10 + [null_wape] * 2 + [null_rel])})
    assert ten.levels["total"].wins == 10 and ten.levels["total"].conditions[3]
    nine = _gate({"total": _level(folds=[WIN] * 9 + [null_wape] * 3 + [null_rel])})
    assert nine.levels["total"].wins == 9 and not nine.levels["total"].conditions[3]


def test_ac_fc_15_two_null_wape_folds_average_the_other_eleven() -> None:
    values = [0.40, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.40, 0.41, 0.42]
    folds = [replace(WIN, wape_candidate=v) for v in values] + [WindowScore(None, None, 0.85)] * 2
    verdict = _gate({"category": _level(folds=folds)}).levels["category"]
    assert verdict.mean_wape_candidate == math.fsum(values) / 11  # never null as 0
    assert verdict.mean_wape_baseline == 0.5
    assert verdict.wins == 11  # counted out of 13
    assert mean_wape([None, None]) is None and mean_relmae([None]) is None


def test_ac_fc_15_tied_fold_is_not_won() -> None:
    tie = replace(WIN, wape_candidate=0.5)
    verdict = _gate({"total": _level(folds=[WIN] * 9 + [tie] * 4)}).levels["total"]
    assert verdict.wins == 9 and not verdict.conditions[3]


@pytest.mark.parametrize("holdout", [
    replace(HOLDOUT, wape_candidate=None), replace(HOLDOUT, wape_baseline=None),
    replace(HOLDOUT, relmae=None), replace(HOLDOUT, relmae=1.01),
])
def test_ac_fc_15_null_or_worse_holdout_fails(holdout: WindowScore) -> None:
    result = _gate({"product_region": _level(holdout=holdout)})
    assert not result.levels["product_region"].conditions[4] and result.decision == "fail"


def test_ac_fc_15_holdout_bounds_are_inclusive() -> None:
    equal = WindowScore(wape_candidate=0.5, wape_baseline=0.5, relmae=1.0)
    assert _gate({"total": _level(holdout=equal)}).decision == "pass"


def test_ac_fc_15_formal_backtest_pass_is_not_decided() -> None:
    levels = {level: _level(holdout=None) for level in LEVELS}
    result = evaluate_gate(levels, "formal", "backtest")
    assert result.decision == "not decided" and not result.accepted
    levels["total"] = replace(FAILING_LEVEL[2], holdout=None)
    assert evaluate_gate(levels, "formal", "backtest").decision == "fail"


@pytest.mark.parametrize("stage", ["backtest", "holdout"])
def test_ac_fc_15_exploratory_run_is_not_decided(stage: str) -> None:
    assert _gate(run_class="exploratory", stage=stage).decision == "not decided"
    assert _gate({"total": FAILING_LEVEL[1]}, "exploratory", stage).decision == "not decided"


def test_ac_fc_15_counters_do_not_change_the_verdict() -> None:
    plain = relmae([2.0, 3.0], [4.0, 4.0], [True, True])
    padded = relmae([2.0, 3.0, 1.0, 0.0, 0.0], [4.0, 4.0, 0.0, 1.0, 0.0], [True] * 5)
    assert (padded.n_base_perfect, padded.n_cand_perfect, padded.n_tie) == (1, 1, 1)
    results = [
        _gate({"total": _level(folds=[replace(WIN, relmae=r.value)] * 13)})
        for r in (plain, padded)
    ]
    assert results[0] == results[1] and results[0].decision == "pass"


def test_ac_fc_22_gate_reads_only_open_scope() -> None:
    base = _gate()
    levels = {level: _level() for level in LEVELS}
    for scores in levels.values():
        for fold in scores.folds:
            fold["all"] = WindowScore(0.0, 1.0, 0.0001)
    assert evaluate_gate(levels, "formal", "holdout") == base


def test_ac_fc_15_bad_inputs_are_refused() -> None:
    with pytest.raises(ForecastingError, match="13 folds"):
        _gate({"total": _level(folds=[WIN] * 12)})
    with pytest.raises(ForecastingError, match="levels"):
        evaluate_gate({"total": _level()}, "formal", "holdout")
    with pytest.raises(ForecastingError):
        _gate(run_class="informal")
