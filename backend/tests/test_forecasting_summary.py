"""
Exploratory backtest summary shown on the Prediction page (spec 007 D14 amendment,
2026-11-04; spec 003 section 9.5 exploratory runs).

The committed `frontend/src/evaluation/exploratory-backtest.json` must equal the summary of a
fresh exploratory backtest of the seed-42 data run by the spec 003 harness, apart from the
run identity (`run_id`, `created_at`). So no number on the page can drift from, or be
invented apart from, what the harness produces.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dealpilot.analytics.dataset import find_project_root
from dealpilot.forecasting import evaluate as ev
from dealpilot.forecasting.split import ForecastingError
from dealpilot.forecasting.summary import LABEL, main, summarize

COMMITTED = find_project_root() / "frontend" / "src" / "evaluation" / "exploratory-backtest.json"
IDENTITY = ("run_id", "created_at")


@pytest.fixture(scope="module")
def fresh(generated_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    results = tmp_path_factory.mktemp("results")
    return ev.run_backtest(generated_dir, results, signal=False, echo=lambda _: None).folder


def test_committed_summary_matches_a_fresh_exploratory_run(fresh: Path) -> None:
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    summary = summarize(fresh)
    for field in IDENTITY:
        committed.pop(field)
        summary.pop(field)
    assert committed == summary


def test_summary_is_labelled_exploratory_and_has_13_fold_means(fresh: Path) -> None:
    summary = summarize(fresh)
    assert summary["label"] == LABEL == "Exploratory backtest, not a formal evaluation"
    assert (summary["run_class"], summary["decision_grade"], summary["decision"]) == (
        "exploratory", False, "not decided")
    assert summary["folds"] == 13 and summary["window"] == "mean" and summary["scope"] == "open"
    assert len(summary["metrics"]) == 6
    for row in summary["metrics"]:
        assert row["n_folds_wape"] == 13 and row["wape"] is not None
        assert (row["relmae"] is None) == (row["model"] == "seasonal_naive")  # the reference
    assert "holdout" not in json.dumps(summary)


@pytest.mark.parametrize("change", [{"run_class": "formal"}, {"stage": "holdout"},
                                    {"decision_grade": True}])
def test_summary_refuses_formal_or_holdout_runs(fresh: Path, tmp_path: Path, change) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    record = json.loads((fresh / "run.json").read_text(encoding="utf-8"))
    record.update(change)
    (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")
    (folder / "metrics.csv").write_bytes((fresh / "metrics.csv").read_bytes())
    with pytest.raises(ForecastingError):
        summarize(folder)
    assert main([str(folder), str(tmp_path / "out.json")]) == 1
    assert not (tmp_path / "out.json").exists()
