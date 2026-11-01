"""Spec 003 time split (AC-FC-01, AC-FC-02). Dates only: no dataset is read."""
from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import pytest

from dealpilot.forecasting.split import ForecastingError, is_open, make_split

D = date.fromisoformat

# Spec 003 section 5.2, copied from the tables (expected values come from the spec).
DEFAULT_FOLDS = [
    ("2024-10-03", "2024-10-04", "2024-10-31"), ("2024-10-31", "2024-11-01", "2024-11-28"),
    ("2024-11-28", "2024-11-29", "2024-12-26"), ("2024-12-26", "2024-12-27", "2025-01-23"),
    ("2025-01-23", "2025-01-24", "2025-02-20"), ("2025-02-20", "2025-02-21", "2025-03-20"),
    ("2025-03-20", "2025-03-21", "2025-04-17"), ("2025-04-17", "2025-04-18", "2025-05-15"),
    ("2025-05-15", "2025-05-16", "2025-06-12"), ("2025-06-12", "2025-06-13", "2025-07-10"),
    ("2025-07-10", "2025-07-11", "2025-08-07"), ("2025-08-07", "2025-08-08", "2025-09-04"),
    ("2025-09-04", "2025-09-05", "2025-10-02"),
]
DEFAULT_ORIGINS = [
    ("2025-10-02", 28, "2025-10-03", "2025-10-30"), ("2025-10-30", 28, "2025-10-31", "2025-11-27"),
    ("2025-11-27", 28, "2025-11-28", "2025-12-25"), ("2025-12-25", 6, "2025-12-26", "2025-12-31"),
]


def test_ac_fc_01_default_calendar() -> None:
    split = make_split(D("2023-01-01"), D("2025-12-31"))
    assert split.holdout_cutoff == D("2025-10-02")
    assert split.holdout_first == D("2025-10-03")
    assert (split.end - split.holdout_first).days + 1 == 90
    assert [(f.index, f.cutoff, f.first, f.last) for f in split.folds] == [
        (i, D(c), D(a), D(b)) for i, (c, a, b) in enumerate(DEFAULT_FOLDS, start=1)]
    assert all(f.cutoff.weekday() == 3 for f in split.folds)  # every cutoff is a Thursday
    assert [(o.index, o.cutoff, o.horizon, o.first, o.last) for o in split.holdout_origins] == [
        (i, D(c), h, D(a), D(b)) for i, (c, h, a, b) in enumerate(DEFAULT_ORIGINS, start=1)]


@pytest.mark.parametrize(("start", "n_days"), [
    ("2023-01-01", 730), ("2023-01-01", 1096), ("2022-03-15", 730), ("2021-07-04", 1096),
    ("2023-01-01", 900),
])
def test_ac_fc_02_calendar_for_any_valid_range(start: str, n_days: int) -> None:
    first = D(start)
    end = first + timedelta(days=n_days - 1)
    split = make_split(first, end)
    h = split.holdout_cutoff
    assert h == end - timedelta(days=90)
    assert (end - h).days == 90  # holdout is the last 90 days
    cutoffs = [f.cutoff for f in split.folds]
    assert len(cutoffs) == 13
    assert all((b - a).days == 28 for a, b in pairwise(cutoffs))
    for fold, nxt in pairwise(split.folds):
        assert fold.horizon == 28 and (fold.last - fold.first).days == 27
        assert nxt.first == fold.last + timedelta(days=1)  # back to back, no overlap
    assert split.folds[-1].last == h  # the last window ends on the holdout cutoff
    assert all(f.last <= h for f in split.folds)  # none overlaps the holdout
    assert [(o.cutoff, o.horizon) for o in split.holdout_origins] == [
        (h, 28), (h + timedelta(days=28), 28), (h + timedelta(days=56), 28),
        (h + timedelta(days=84), 6)]
    assert split.holdout_origins[-1].last == end
    assert (split.folds[0].cutoff - first).days + 1 >= 276  # training days, earliest fold


@pytest.mark.parametrize("n_days", [729, 1097, 1])
def test_ac_fc_02_invalid_range_is_refused(n_days: int) -> None:
    start = D("2023-01-01")
    with pytest.raises(ForecastingError, match="730 to 1096"):
        make_split(start, start + timedelta(days=n_days - 1))


def test_ac_fc_02_shortest_range_has_exactly_276_training_days() -> None:
    start = D("2023-01-01")
    split = make_split(start, start + timedelta(days=729))
    assert (split.folds[0].cutoff - start).days + 1 == 276


@pytest.mark.parametrize(("day", "open_"), [
    ("2024-12-25", False), ("2025-01-01", False), ("2024-12-24", True), ("2024-12-31", True),
    ("2024-02-29", True),
])
def test_ac_fc_01_holiday_constant(day: str, open_: bool) -> None:
    assert is_open(D(day)) is open_
