"""Fold averages and the acceptance gate (spec 003 sections 7.5 and 8, D9).

The gate compares a candidate with seasonal naive from the same run. It reads only the
`open` day scope, uses unrounded float64 values and inclusive thresholds.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dealpilot.forecasting.series import LEVELS
from dealpilot.forecasting.split import N_FOLDS, ForecastingError

MIN_IMPROVEMENT = 0.05
MAX_RELMAE = 0.95
MIN_WINS = 10
RUN_CLASSES = ("exploratory", "formal")
STAGES = ("backtest", "holdout")


@dataclass(frozen=True)
class WindowScore:
    """Candidate and baseline WAPE and the candidate's RelMAE for one window and scope."""
    wape_candidate: float | None
    wape_baseline: float | None
    relmae: float | None


@dataclass(frozen=True)
class LevelScores:
    """13 backtest folds and the holdout, each as {day scope: WindowScore}."""
    folds: Sequence[Mapping[str, WindowScore]]
    holdout: Mapping[str, WindowScore] | None = None


@dataclass(frozen=True)
class LevelVerdict:
    mean_wape_candidate: float | None
    mean_wape_baseline: float | None
    mean_relmae: float | None
    wins: int
    conditions: dict[int, bool]

    @property
    def passed(self) -> bool:
        return all(self.conditions.values())


@dataclass(frozen=True)
class GateResult:
    levels: dict[str, LevelVerdict]
    accepted: bool  # all four conditions at all three levels
    decision: str  # "pass", "fail" or "not decided"


def mean_wape(values: Sequence[float | None]) -> float | None:
    """Arithmetic mean over WAPE-eligible folds; null is never averaged or read as 0."""
    defined = [v for v in values if v is not None]
    return math.fsum(defined) / len(defined) if defined else None


def mean_relmae(values: Sequence[float | None]) -> float | None:
    """Geometric mean over folds whose RelMAE is not null."""
    defined = [v for v in values if v is not None]
    if not defined:
        return None
    return math.exp(math.fsum(math.log(v) for v in defined) / len(defined))


def fold_won(score: WindowScore) -> bool:
    """Both WAPEs defined, candidate strictly lower, RelMAE defined and strictly below 1."""
    return (score.wape_candidate is not None and score.wape_baseline is not None
            and score.wape_candidate < score.wape_baseline
            and score.relmae is not None and score.relmae < 1)


def holdout_condition(holdout: WindowScore | None) -> bool:
    """Condition 4: holdout WAPE not worse and holdout RelMAE <= 1, both defined."""
    return (holdout is not None and holdout.wape_candidate is not None
            and holdout.wape_baseline is not None and holdout.relmae is not None
            and holdout.wape_candidate <= holdout.wape_baseline and holdout.relmae <= 1)


def level_verdict(scores: LevelScores) -> LevelVerdict:
    if len(scores.folds) != N_FOLDS:
        raise ForecastingError(f"the gate needs exactly {N_FOLDS} folds")
    folds = [fold["open"] for fold in scores.folds]
    w_c = mean_wape([f.wape_candidate for f in folds])
    w_b = mean_wape([f.wape_baseline for f in folds])
    r = mean_relmae([f.relmae for f in folds])
    wins = sum(fold_won(f) for f in folds)  # out of the fixed 13
    holdout = scores.holdout["open"] if scores.holdout is not None else None
    conditions = {
        1: w_c is not None and w_b is not None and w_b > 0
        and 1 - w_c / w_b >= MIN_IMPROVEMENT,
        2: r is not None and r <= MAX_RELMAE,
        3: wins >= MIN_WINS,
        4: holdout_condition(holdout),
    }
    return LevelVerdict(w_c, w_b, r, wins, conditions)


def evaluate_gate(levels: Mapping[str, LevelScores], run_class: str, stage: str) -> GateResult:
    """Verdict per level and the run's `decision` (section 8)."""
    if set(levels) != set(LEVELS):
        raise ForecastingError(f"the gate needs exactly the levels {', '.join(LEVELS)}")
    if run_class not in RUN_CLASSES or stage not in STAGES:
        raise ForecastingError("unknown run class or stage")
    verdicts = {level: level_verdict(levels[level]) for level in LEVELS}
    accepted = all(v.passed for v in verdicts.values())
    backtest_ok = all(v.conditions[c] for v in verdicts.values() for c in (1, 2, 3))
    if run_class == "exploratory":
        decision = "not decided"
    elif stage == "backtest":
        decision = "not decided" if backtest_ok else "fail"
    else:
        decision = "pass" if accepted else "fail"
    return GateResult(verdicts, accepted, decision)
