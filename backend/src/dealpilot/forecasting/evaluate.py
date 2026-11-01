"""Evaluation harness and command line (spec 003 sections 5, 8 and 9; D2).

    python -m dealpilot.forecasting.evaluate backtest [--data-dir data/raw]
        [--results-dir evals/results] [--no-signal-recovery]
    python -m dealpilot.forecasting.evaluate holdout-status

The command line runs exploratory backtests only and reads the holdout log. Formal runs
(`run_backtest` with `formal=`, and `run_holdout`) need a candidate model, a commit, a
CLEAN clean-tree result and a matching decision seed (section 9.5); they are Python calls,
each under its own authorization. A CLEAN result alone never allows a formal run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dealpilot import __version__
from dealpilot.analytics.dataset import find_project_root
from dealpilot.forecasting import holdout_log as hl
from dealpilot.forecasting import records as rec
from dealpilot.forecasting.engine import (
    BASELINES,
    HOLDOUT,
    REFERENCE,
    Model,
    WindowScores,
    forecast_origins,
    level_scores,
    mean_rows,
    score_window,
    window_name,
)
from dealpilot.forecasting.gate import evaluate_gate, holdout_condition
from dealpilot.forecasting.inputs import (
    A1_FILES,
    EXPECTED_FILE,
    EvalData,
    data_hash,
    parse_data,
    read_files,
    sha256_hex,
)
from dealpilot.forecasting.seed import SeedInputs, check_recorded_seed
from dealpilot.forecasting.series import LEVELS
from dealpilot.forecasting.split import ForecastingError, make_split

RUNTIME_TARGET_SECONDS = 60.0
DEFAULT_RESULTS = Path("evals/results")
DEFAULT_LOG = Path("evals/holdout-log.csv")
LOCK_NAME, HEAD_NAME = "holdout.lock", "holdout-log.head"
_clock = time.perf_counter  # separate so tests can simulate a slow run
_COMMIT = re.compile(r"[0-9a-f]{40}")
_CHECK_ERRORS = (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
                 RuntimeError, LookupError, ArithmeticError, ImportError, MemoryError)


class HoldoutStopped(ForecastingError):
    """A failure from step 4 onward: the holdout is consumed and the lock is kept."""


@dataclass(frozen=True)
class FormalSetup:
    """What a formal run needs besides the candidate (section 9.5)."""
    seed_inputs: SeedInputs
    checker: Callable[[], object]  # returns a clean-tree result (CleanTreeResult-like)
    excluded_seeds: frozenset[int] = frozenset()


@dataclass
class RunResult:
    run_id: str
    folder: Path
    record: dict
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


def default_checker(project_root: Path) -> Callable[[], object]:
    def check():
        from dealpilot.forecasting.cleantree import check_clean_tree  # needs pygit2 only here
        return check_clean_tree(project_root)
    return check


# --------------------------------------------------------------------------- checks

def _models(candidate: Model | None) -> list[Model]:
    models = list(BASELINES) + ([candidate] if candidate is not None else [])
    names = [model.info.name for model in models]
    if len(set(names)) != len(names):
        raise ForecastingError("model names must be unique")
    if REFERENCE not in names:
        raise ForecastingError("seasonal naive must be part of every run")
    for model in models:
        rec.version_key(model.info.version)
        rec.canonical_json(model.info.settings)  # strings, ints, booleans, null only
    return models


def check_git(checker: Callable[[], object]) -> dict:
    """Fail closed: only an explicit CLEAN result with a commit passes (section 9.5)."""
    try:
        result = checker()
    except _CHECK_ERRORS as error:  # anything else propagates: the run never starts either
        raise ForecastingError(f"clean-tree check failed: {type(error).__name__}") from None
    outcome = getattr(result, "outcome", None)
    clean = getattr(result, "clean", None)
    commit = getattr(result, "commit", None)
    if outcome != "CLEAN" or clean is not True:
        reasons = getattr(result, "reasons", ())
        raise ForecastingError(f"the working tree is not verified clean: {outcome} {reasons}")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise ForecastingError("the clean-tree result has no commit")
    provenance = getattr(result, "provenance", None)
    record = provenance() if callable(provenance) else {}
    return {**record, "commit": commit, "clean_tree": True,
            "checker": getattr(result, "checker", None),
            "checker_version": getattr(result, "checker_version", None),
            "libgit2_version": getattr(result, "libgit2_version", None)}


def check_seed(formal: FormalSetup, candidate: Model | None, metadata_seed) -> dict:
    if candidate is None:
        raise ForecastingError("a formal run needs a candidate model")
    inputs = formal.seed_inputs
    if (inputs.name, inputs.version) != (candidate.info.name, candidate.info.version):
        raise ForecastingError("the decision seed inputs name another candidate")
    if inputs.config_sha256 != rec.candidate_config_sha256(candidate.info):
        raise ForecastingError("the decision seed config hash does not match the candidate")
    return check_recorded_seed(inputs, metadata_seed, formal.excluded_seeds)


def _metadata_json(raw: dict[str, bytes]) -> dict:
    """Evaluation-only fields (seed, start, end); observations are not parsed here."""
    try:
        loaded = json.loads(raw["metadata.json"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ForecastingError("metadata.json is not valid UTF-8 JSON") from None
    if not isinstance(loaded, dict):
        raise ForecastingError("metadata.json is not a JSON object")
    return loaded


def _input_names(folder: Path, signal: bool) -> tuple[tuple[str, ...], dict]:
    if not signal:
        return A1_FILES, {"computed": False, "reason": "disabled for this run"}
    if not (folder / EXPECTED_FILE).is_file():
        return A1_FILES, {"computed": False, "reason": f"{EXPECTED_FILE} is missing"}
    return A1_FILES + (EXPECTED_FILE,), {"computed": True}


# --------------------------------------------------------------------------- scoring

def _score_folds(data: EvalData, models: Sequence[Model], signal: bool) -> list[WindowScores]:
    return [score_window(data, window_name(w), forecast_origins(data, models, [w]), signal)
            for w in data.split.folds]


def _diagnostics(windows: Sequence[WindowScores], warnings: list[str]) -> dict:
    zero_fallback: dict[str, int] = {}
    for window in windows:
        for name, count in window.zero_fallback.items():
            zero_fallback[name] = zero_fallback.get(name, 0) + count
    counters: dict = {}
    for window in windows:
        for row in window.metric_rows:
            if row["model"] == REFERENCE or row["scope"] != "open":
                continue
            target = counters.setdefault(row["model"], {}).setdefault(
                row["level"], {"n_tie": 0, "n_base_perfect": 0, "n_cand_perfect": 0})
            for name in target:
                target[name] += row[name]
    return {"zero_fallback_count": zero_fallback,
            "n_inactive": {level: {w.name: w.n_inactive[level] for w in windows}
                           for level in LEVELS},
            "relmae_counters_open": counters,
            "baseline_sanity_warning": next((w for w in warnings if "naive" in w), None),
            "warnings": list(warnings)}


def _sanity_warning(means: list[dict]) -> str | None:
    """Report only: seasonal naive's mean WAPE at the total level should beat naive's."""
    wape = {r["model"]: r["wape"] for r in means
            if r["level"] == "total" and r["scope"] == "open"}
    ours, theirs = wape.get(REFERENCE), wape.get("naive")
    if ours is None or theirs is None or ours < theirs:
        return None
    return "seasonal naive's mean WAPE at the total level is not lower than naive's"


# --------------------------------------------------------------------------- records

def _base_record(project_root: Path, data: EvalData, models, stage: str, run_class: str,
                 data_label: str, signal_record: dict, created, config_sha: str) -> dict:
    record = {
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spec": {"number": "003", "status": rec.spec_status(project_root)},
        "stage": stage, "run_class": run_class,
        "decision_grade": run_class == "formal",
        "config_hash": config_sha,
        "code_version": {"package": __version__},
        "data": {"seed": data.metadata["seed"], "start": data.start.isoformat(),
                 "end": data.end.isoformat(),
                 "generator_version": data.metadata["generator_version"],
                 "folder": data_label, "files": dict(sorted(data.file_hashes.items()))},
        "library_versions": rec.library_versions(),
        "calendar": {
            "holdout_first": data.split.holdout_first.isoformat(),
            "holdout_last": data.end.isoformat(),
            "holdout_cutoff": data.split.holdout_cutoff.isoformat(),
            "holdout_origins": [{"origin": w.index, "cutoff": w.cutoff.isoformat(),
                                 "horizon": w.horizon} for w in data.split.holdout_origins],
            "folds": [{"fold": w.index, "cutoff": w.cutoff.isoformat(),
                       "horizon": w.horizon} for w in data.split.folds]},
        "models": [rec.model_record(m.info) for m in models],
        "levels": {level: len(data.series.keys[level]) for level in LEVELS},
        "signal_recovery": signal_record,
    }
    if run_class == "exploratory":
        record["source_manifest"] = rec.source_manifest(project_root)
    return record


def _decision(gate_result, candidate: str | None) -> dict:
    if gate_result is None:
        return {"value": "not decided", "candidate": candidate, "levels": {}}
    return {"value": gate_result.decision, "candidate": candidate, "levels": {
        level: {"conditions": {str(c): ok for c, ok in v.conditions.items()},
                "mean_wape_candidate": v.mean_wape_candidate,
                "mean_wape_baseline": v.mean_wape_baseline,
                "mean_relmae": v.mean_relmae, "wins": v.wins}
        for level, v in gate_result.levels.items()}}


def _metrics_text(windows: Sequence[WindowScores], means: list[dict]) -> str:
    return rec.csv_text(rec.METRIC_COLUMNS,
                        [r for w in windows for r in w.metric_rows] + means,
                        ("model", "level", "window", "scope"))


def _write_tables(folder: Path, windows: Sequence[WindowScores], means: list[dict]) -> None:
    rec.write_new_file(folder / "metrics.csv", _metrics_text(windows, means))
    rec.write_new_file(folder / "series_metrics.csv", rec.csv_text(
        rec.SERIES_COLUMNS, [r for w in windows for r in w.series_rows],
        ("model", "window", "scope", "product_id", "region_id")))
    rec.write_new_file(folder / "signal_recovery.csv", rec.csv_text(
        rec.SIGNAL_COLUMNS, [r for w in windows for r in w.signal_rows],
        ("model", "level", "window", "scope")))


def _label(data_dir: str | Path, label: str | None) -> str:
    """Spec 002 section 3.7: a relative path as written, never an absolute one."""
    if label is not None:
        return label
    return "<absolute path>" if Path(data_dir).is_absolute() else str(data_dir)


def _project_root(project_root: Path | None) -> Path:
    root = project_root or find_project_root()
    if root is None:
        raise ForecastingError("project root not found")
    return Path(root)


# --------------------------------------------------------------------------- backtest

def run_backtest(data_dir: Path, results_dir: Path, *, candidate: Model | None = None,
                 formal: FormalSetup | None = None, signal: bool = True,
                 project_root: Path | None = None, data_label: str | None = None,
                 echo: Callable[[str], None] = print) -> RunResult:
    """Backtest stage: 13 folds, every model, 3 levels, both day scopes (section 5)."""
    root = _project_root(project_root)
    models = _models(candidate)
    run_class = "formal" if formal is not None else "exploratory"
    git = check_git(formal.checker) if formal is not None else None
    created = rec.utc_now()
    config_sha = rec.config_hash(m.info for m in models)
    names, signal_record = _input_names(Path(data_dir), signal)
    raw = read_files(Path(data_dir), names)
    seed_record = check_seed(formal, candidate, _metadata_json(raw).get("seed")) if formal else None
    data = parse_data(raw, with_expected=signal_record["computed"])

    began = _clock()
    folds = _score_folds(data, models, signal_record["computed"])
    means = mean_rows(folds)
    duration = _clock() - began
    gate_result = None
    if candidate is not None:
        gate_result = evaluate_gate(level_scores(folds, None, candidate.info.name),
                                    run_class, "backtest")
    warnings = [w for w in [_sanity_warning(means)] if w]
    if duration > RUNTIME_TARGET_SECONDS:
        warnings.append(f"backtest took {duration:.1f} s, above the "
                        f"{RUNTIME_TARGET_SECONDS:.0f} s target")

    record = _base_record(root, data, models, "backtest", run_class,
                          _label(data_dir, data_label), signal_record, created, config_sha)
    record["decision"] = _decision(gate_result, candidate.info.name if candidate else None)
    record["diagnostics"] = _diagnostics(folds, warnings)
    if formal is not None:
        record["code_version"].update(commit=git["commit"], clean_tree=True)
        record["git_provenance"] = git
        record["decision_seed"] = seed_record

    folder = rec.create_run_folder(Path(results_dir),
                                   rec.run_id_base(created, "backtest", config_sha))
    record["run_id"] = folder.name
    _write_tables(folder, folds, means)
    rec.write_json_atomic(folder / "run.json", record)
    for warning in warnings:
        echo(f"WARNING: {warning}")
    return RunResult(folder.name, folder, record, duration, warnings)


# --------------------------------------------------------------------------- holdout

@dataclass(frozen=True)
class FormalBacktest:
    """The recorded formal backtest a holdout run relies on (section 5.3, condition 2)."""
    folder: Path
    levels: dict
    library_versions: dict


def _formal_backtest(results_dir: Path, config_sha: str, data_hash_value: str
                     ) -> FormalBacktest | None:
    """A formal backtest run with the same hashes that passed conditions 1 to 3 at every
    level, as recorded in its `run.json`, or None. The record is only a claim: the holdout
    run recomputes it before scoring (`_verify_backtest`)."""
    if not results_dir.is_dir():
        return None
    for folder in sorted(results_dir.iterdir()):
        path = folder / "run.json"
        if "-backtest-" not in folder.name or not path.is_file():
            continue
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            files = run["data"]["files"]
            levels = run["decision"]["levels"]
            same = (run["run_class"] == "formal" and run["stage"] == "backtest"
                    and run["config_hash"] == config_sha
                    and data_hash({n: files[n] for n in A1_FILES}) == data_hash_value)
            passed = set(levels) == set(LEVELS) and all(
                levels[level]["conditions"][c] is True
                for level in LEVELS for c in ("1", "2", "3"))
            versions = dict(run["library_versions"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ForecastingError):
            continue
        if same and passed:
            return FormalBacktest(folder, levels, versions)
    return None


def _check_backtest_reproducible(backtest: FormalBacktest) -> None:
    """Step 3 preconditions of the recomputation, so that a mismatch found after step 4
    can't come from a different environment or a missing file: same library versions
    (section 9.6 promises identical numbers only then) and a recorded `metrics.csv`."""
    if backtest.library_versions != rec.library_versions():
        raise hl.HoldoutRefused("the formal backtest ran with other library versions; "
                                "it can't be recomputed identically")
    if not (backtest.folder / "metrics.csv").is_file():
        raise hl.HoldoutRefused("the formal backtest has no metrics.csv to verify")


def _verify_backtest(data: EvalData, models: Sequence[Model], candidate: str,
                     backtest: FormalBacktest) -> dict:
    """Recompute the 13 folds from the hashed bytes and compare with the record.

    A consistency check against locally editable files, not a proof of trust: it shows the
    recorded pass is what the current code computes on this data. Any difference stops the
    run (after step 4, so the holdout stays consumed and the lock is kept).
    """
    folds = _score_folds(data, models, False)
    means = mean_rows(folds)
    gate_result = evaluate_gate(level_scores(folds, None, candidate), "formal", "backtest")
    recomputed_levels = _decision(gate_result, candidate)["levels"]
    recorded_csv = (backtest.folder / "metrics.csv").read_bytes()
    recomputed_csv = _metrics_text(folds, means).encode("utf-8")
    if recomputed_levels != backtest.levels:
        raise ForecastingError("formal backtest record does not match the recomputation "
                               "(gate values)")
    if recomputed_csv != recorded_csv:
        raise ForecastingError("formal backtest record does not match the recomputation "
                               "(metrics.csv)")
    return {"run_id": backtest.folder.name, "folds": len(folds),
            "metrics_csv_sha256": sha256_hex(recorded_csv), "match": True}


def run_holdout(data_dir: Path, results_dir: Path, *, candidate: Model,
                formal: FormalSetup, log_path: Path, signal: bool = True,
                project_root: Path | None = None, data_label: str | None = None,
                echo: Callable[[str], None] = print) -> RunResult:
    """Holdout stage, formal only, in the order of section 9.4 (steps 1 to 7)."""
    results_dir = Path(results_dir)
    lock_path, head_path = results_dir / LOCK_NAME, results_dir / HEAD_NAME
    root = _project_root(project_root)
    models = _models(candidate)
    hl.create_lock(lock_path)  # step 1
    try:  # steps 2 and 3: any refusal removes the run's own lock, nothing is appended
        inspection = hl.inspect_log(log_path, head_path, results_dir)  # step 2
        if not inspection.usable:
            raise hl.HoldoutRefused(
                f"holdout log integrity failure, state {inspection.state}: "
                f"{'; '.join(inspection.reasons)}")
        created = rec.utc_now()  # step 3
        config_sha = rec.config_hash(m.info for m in models)
        names, signal_record = _input_names(Path(data_dir), signal)
        try:
            raw = read_files(Path(data_dir), names)
        except ForecastingError as error:
            raise hl.HoldoutRefused(str(error)) from None
        hashes = {name: sha256_hex(data) for name, data in raw.items()}
        dhash = data_hash(hashes)
        metadata = _metadata_json(raw)
        first, last = _holdout_dates(metadata)
        backtest = _formal_backtest(results_dir, config_sha, dhash)
        if backtest is None:
            raise hl.HoldoutRefused("no formal backtest pass for this configuration and data")
        _check_backtest_reproducible(backtest)
        if hl.consumed(inspection, dhash, first, last):
            raise hl.HoldoutRefused("this holdout is already consumed")
        seed_record = check_seed(formal, candidate, metadata.get("seed"))
        git = check_git(formal.checker)
        run_id = rec.choose_run_id(results_dir, rec.run_id_base(created, "holdout",
                                                                config_sha))
    except ForecastingError as error:
        hl.remove_lock(lock_path)
        if isinstance(error, hl.HoldoutRefused):
            raise
        raise hl.HoldoutRefused(str(error)) from None
    except BaseException:
        hl.remove_lock(lock_path)
        raise

    # Step 4: from here on every failure consumes the holdout and keeps the lock.
    began = _clock()
    head = inspection.head
    seq = head[0] + 1 if head else 1
    prev = head[1] if head else rec.sha256_text(hl.HEADER)
    started = hl.entry_line(seq, created.strftime("%Y-%m-%dT%H:%M:%SZ"), hl.STARTED, run_id,
                            config_sha, git["commit"], dhash, first, last, "", prev)
    try:
        hl.append_entry(log_path, started, first_use=inspection.state == "A")
        hl.write_head(head_path, seq, rec.sha256_text(started))
        folder = results_dir / run_id
        folder.mkdir()
        # Steps 5 to 7: parse the hashed bytes, recompute and compare the formal backtest
        # (before any holdout forecast), score all four origins in memory, write.
        data = parse_data(raw, with_expected=signal_record["computed"])
        verification = _verify_backtest(data, models, candidate.info.name, backtest)
        forecasts = forecast_origins(data, models, data.split.holdout_origins)
        holdout = score_window(data, HOLDOUT, forecasts, signal_record["computed"])
        levels = {}
        for level in LEVELS:
            ok4 = holdout_condition(holdout.gate[candidate.info.name][level]["open"])
            levels[level] = {"conditions": {**{c: backtest.levels[level]["conditions"][c]
                                               for c in ("1", "2", "3")}, "4": ok4}}
        result = "pass" if all(all(v["conditions"].values()) for v in levels.values()) \
            else "fail"
        _write_tables(folder, [holdout], [])
        completed = hl.entry_line(seq + 1, rec.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  hl.COMPLETED, run_id, config_sha, git["commit"], dhash,
                                  first, last, result, rec.sha256_text(started))
        hl.append_entry(log_path, completed, first_use=False)
        hl.write_head(head_path, seq + 1, rec.sha256_text(completed))
        record = _base_record(root, data, models, "holdout", "formal",
                              _label(data_dir, data_label), signal_record, created,
                              config_sha)
        record.update(run_id=run_id, decision={"value": result,
                                               "candidate": candidate.info.name,
                                               "levels": levels})
        record["code_version"].update(commit=git["commit"], clean_tree=True)
        record["git_provenance"] = git
        record["decision_seed"] = seed_record
        record["backtest_verification"] = verification
        record["diagnostics"] = _diagnostics([holdout], [])
        record["holdout_log"] = {"started": {"seq": seq, "sha256": rec.sha256_text(started)},
                                 "completed": {"seq": seq + 1,
                                               "sha256": rec.sha256_text(completed)},
                                 "head": {"seq": seq + 1,
                                          "sha256": rec.sha256_text(completed)}}
        rec.write_json_atomic(folder / "run.json", record)
    except Exception as error:
        raise HoldoutStopped(f"holdout run stopped after step 4 (consumed, lock kept): "
                             f"{type(error).__name__}: {error}") from error
    hl.remove_lock(lock_path)
    echo(f"holdout run {run_id}: {result}")
    return RunResult(run_id, folder, record, _clock() - began)


def _holdout_dates(metadata: dict) -> tuple[str, str]:
    try:
        split = make_split(date.fromisoformat(metadata["start"]),
                           date.fromisoformat(metadata["end"]))
    except (TypeError, KeyError, ValueError):
        raise ForecastingError("metadata.json start or end is invalid") from None
    return split.holdout_first.isoformat(), split.end.isoformat()


# --------------------------------------------------------------------------- command line

def _resolve(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dealpilot.forecasting.evaluate",
                                     description="Spec 003 evaluation harness "
                                     "(exploratory backtests and holdout log status).")
    sub = parser.add_subparsers(dest="command", required=True)
    backtest = sub.add_parser("backtest", help="exploratory backtest of the baselines")
    backtest.add_argument("--data-dir", default="data/raw",
                          help="relative paths start at the project root")
    backtest.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    backtest.add_argument("--no-signal-recovery", action="store_true")
    status = sub.add_parser("holdout-status", help="read-only holdout log report")
    status.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    status.add_argument("--log", default=str(DEFAULT_LOG))
    args = parser.parse_args(argv)
    root = _project_root(None)
    try:
        if args.command == "backtest":
            result = run_backtest(_resolve(args.data_dir, root),
                                  _resolve(args.results_dir, root),
                                  signal=not args.no_signal_recovery, project_root=root,
                                  data_label=_label(args.data_dir, None))
            print(f"exploratory backtest written to {args.results_dir}/{result.run_id} "
                  f"({result.duration_seconds:.1f} s)")
        else:
            results = _resolve(args.results_dir, root)
            print(json.dumps(hl.status_report(_resolve(args.log, root),
                                              results / HEAD_NAME, results / LOCK_NAME,
                                              results), indent=2, sort_keys=True))
    except ForecastingError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
