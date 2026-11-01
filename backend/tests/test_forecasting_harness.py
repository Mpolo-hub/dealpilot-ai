"""Spec 003 evaluation harness: backtest runs, records, run classes and the decision seed.

Most tests use the small dataset of `forecasting_support` (730 days, 10 product-region
series). AC-FC-16 runs once on the default seed 42 data and is marked slow (section 11).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from dealpilot.forecasting import evaluate as ev
from dealpilot.forecasting import records as rec
from dealpilot.forecasting.baselines import ModelInfo
from dealpilot.forecasting.engine import (
    BASELINES,
    LevelForecast,
    forecast_origins,
    mean_rows,
    score_window,
    window_name,
)
from dealpilot.forecasting.inputs import load_data, visible_inputs, visible_metadata
from dealpilot.forecasting.seed import (
    BASE_EXCLUDED,
    SeedInputs,
    check_recorded_seed,
    derivation_text,
    derive_seed,
)
from dealpilot.forecasting.split import CLOSED_DAYS, ForecastingError
from forecasting_support import (
    CANDIDATE_INFO,
    FakeClean,
    candidate_model,
    folder_bytes,
    write_dataset,
)

RUN_FILES = {"run.json", "metrics.csv", "series_metrics.csv", "signal_recovery.csv"}
EXPLORATORY_FIELDS = {"run_id", "created_at", "spec", "stage", "run_class", "decision_grade",
                      "decision", "config_hash", "code_version", "source_manifest", "data",
                      "library_versions", "calendar", "models", "levels", "diagnostics",
                      "signal_recovery"}
FORMAL_ONLY = {"decision_seed", "git_provenance", "holdout_log"}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    return write_dataset(tmp_path_factory.mktemp("small") / "data")


@pytest.fixture(scope="module")
def data(dataset):
    return load_data(dataset)


def _run(data_dir: Path, results: Path, **kwargs) -> ev.RunResult:
    messages: list[str] = []
    return ev.run_backtest(data_dir, results, echo=messages.append, **kwargs)


def _windows(data):
    return [[w] for w in data.split.folds] + [[w] for w in data.split.holdout_origins]


def _shift_after(data, cutoff: date, amount: int):
    """A copy of the data whose every series value after `cutoff` is changed."""
    col = (cutoff - data.start).days + 1
    values = {level: v.copy() for level, v in data.series.values.items()}
    for v in values.values():
        v[:, col:] += amount
    return dataclasses.replace(data, series=dataclasses.replace(data.series, values=values))


# --------------------------------------------------------------------------- AC-FC-06/07

def test_ac_fc_06_forecasts_ignore_data_after_the_cutoff(data) -> None:
    models = list(BASELINES) + [candidate_model()]
    for origins in _windows(data):
        cutoff = origins[0].cutoff
        before = forecast_origins(data, models, origins).values
        after = forecast_origins(_shift_after(data, cutoff, 1000), models, origins).values
        for model in before:
            for level in before[model]:
                np.testing.assert_array_equal(before[model][level], after[model][level])


def test_ac_fc_07_metadata_reader_gives_start_and_cutoff_only(data) -> None:
    cutoff = data.split.folds[0].cutoff
    assert visible_metadata(data.metadata, cutoff) == {"start": data.start, "cutoff": cutoff}
    assert set(visible_inputs(data, cutoff).metadata) == {"start", "cutoff"}
    assert "parameters" not in data.metadata


def test_ac_fc_07_no_hidden_inputs(dataset, tmp_path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(dataset, copy)
    (copy / "expected_demand.parquet").unlink()
    metadata = json.loads((copy / "metadata.json").read_text(encoding="utf-8"))
    del metadata["parameters"]
    (copy / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    original = _run(dataset, tmp_path / "a")
    stripped = _run(copy, tmp_path / "b")
    for name in ("metrics.csv", "series_metrics.csv"):
        assert (original.folder / name).read_bytes() == (stripped.folder / name).read_bytes()
    assert stripped.record["signal_recovery"] == {
        "computed": False, "reason": "expected_demand.parquet is missing"}


# --------------------------------------------------------------------------- AC-FC-11

def test_ac_fc_11_backtest_ignores_the_holdout(data) -> None:
    def tables(d) -> tuple[str, str]:
        folds = [score_window(d, window_name(w), forecast_origins(d, BASELINES, [w]), False)
                 for w in d.split.folds]
        metrics = rec.csv_text(rec.METRIC_COLUMNS,
                               [r for f in folds for r in f.metric_rows] + mean_rows(folds),
                               ("model", "level", "window", "scope"))
        series = rec.csv_text(rec.SERIES_COLUMNS, [r for f in folds for r in f.series_rows],
                              ("model", "window", "scope", "product_id", "region_id"))
        return metrics, series

    assert tables(data) == tables(_shift_after(data, data.split.holdout_cutoff, 7))


# --------------------------------------------------------------------------- AC-FC-12/13

def test_ac_fc_12_results_record(dataset, tmp_path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "older-run").mkdir()
    data_before = folder_bytes(dataset)
    run = _run(dataset, results)
    assert sorted(p.name for p in results.iterdir()) == sorted(["older-run", run.run_id])
    assert {p.name for p in run.folder.iterdir()} == RUN_FILES
    record = json.loads((run.folder / "run.json").read_text(encoding="utf-8"))
    assert set(record) == EXPLORATORY_FIELDS
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["created_at"])
    assert record["run_id"] == run.folder.name and record["stage"] == "backtest"
    assert record["spec"]["number"] == "003" and record["spec"]["status"].startswith("Approved")
    assert record["data"]["files"] == {
        name: hashlib.sha256((dataset / name).read_bytes()).hexdigest()
        for name in ("metadata.json", "order_lines.parquet", "orders.parquet",
                     "products.parquet", "regions.parquet", "expected_demand.parquet")}
    assert record["data"]["folder"] == "<absolute path>"
    assert set(record["library_versions"]) == {"python", "numpy", "pandas", "duckdb",
                                               "pyarrow"}
    assert [m["name"] for m in record["models"]] == ["seasonal_naive", "naive"]
    assert record["levels"] == {"total": 1, "category": 2, "product_region": 10}
    assert len(record["calendar"]["folds"]) == 13
    assert [o["horizon"] for o in record["calendar"]["holdout_origins"]] == [28, 28, 28, 6]
    assert folder_bytes(dataset) == data_before


def test_ac_fc_12_data_folder_label_is_relative_or_hidden(dataset, tmp_path) -> None:
    run = _run(dataset, tmp_path / "r", data_label=None)
    assert run.record["data"]["folder"] == "<absolute path>"
    assert ev._label("data/raw", None) == "data/raw"


def test_ac_fc_13_reproducible(dataset, tmp_path) -> None:
    first = _run(dataset, tmp_path / "one")
    second = _run(dataset, tmp_path / "two")
    for name in RUN_FILES - {"run.json"}:
        text = (first.folder / name).read_bytes()
        assert text == (second.folder / name).read_bytes()
        assert b"\r" not in text
    a = json.loads((first.folder / "run.json").read_text(encoding="utf-8"))
    b = json.loads((second.folder / "run.json").read_text(encoding="utf-8"))
    for key in ("run_id", "created_at"):
        a.pop(key)
        b.pop(key)
    assert a == b


def test_ac_fc_13_number_format_and_row_order() -> None:
    rows = [{"model": "b", "level": "total", "window": "fold_01", "scope": "open",
             "wape": 1 / 3}, {"model": "a", "level": "total", "window": "fold_01",
                              "scope": "open", "wape": None, "n_tie": 2}]
    text = rec.csv_text(rec.METRIC_COLUMNS, rows, ("model", "level", "window", "scope"))
    lines = text.split("\n")
    assert lines[1].startswith("a,total,fold_01,open,,") and ",2," in lines[1]
    assert lines[2].startswith("b,total,fold_01,open,0.3333333333,")
    assert text.endswith("\n") and "\r" not in text


# --------------------------------------------------------------------------- AC-FC-14

def test_ac_fc_14_signal_recovery_is_separate(data, dataset, tmp_path) -> None:
    window = data.split.folds[0]
    scores = score_window(data, "fold_01", forecast_origins(data, BASELINES, [window]), True)
    days = [window.first + timedelta(days=i) for i in range(window.horizon)]
    cols = [(d - data.start).days for d in days]
    actual = data.series.values["total"][0, cols].astype(float)
    # Hand case: expected units are the actual units plus 0.5 on every day with sales.
    noise = 0.5 * float((data.series.values["product_region"][:, cols] > 0).sum()) / actual.sum()
    row = next(r for r in scores.signal_rows if r["model"] == "seasonal_naive"
               and r["level"] == "total" and r["scope"] == "all")
    assert row["noise_floor"] == pytest.approx(noise, rel=1e-12)
    forecast = forecast_origins(data, BASELINES, [window]).values["seasonal_naive"]["total"][0]
    x = data.expected[:, cols].sum(axis=0)
    assert row["signal_wape"] == pytest.approx(np.abs(forecast - x).sum() / x.sum(), rel=1e-12)

    run = _run(dataset, tmp_path / "r", candidate=candidate_model())
    header = (run.folder / "metrics.csv").read_text(encoding="utf-8").split("\n")[0]
    assert "signal" not in header and "noise" not in header
    doubled = dataclasses.replace(data, expected=data.expected * 2)
    gate = [ev.evaluate_gate(ev.level_scores(ev._score_folds(d, [*BASELINES, candidate_model()],
                                                             True), None, "weekly_copy"),
                             "exploratory", "backtest") for d in (data, doubled)]
    assert gate[0] == gate[1]


# --------------------------------------------------------------------------- AC-FC-16

def test_ac_fc_16_runtime_warning(dataset, tmp_path, monkeypatch) -> None:
    ticks = iter([0.0, 61.5])
    monkeypatch.setattr(ev, "_clock", lambda: next(ticks))
    messages: list[str] = []
    run = ev.run_backtest(dataset, tmp_path / "r", echo=messages.append)
    assert run.duration_seconds == 61.5
    assert any("61.5 s" in m for m in messages)
    assert any("61.5 s" in w for w in run.record["diagnostics"]["warnings"])


@pytest.mark.slow
def test_ac_fc_16_full_baseline_run(generated_dir, tmp_path) -> None:
    run = _run(generated_dir, tmp_path / "r")
    lines = (run.folder / "metrics.csv").read_text(encoding="utf-8").splitlines()
    columns = lines[0].split(",")
    rows = [dict(zip(columns, line.split(","))) for line in lines[1:]]
    windows = {f"fold_{i:02d}" for i in range(1, 14)} | {"mean"}
    expected = {(m, lv, w, s) for m in ("seasonal_naive", "naive")
                for lv in ("total", "category", "product_region") for w in windows
                for s in ("open", "all")}
    assert {(r["model"], r["level"], r["window"], r["scope"]) for r in rows} == expected
    assert all(r["wape"] != "" for r in rows)
    assert run.duration_seconds > 0
    assert run.record["levels"] == {"total": 1, "category": 5, "product_region": 250}


# --------------------------------------------------------------------------- AC-FC-17

class _Constant:
    info = ModelInfo("constant_one", "1.0", {}, False, False)

    def forecast(self, inputs, level, horizon):
        keys, _ = inputs.history[level]
        return LevelForecast(keys, np.ones((len(keys), horizon)))


def test_ac_fc_17_cutoff_visible_inputs(data) -> None:
    early = visible_inputs(data, date(2023, 6, 1))
    assert [p.product_id for p in early.products] == ["P001", "P002", "P003"]
    assert next(p for p in early.products if p.product_id == "P002").discontinue_date is None
    later = visible_inputs(data, date(2024, 5, 1))
    assert next(p for p in later.products if p.product_id == "P002").discontinue_date \
        == date(2023, 9, 1)
    assert "P005" not in {p.product_id for p in later.products}
    assert later.regions == ("R01", "R02") and all(isinstance(r, str) for r in later.regions)
    assert set(later.metadata) == {"start", "cutoff"}
    for keys, values in later.history.values():
        assert values.shape == (len(keys), (date(2024, 5, 1) - data.start).days + 1)
    assert all(k[0] != "P005" for k in later.history["product_region"][0])

    window = data.split.folds[0]
    assert window.cutoff < date(2024, 10, 20)
    forecasts = forecast_origins(data, [_Constant()], [window]).values["constant_one"]
    keys = data.series.keys["product_region"]
    for i, (product_id, _) in enumerate(keys):
        assert forecasts["product_region"][i].tolist() == \
            ([0.0] * 28 if product_id in ("P004", "P005") else [1.0] * 28)


def test_ac_fc_17_holiday_constant(generated_dir) -> None:
    assert CLOSED_DAYS == ((12, 25), (1, 1))  # spec 001 section 5.7
    metadata = json.loads((generated_dir / "metadata.json").read_text(encoding="utf-8"))
    assert {f"{m:02d}-{d:02d}" for m, d in CLOSED_DAYS} \
        == set(metadata["parameters"]["closed_days"])


# --------------------------------------------------------------------------- AC-FC-23

def _formal_dataset(tmp_path: Path) -> tuple[Path, ev.FormalSetup]:
    inputs = SeedInputs("004", CANDIDATE_INFO.name, CANDIDATE_INFO.version,
                        rec.candidate_config_sha256(CANDIDATE_INFO), "1")
    derived = derive_seed(inputs)
    folder = write_dataset(tmp_path / "formal-data", seed=derived.seed)
    return folder, ev.FormalSetup(derived.inputs, lambda: FakeClean())


def test_ac_fc_23_exploratory_run_class(dataset, tmp_path) -> None:
    record = _run(dataset, tmp_path / "r").record
    assert record["run_class"] == "exploratory" and record["decision_grade"] is False
    assert record["decision"]["value"] == "not decided" and record["source_manifest"]
    assert "git_provenance" not in record and "decision_seed" not in record


def _raise(error):
    def checker():
        raise error
    return checker


@pytest.mark.parametrize("checker", [
    lambda: FakeClean(commit=None),  # no commit
    lambda: FakeClean(outcome="DIRTY", clean=False, reasons=("changes_present",)),
    lambda: FakeClean(outcome="REFUSED", clean=False, reasons=("no_head_commit",)),
    lambda: FakeClean(outcome="CLEAN", clean=False),  # never assumed clean
    lambda: object(),  # unknown result
    _raise(ImportError("pygit2")),  # checker cannot be imported
    _raise(OSError("no repository")),
], ids=["no-commit", "dirty", "refused", "clean-flag-false", "unknown", "import", "error"])
def test_ac_fc_23_formal_fails_closed(tmp_path, checker) -> None:
    folder, formal = _formal_dataset(tmp_path)
    results = tmp_path / "results"
    with pytest.raises(ForecastingError):
        _run(folder, results, candidate=candidate_model(),
             formal=dataclasses.replace(formal, checker=checker))
    assert not results.exists() or not any(results.iterdir())


def test_ac_fc_23_clean_alone_never_allows_a_formal_run(tmp_path, dataset) -> None:
    folder, formal = _formal_dataset(tmp_path)
    seed = formal.seed_inputs
    cases = [  # (data folder, candidate, formal setup)
        (folder, None, formal),  # no candidate
        (dataset, candidate_model(), formal),  # metadata seed 42 differs from the derived one
        (folder, candidate_model(), dataclasses.replace(
            formal, seed_inputs=dataclasses.replace(seed, decision="2"))),
        (folder, candidate_model(), dataclasses.replace(
            formal, seed_inputs=dataclasses.replace(seed, name="other"))),
    ]
    for i, (data_dir, candidate, setup) in enumerate(cases):
        results = tmp_path / f"results{i}"
        with pytest.raises(ForecastingError):
            _run(data_dir, results, candidate=candidate, formal=setup)
        assert not results.exists() or not any(results.iterdir())


def test_ac_fc_23_formal_backtest_records_provenance(tmp_path) -> None:
    folder, formal = _formal_dataset(tmp_path)
    run = _run(folder, tmp_path / "results", candidate=candidate_model(), formal=formal)
    record = run.record
    assert record["run_class"] == "formal" and record["decision_grade"] is True
    assert record["code_version"]["commit"] == "a" * 40
    assert record["code_version"]["clean_tree"] is True
    assert record["git_provenance"]["clean_tree"] is True
    assert record["decision_seed"]["match"] is True
    assert "source_manifest" not in record
    # The candidate copies seasonal naive, so it can't beat it: a formal backtest fails.
    assert record["decision"]["value"] == "fail"


# --------------------------------------------------------------------------- AC-FC-24

def test_ac_fc_24_run_id_collisions(dataset, tmp_path, monkeypatch) -> None:
    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    monkeypatch.setattr(rec, "utc_now", lambda: fixed)
    results = tmp_path / "results"
    config = rec.config_hash(m.info for m in BASELINES)
    base = rec.run_id_base(fixed, "backtest", config)
    assert base == f"20260102T030405Z-backtest-{config[:8]}"
    (results / base).mkdir(parents=True)
    (results / base / "keep.txt").write_text("x", encoding="utf-8")
    assert _run(dataset, results).run_id == f"{base}-2"
    for n in range(3, 100):
        (results / f"{base}-{n}").mkdir()
    before = folder_bytes(results)
    with pytest.raises(ForecastingError):
        _run(dataset, results)
    assert folder_bytes(results) == before


# --------------------------------------------------------------------------- AC-FC-25

def _formula(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big") \
        & 0x7FFFFFFF


SAMPLE = SeedInputs("004", "my_model", "1.10", "0123456789abcdef" * 4, "3", "1")


def test_ac_fc_25_derived_seed_matches_the_formula() -> None:
    text = ("dealpilot-decision-seed/v1|spec=004|candidate=my_model@1.10|config="
            + "0123456789abcdef" * 4 + "|decision=3|n=1")
    assert derivation_text(SAMPLE) == text
    derived = derive_seed(SAMPLE)
    assert derived.seed == _formula(text) and derived.inputs.n == "1"


@pytest.mark.parametrize("field,value", [
    ("spec", "4"), ("spec", "0041"), ("name", "My_model"), ("name", "1model"),
    ("name", "my-model"), ("version", "1."), ("version", "v1"), ("version", "1.0a"),
    ("config_sha256", "0123456789ABCDEF" * 4), ("config_sha256", "abc"),
    ("decision", "0"), ("decision", "01"), ("decision", "-1"), ("n", "0"), ("n", "1 "),
    ("decision", "١"),
])
def test_ac_fc_25_bad_fields_refuse(field, value) -> None:
    with pytest.raises(ForecastingError):
        derive_seed(dataclasses.replace(SAMPLE, **{field: value}))


def test_ac_fc_25_canonical_json_and_floats() -> None:
    record = {"name": "m", "version": "1.0", "settings": {"b": [1, True, None], "a": "é\"\n\x01"},
              "uses_holiday_calendar": True, "uses_planned_promotions": False}
    assert rec.canonical_json(record) == (
        '{"name":"m","settings":{"a":"é\\"\\n\\u0001","b":[1,true,null]},'
        '"uses_holiday_calendar":true,"uses_planned_promotions":false,"version":"1.0"}')
    info = ModelInfo("m", "1.0", {"alpha": 0.5}, False, False)
    with pytest.raises(ForecastingError):
        rec.candidate_config_sha256(info)


def test_ac_fc_25_excluded_seed_raises_n_only() -> None:
    first = derive_seed(SAMPLE)
    second = derive_seed(SAMPLE, excluded=frozenset({first.seed}))
    assert second.inputs == dataclasses.replace(SAMPLE, n="2")
    assert second.seed == _formula(derivation_text(dataclasses.replace(SAMPLE, n="2")))
    assert {42, 7} | set(range(1, 11)) == BASE_EXCLUDED


def test_ac_fc_25_metadata_seed_must_match() -> None:
    derived = derive_seed(SAMPLE)
    record = check_recorded_seed(derived.inputs, derived.seed)
    assert record["match"] is True and record["derived_seed"] == derived.seed
    for wrong in (derived.seed + 1, str(derived.seed), None, True):
        with pytest.raises(ForecastingError):
            check_recorded_seed(derived.inputs, wrong)


def test_config_hash_orders_versions_numerically() -> None:
    def info(version):
        return ModelInfo("m", version, {}, False, False)
    order = sorted(["1.10", "1.9", "1.0.0", "1.0", "1.01", "1.1"], key=rec.version_key)
    assert order == ["1.0", "1.0.0", "1.01", "1.1", "1.9", "1.10"]
    assert rec.config_hash([info("1.10"), info("1.9")]) \
        == rec.config_hash([info("1.9"), info("1.10")])
