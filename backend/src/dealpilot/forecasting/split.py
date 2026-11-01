"""Business calendar and time split (spec 003 sections 5.1, 5.2 and 6.3).

Everything here depends only on the dataset `start` and `end`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

# D17: fixed business-calendar constants, matching spec 001 section 5.7. The module never
# reads metadata.json `parameters`.
CLOSED_DAYS = ((12, 25), (1, 1))  # (month, day)
MIN_DAYS, MAX_DAYS = 730, 1096  # A2, counting both ends
HOLDOUT_DAYS = 90
FOLD_DAYS = 28
N_FOLDS = 13
HOLDOUT_HORIZONS = (28, 28, 28, 6)  # D6


class ForecastingError(ValueError):
    """An input breaks a spec 003 rule."""


def is_open(day: date) -> bool:
    return (day.month, day.day) not in CLOSED_DAYS


def date_range(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def open_mask(days: list[date]) -> np.ndarray:
    """True for open days, in the order given."""
    return np.array([is_open(d) for d in days], dtype=bool)


@dataclass(frozen=True)
class Window:
    """One forecast origin: train on `start`..`cutoff`, score `first`..`last`."""
    index: int  # fold number in time order (1 to 13), or holdout origin (1 to 4)
    cutoff: date
    horizon: int

    @property
    def first(self) -> date:
        return self.cutoff + timedelta(days=1)

    @property
    def last(self) -> date:
        return self.cutoff + timedelta(days=self.horizon)


@dataclass(frozen=True)
class TimeSplit:
    start: date
    end: date
    holdout_cutoff: date  # H = E - 90
    folds: tuple[Window, ...]  # 13 backtest folds, fold 1 first (k = 13)
    holdout_origins: tuple[Window, ...]  # 4 sequential holdout origins

    @property
    def holdout_first(self) -> date:
        return self.holdout_cutoff + timedelta(days=1)


def make_split(start: date, end: date) -> TimeSplit:
    """Section 5.1 for any valid spec 001 range (730 to 1096 days)."""
    n_days = (end - start).days + 1
    if not MIN_DAYS <= n_days <= MAX_DAYS:
        raise ForecastingError(
            f"the range has {n_days} days; it must be {MIN_DAYS} to {MAX_DAYS} days")
    h = end - timedelta(days=HOLDOUT_DAYS)
    folds = tuple(Window(N_FOLDS + 1 - k, h - timedelta(days=FOLD_DAYS * k), FOLD_DAYS)
                  for k in range(N_FOLDS, 0, -1))
    origins, cutoff = [], h
    for i, horizon in enumerate(HOLDOUT_HORIZONS, start=1):
        origins.append(Window(i, cutoff, horizon))
        cutoff += timedelta(days=horizon)
    return TimeSplit(start, end, h, folds, tuple(origins))
