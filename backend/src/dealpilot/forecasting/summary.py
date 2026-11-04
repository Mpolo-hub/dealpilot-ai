"""Exploratory backtest summary for the Prediction page (spec 007 D14 amendment, 2026-11-04).

Reads one finished exploratory backtest folder written by the spec 003 harness
(`python -m dealpilot.forecasting.evaluate backtest`) and keeps only what the page shows:
the 13-fold means (section 7.5) on open days for both baselines and the three levels, with
the run's provenance. It copies the harness numbers; it computes no metric of its own.

    python -m dealpilot.forecasting.summary <run folder> <output.json>

A formal run, a holdout run or a decision-grade run is refused: the page shows exploratory
results only, and never holdout results.
"""
from __future__ import annotations

import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dealpilot.forecasting.inputs import data_hash
from dealpilot.forecasting.split import ForecastingError

LABEL = "Exploratory backtest, not a formal evaluation"
SCOPE = "open"
MODELS = ("seasonal_naive", "naive")
LEVELS = ("total", "category", "product_region")
_FLOAT_FIELDS = ("wape", "mae", "bias", "mase_mean", "mase_median", "relmae")
_INT_FIELDS = ("n_folds_wape", "n_folds_mae", "n_folds_bias", "n_folds_mase")


def _number(text: str, kind: type) -> float | int | None:
    return None if text == "" else kind(text)


def summarize(folder: Path) -> dict:
    record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    if (record.get("stage") != "backtest" or record.get("run_class") != "exploratory"
            or record.get("decision_grade") is not False):
        raise ForecastingError("only an exploratory backtest run can be summarized")
    with (folder / "metrics.csv").open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle)
                if r["window"] == "mean" and r["scope"] == SCOPE]
    metrics = []
    for model in MODELS:
        for level in LEVELS:
            match = [r for r in rows if r["model"] == model and r["level"] == level]
            if len(match) != 1:
                raise ForecastingError(f"no mean {SCOPE} row for {model} {level}")
            row = {"model": model, "level": level}
            row.update({f: _number(match[0][f], float) for f in _FLOAT_FIELDS})
            row.update({f: _number(match[0][f], int) for f in _INT_FIELDS})
            metrics.append(row)
    folds = record["calendar"]["folds"]
    data = record["data"]
    return {
        "label": LABEL,
        "run_id": record["run_id"],
        "created_at": record["created_at"],
        "spec": "003",
        "stage": "backtest",
        "run_class": "exploratory",
        "decision_grade": False,
        "decision": record["decision"]["value"],
        "scope": SCOPE,
        "window": "mean",
        "folds": len(folds),
        "fold_horizon_days": folds[0]["horizon"],
        "first_cutoff": folds[0]["cutoff"],
        "last_cutoff": folds[-1]["cutoff"],
        "data": {"seed": data["seed"], "start": data["start"], "end": data["end"],
                 "generator_version": data["generator_version"],
                 "data_hash": data_hash(data["files"])},
        "models": [{k: m[k] for k in ("name", "version")} for m in record["models"]],
        "metrics": metrics,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m dealpilot.forecasting.summary <run folder> <output.json>",
              file=sys.stderr)
        return 2
    try:
        summary = summarize(Path(args[0]))
    except (ForecastingError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    text = json.dumps(summary, indent=2, sort_keys=False) + "\n"
    Path(args[1]).write_text(text, encoding="utf-8", newline="\n")
    print(f"summary written to {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
