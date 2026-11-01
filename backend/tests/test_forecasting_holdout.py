"""Spec 003 holdout log, governance and holdout origins (AC-FC-19, AC-FC-20).

Everything runs in temporary folders with the small dataset of `forecasting_support`, a
fake clean-tree checker and a real formal backtest of a test-only candidate that passes
gate conditions 1 to 3. Nothing here touches `evals/` or the project's Git repository.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from dealpilot.forecasting import evaluate as ev
from dealpilot.forecasting import holdout_log as hl
from dealpilot.forecasting import records as rec
from dealpilot.forecasting.engine import BASELINES, SeriesModel
from dealpilot.forecasting.inputs import A1_FILES, data_hash
from dealpilot.forecasting.seed import SeedInputs, derive_seed
from dealpilot.forecasting.split import ForecastingError
from forecasting_support import (
    LAG_INFO,
    START,
    FakeClean,
    folder_bytes,
    passing_candidate,
    write_dataset,
)

HOLDOUT = ("2024-10-02", "2024-12-30")
H64 = "0" * 64
RUN_A = "20260101T000000Z-holdout-00000000"
RUN_B = "20260101T000001Z-holdout-00000000"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line(seq, event, run_id, prev, data=H64, result="", start=HOLDOUT[0],
          end=HOLDOUT[1]) -> str:
    return hl.entry_line(seq, "2026-01-01T00:00:00Z", event, run_id, H64, "c" * 40, data,
                         start, end, result, prev)


def _chain(*specs) -> list[str]:
    """Lines for (event, run_id[, result]) specs, chained from the header."""
    lines, prev = [], _sha(hl.HEADER)
    for seq, spec in enumerate(specs, start=1):
        event, run_id = spec[0], spec[1]
        line = _line(seq, event, run_id, prev, result=spec[2] if len(spec) > 2 else "")
        lines.append(line)
        prev = _sha(line)
    return lines


class Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.results = root / "results"
        self.results.mkdir(parents=True, exist_ok=True)
        self.log = root / "holdout-log.csv"
        self.head = self.results / ev.HEAD_NAME
        self.lock = self.results / ev.LOCK_NAME

    def write_log(self, lines: list[str], header: bool = True, final_lf: bool = True) -> None:
        text = "\n".join(([hl.HEADER] if header else []) + lines)
        self.log.write_bytes((text + ("\n" if final_lf else "")).encode("utf-8"))

    def write_head_for(self, lines: list[str]) -> None:
        self.head.write_bytes(hl.head_bytes(len(lines), _sha(lines[-1])))

    def state(self) -> str:
        return hl.inspect_log(self.log, self.head, self.results).state

    def snapshot(self) -> dict:
        return folder_bytes(self.root)


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(tmp_path / "evals")


# --------------------------------------------------------------------------- log states

def test_ac_fc_19_state_a_first_use(paths) -> None:
    assert paths.state() == "A"


def test_ac_fc_19_state_b_holdout_folder_without_log(paths) -> None:
    (paths.results / RUN_A).mkdir()
    assert paths.state() == "B"


def test_ac_fc_19_state_c_head_without_log(paths) -> None:
    paths.head.write_bytes(hl.head_bytes(1, H64))
    assert paths.state() == "C"


@pytest.mark.parametrize("with_head", [False, True])
def test_ac_fc_19_state_d_header_only(paths, with_head) -> None:
    paths.write_log([])
    if with_head:
        paths.head.write_bytes(hl.head_bytes(1, H64))
    assert paths.state() == "D"


def test_ac_fc_19_state_e_entries_without_head(paths) -> None:
    paths.write_log(_chain(("started", RUN_A)))
    assert paths.state() == "E"


@pytest.mark.parametrize("case", ["empty", "wrong-header", "fields", "no-final-lf",
                                  "not-utf8", "partial-header"])
def test_ac_fc_19_state_f_malformed(paths, case) -> None:
    lines = _chain(("started", RUN_A))
    if case == "empty":
        paths.log.write_bytes(b"")
    elif case == "wrong-header":
        paths.log.write_bytes(("seq,timestamp\n" + lines[0] + "\n").encode())
    elif case == "fields":
        paths.write_log([lines[0] + ",extra"])
    elif case == "no-final-lf":
        paths.write_log(lines, final_lf=False)
    elif case == "not-utf8":
        paths.log.write_bytes((hl.HEADER + "\n").encode() + b"\xff\xfe\n")
    else:
        paths.log.write_bytes(hl.HEADER[:10].encode())
    paths.write_head_for(lines)
    assert paths.state() == "F"


@pytest.mark.parametrize("head", [b"1," + b"a" * 64, b"1," + b"a" * 64 + b"\r\n",
                                  b"1, " + b"a" * 64 + b"\n", b"1," + b"A" * 64 + b"\n",
                                  b"01," + b"a" * 64 + b"\n",
                                  b"1," + b"a" * 64 + b"\n2," + b"a" * 64 + b"\n"],
                         ids=["no-lf", "cr", "space", "uppercase", "leading-zero",
                              "second-line"])
def test_ac_fc_19_state_g_unreadable_head(paths, head) -> None:
    paths.write_log(_chain(("started", RUN_A)))
    paths.head.write_bytes(head)
    assert paths.state() == "G"


def test_ac_fc_19_state_g_head_differs(paths) -> None:
    lines = _chain(("started", RUN_A), ("completed", RUN_A, "pass"))
    paths.write_log(lines)
    paths.head.write_bytes(hl.head_bytes(1, _sha(lines[0])))  # seq and hash of entry 1
    assert paths.state() == "G"
    paths.head.write_bytes(hl.head_bytes(2, _sha(lines[0])))  # right seq, wrong hash
    assert paths.state() == "G"


def test_ac_fc_19_normal_state(paths) -> None:
    lines = _chain(("started", RUN_A), ("completed", RUN_A, "fail"), ("started", RUN_B))
    paths.write_log(lines)
    paths.write_head_for(lines)
    inspection = hl.inspect_log(paths.log, paths.head, paths.results)
    assert inspection.state == hl.NORMAL and inspection.head == (3, _sha(lines[-1]))


def test_ac_fc_19_precedence(paths) -> None:
    # B and C need no log; with a header-only log and a bad head record, D comes first.
    paths.write_log([])
    paths.head.write_bytes(b"garbage")
    (paths.results / RUN_A).mkdir()
    assert paths.state() == "D"
    # F before E and G: a broken chain with no head record is F.
    lines = _chain(("started", RUN_A), ("started", RUN_B))
    lines[1] = lines[1].replace(_sha(lines[0]), H64)
    paths.write_log(lines)
    paths.head.unlink()
    assert paths.state() == "F"


# --------------------------------------------------------------------------- tampering

@pytest.mark.parametrize("tamper", ["modify-middle", "delete", "swap", "truncate",
                                    "modify-last", "head-mismatch", "head-missing",
                                    "duplicate-started", "completed-first"])
def test_ac_fc_19_tampering_is_refused(paths, tamper) -> None:
    lines = _chain(("started", RUN_A), ("completed", RUN_A, "pass"), ("started", RUN_B))
    paths.write_log(lines)
    paths.write_head_for(lines)
    if tamper == "modify-middle":
        paths.write_log([lines[0], lines[1].replace(",pass,", ",fail,"), lines[2]])
    elif tamper == "delete":
        paths.write_log([lines[0], lines[2]])
    elif tamper == "swap":
        paths.write_log([lines[1], lines[0], lines[2]])
    elif tamper == "truncate":
        paths.write_log(lines[:2])
    elif tamper == "modify-last":
        paths.write_log(lines[:2] + [lines[2].replace("2026-01-01", "2026-01-02")])
    elif tamper == "head-mismatch":
        paths.head.write_bytes(hl.head_bytes(3, H64))
    elif tamper == "head-missing":
        paths.head.unlink()
    elif tamper == "duplicate-started":
        extra = _line(4, "started", RUN_A, _sha(lines[2]))
        paths.write_log(lines + [extra])
        paths.write_head_for(lines + [extra])
    else:
        bad = _chain(("completed", RUN_A, "pass"))
        paths.write_log(bad)
        paths.write_head_for(bad)
    assert paths.state() in {"E", "F", "G"}


# --------------------------------------------------------------------------- consumption

def test_ac_fc_19_started_entry_counts_as_consumed_even_in_state_f(paths) -> None:
    lines = _chain(("started", RUN_A), ("completed", RUN_A, "pass"))
    paths.write_log([lines[0], lines[1].replace(_sha(lines[0]), H64)])  # chain broken
    inspection = hl.inspect_log(paths.log, paths.head, paths.results)
    assert inspection.state == "F"
    assert hl.consumed(inspection, H64, *HOLDOUT)
    assert not hl.consumed(inspection, "1" * 64, *HOLDOUT)  # other data_hash: not blocked
    report = hl.status_report(paths.log, paths.head, paths.lock, paths.results)
    assert RUN_A in report["runs"]


def test_ac_fc_19_reported_run_states(paths) -> None:
    lines = _chain(("started", RUN_A), ("completed", RUN_A, "pass"), ("started", RUN_B))
    paths.write_log(lines)
    paths.write_head_for(lines)
    report = hl.status_report(paths.log, paths.head, paths.lock, paths.results)
    assert report["runs"] == {RUN_A: "completed, record incomplete", RUN_B: "interrupted"}
    (paths.results / RUN_A).mkdir()
    (paths.results / RUN_A / "run.json").write_text("{}", encoding="utf-8")
    report = hl.status_report(paths.log, paths.head, paths.lock, paths.results)
    assert report["runs"][RUN_A] == "completed"


# --------------------------------------------------------------------------- holdout runs

@dataclasses.dataclass
class Setup:
    data: Path
    paths: Paths
    formal: ev.FormalSetup
    dhash: str
    config: str


@pytest.fixture
def setup(tmp_path) -> Setup:
    inputs = SeedInputs("004", LAG_INFO.name, LAG_INFO.version,
                        rec.candidate_config_sha256(LAG_INFO), "1")
    derived = derive_seed(inputs)
    data = write_dataset(tmp_path / "data", seed=derived.seed)
    paths = Paths(tmp_path / "evals")
    formal = ev.FormalSetup(derived.inputs, lambda: FakeClean())
    backtest = ev.run_backtest(data, paths.results, candidate=passing_candidate(),
                               formal=formal, echo=lambda _: None)
    assert backtest.record["decision"]["value"] == "not decided"  # passed conditions 1-3
    config = rec.config_hash(m.info for m in [*BASELINES, passing_candidate()])
    files = {name: hashlib.sha256((data / name).read_bytes()).hexdigest() for name in A1_FILES}
    return Setup(data, paths, formal, data_hash(files), config)


def _holdout(s: Setup, candidate=None, **kwargs) -> ev.RunResult:
    return ev.run_holdout(s.data, s.paths.results,
                          candidate=candidate or passing_candidate(),
                          formal=kwargs.pop("formal", s.formal), log_path=s.paths.log,
                          echo=lambda _: None, **kwargs)


def _log_lines(s: Setup) -> list[str]:
    return s.paths.log.read_bytes().decode("utf-8").split("\n")[:-1]


def test_ac_fc_19_first_use_creates_log_and_head(setup) -> None:
    run = _holdout(setup)
    lines = _log_lines(setup)
    assert lines[0] == hl.HEADER and len(lines) == 3
    started, completed = (dict(zip(hl.COLUMNS, x.split(","))) for x in lines[1:])
    assert started["prev_sha256"] == _sha(hl.HEADER) and started["seq"] == "1"
    assert started["event"] == "started" and started["result"] == ""
    assert started["data_hash"] == setup.dhash and started["config_hash"] == setup.config
    assert (started["holdout_start"], started["holdout_end"]) == HOLDOUT
    assert completed["prev_sha256"] == _sha(lines[1]) and completed["result"] in ("pass", "fail")
    assert setup.paths.head.read_bytes() == f"2,{_sha(lines[2])}\n".encode("ascii")
    assert not setup.paths.lock.exists()
    assert {p.name for p in run.folder.iterdir()} == {"run.json", "metrics.csv",
                                                      "series_metrics.csv",
                                                      "signal_recovery.csv"}
    record = run.record
    assert record["stage"] == "holdout" and record["run_class"] == "formal"
    assert record["holdout_log"]["head"] == {"seq": 2, "sha256": _sha(lines[2])}
    assert record["holdout_log"]["started"]["sha256"] == _sha(lines[1])
    assert hl.inspect_log(setup.paths.log, setup.paths.head, setup.paths.results).state \
        == hl.NORMAL


def test_ac_fc_19_holdout_is_used_once(setup) -> None:
    _holdout(setup)
    before = setup.paths.snapshot()
    with pytest.raises(hl.HoldoutRefused, match="consumed"):
        _holdout(setup)
    assert setup.paths.snapshot() == before


def _refused_unchanged(setup: Setup, match: str | None = None, **kwargs) -> None:
    before = setup.paths.snapshot()
    with pytest.raises(hl.HoldoutRefused, match=match):
        _holdout(setup, **kwargs)
    assert setup.paths.snapshot() == before


@pytest.mark.parametrize("state", ["B", "C", "D", "E", "F", "G"])
def test_ac_fc_19_integrity_states_refuse_and_change_nothing(setup, state) -> None:
    p = setup.paths
    lines = _chain(("started", RUN_A))
    if state == "B":
        (p.results / RUN_A).mkdir()
    elif state == "C":
        p.head.write_bytes(hl.head_bytes(1, H64))
    elif state == "D":
        p.write_log([])
    elif state == "E":
        p.write_log(lines)
    elif state == "F":
        p.write_log(lines, final_lf=False)
    else:
        p.write_log(lines)
        p.head.write_bytes(b"1," + b"a" * 64 + b"\r\n")
    _refused_unchanged(setup, match=f"state {state}")
    assert not p.lock.exists()


def test_ac_fc_19_existing_lock_refuses(setup) -> None:
    setup.paths.lock.write_text("stale", encoding="utf-8")
    _refused_unchanged(setup, match="lock")
    assert setup.paths.lock.read_text(encoding="utf-8") == "stale"


def test_ac_fc_19_step_3_refusals_append_nothing(setup) -> None:
    # Clean-tree check fails, decision seed fails, missing A1 file, no backtest pass.
    _refused_unchanged(setup, formal=dataclasses.replace(
        setup.formal, checker=lambda: FakeClean(outcome="DIRTY", clean=False)))
    _refused_unchanged(setup, formal=dataclasses.replace(
        setup.formal, seed_inputs=dataclasses.replace(setup.formal.seed_inputs,
                                                      decision="9")))
    other = SeriesModel(dataclasses.replace(LAG_INFO, version="2.0"),
                        passing_candidate().function)
    _refused_unchanged(setup, match="formal backtest", candidate=other)
    (setup.data / "regions.parquet").rename(setup.data / "regions.bak")
    _refused_unchanged(setup, match="regions.parquet")
    (setup.data / "regions.bak").rename(setup.data / "regions.parquet")
    # Afterwards the first use is still state A and the holdout is not consumed.
    assert setup.paths.state() == "A"
    _holdout(setup)


def test_ac_fc_19_backtest_must_pass_conditions_1_to_3(tmp_path, setup) -> None:
    for folder in setup.paths.results.iterdir():
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        record["decision"]["levels"]["category"]["conditions"]["1"] = False
        (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")
    _refused_unchanged(setup, match="formal backtest")


def test_ac_fc_19_data_hash_is_independent_of_signal_files(setup) -> None:
    _holdout(setup, signal=False)
    (setup.data / "expected_demand.parquet").unlink()
    _refused_unchanged(setup, match="consumed")


def test_ac_fc_19_data_hash_formula(setup) -> None:
    text = "".join(hashlib.sha256((setup.data / n).read_bytes()).hexdigest() + "\n"
                   for n in sorted(A1_FILES, key=lambda n: n.encode()))
    assert setup.dhash == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("where", ["fsync", "head", "folder", "step5"])
def test_ac_fc_19_handled_errors_from_step_4_keep_the_lock(setup, monkeypatch, where) -> None:
    def boom(*args, **kwargs):
        raise OSError("injected")

    loaded = []
    monkeypatch.setattr(ev, "parse_data", lambda *a, **k: loaded.append(1) or boom())
    if where == "fsync":
        monkeypatch.setattr(hl, "_fsync", boom)
    elif where == "head":
        monkeypatch.setattr(hl, "write_head", boom)
    elif where == "folder":
        monkeypatch.setattr(ev.rec, "choose_run_id", lambda results, base: "../outside/x")
    with pytest.raises(ev.HoldoutStopped):
        _holdout(setup)
    assert setup.paths.lock.exists()  # never removed automatically
    assert bool(loaded) == (where == "step5")  # no data before the durable point
    with pytest.raises(hl.HoldoutRefused, match="lock"):
        _holdout(setup)


def test_ac_fc_19_interrupted_run_is_reported_and_consumed(setup, monkeypatch) -> None:
    monkeypatch.setattr(ev, "parse_data", lambda *a, **k: (_ for _ in ()).throw(
        OSError("crash")))
    with pytest.raises(ev.HoldoutStopped):
        _holdout(setup)
    monkeypatch.undo()
    report = hl.status_report(setup.paths.log, setup.paths.head, setup.paths.lock,
                              setup.paths.results)
    assert report["state"] == hl.NORMAL and report["lock_present"] is True
    assert list(report["runs"].values()) == ["interrupted"]
    setup.paths.lock.unlink()  # the test stands for a handled incident
    _refused_unchanged(setup, match="consumed")


@pytest.mark.parametrize("case,state", [("header-only", "D"), ("started-no-head", "E"),
                                        ("partial-started", "F"), ("started-and-head", "normal")])
def test_ac_fc_19_first_use_crash_in_step_4(setup, case, state) -> None:
    p = setup.paths
    started = _line(1, "started", RUN_A, _sha(hl.HEADER), data=setup.dhash)
    p.lock.write_text("stale", encoding="utf-8")
    if case == "header-only":
        p.write_log([])
    elif case == "started-no-head":
        p.write_log([started])
    elif case == "partial-started":
        p.write_log([started[:40]], final_lf=False)
    else:
        p.write_log([started])
        p.write_head_for([started])
    _refused_unchanged(setup, match="lock")
    p.lock.unlink()  # removed by the test, standing for a handled incident
    assert p.state() == state
    inspection = hl.inspect_log(p.log, p.head, p.results)
    assert hl.consumed(inspection, setup.dhash, *HOLDOUT) == (case in ("started-no-head",
                                                                     "started-and-head"))
    _refused_unchanged(setup)
    if case == "started-no-head":  # an approved fix: a head record for the unchanged log
        p.write_head_for([started])
        _refused_unchanged(setup, match="consumed")


def test_ac_fc_19_crash_before_started_is_not_consumed(setup) -> None:
    setup.paths.lock.write_text("stale", encoding="utf-8")
    _refused_unchanged(setup, match="lock")
    setup.paths.lock.unlink()
    assert setup.paths.state() == "A"
    _holdout(setup)


def test_ac_fc_19_never_writes_the_incident_record(setup, tmp_path) -> None:
    _holdout(setup)
    written = {p.name for p in tmp_path.rglob("*")}
    assert "holdout-integrity.md" not in written and "incidents" not in written


# --------------------------------------------------------------------------- AC-FC-20

HOLDOUT_CUTOFF = date(2024, 10, 1)


class _Spy:
    """The passing candidate, recording each holdout fit's cutoff and history length."""

    def __init__(self, fail_at_origin: int | None = None) -> None:
        self.inner = passing_candidate()
        self.info = self.inner.info
        self.calls: list[tuple] = []
        self.fail_at = fail_at_origin

    def forecast(self, inputs, level, horizon):
        if inputs.cutoff < HOLDOUT_CUTOFF:  # the backtest recomputation (13 folds)
            return self.inner.forecast(inputs, level, horizon)
        self.calls.append((inputs.cutoff, inputs.history[level][1].shape[1], horizon))
        cutoffs = sorted({c[0] for c in self.calls})
        if self.fail_at is not None and len(cutoffs) == self.fail_at:
            raise RuntimeError("origin failed on purpose")
        return self.inner.forecast(inputs, level, horizon)


def test_ac_fc_20_holdout_origins(setup) -> None:
    spy = _Spy()
    run = _holdout(setup, candidate=spy)
    cutoffs = sorted({c[0] for c in spy.calls})
    assert [c.isoformat() for c in cutoffs] == ["2024-10-01", "2024-10-29", "2024-11-26",
                                                "2024-12-24"]
    for cutoff, history_days, _ in spy.calls:
        assert history_days == (cutoff - START).days + 1  # only data up to the cutoff
    assert [h for _, _, h in spy.calls[::3]] == [28, 28, 28, 6]
    assert run.record["config_hash"] == setup.config  # one frozen configuration


def test_ac_fc_20_no_run_file_before_all_origins(setup) -> None:
    with pytest.raises(ev.HoldoutStopped):
        _holdout(setup, candidate=_Spy(fail_at_origin=4))
    folders = [p for p in setup.paths.results.iterdir() if "-holdout-" in p.name]
    assert len(folders) == 1 and not any(folders[0].iterdir())  # no metrics files
    lines = _log_lines(setup)
    assert [x.split(",")[2] for x in lines[1:]] == ["started"]
    assert setup.paths.lock.exists()
    with pytest.raises(ForecastingError):
        _holdout(setup)


# --------------------------------------------------------------------------- recomputation

def _backtest_folder(s: Setup) -> Path:
    return next(p for p in s.paths.results.iterdir() if "-backtest-" in p.name)


def test_holdout_records_the_backtest_verification(setup) -> None:
    run = _holdout(setup)
    check = run.record["backtest_verification"]
    assert check["match"] is True and check["folds"] == 13
    assert check["run_id"] == _backtest_folder(setup).name
    assert check["metrics_csv_sha256"] == hashlib.sha256(
        (_backtest_folder(setup) / "metrics.csv").read_bytes()).hexdigest()


@pytest.mark.parametrize("edit", ["gate-value", "metrics-csv"])
def test_holdout_stops_when_the_backtest_record_differs(setup, edit) -> None:
    folder = _backtest_folder(setup)
    if edit == "gate-value":  # still claims a pass, but a value was changed
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        level = record["decision"]["levels"]["total"]
        level["mean_wape_candidate"] = level["mean_wape_candidate"] * 0.5
        (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")
    else:
        csv = (folder / "metrics.csv").read_bytes()
        (folder / "metrics.csv").write_bytes(csv.replace(b"fold_01,open,", b"fold_01,open,9", 1))
    spy = _Spy()
    with pytest.raises(ev.HoldoutStopped, match="does not match the recomputation"):
        _holdout(setup, candidate=spy)
    assert spy.calls == []  # no holdout origin was forecast
    assert [x.split(",")[2] for x in _log_lines(setup)[1:]] == ["started"]  # consumed
    assert setup.paths.lock.exists()  # kept: an integrity incident
    holdout_folder = next(p for p in setup.paths.results.iterdir() if "-holdout-" in p.name)
    assert not any(holdout_folder.iterdir())


@pytest.mark.parametrize("problem", ["library-versions", "metrics-missing"])
def test_holdout_refuses_an_unverifiable_backtest_before_step_4(setup, problem) -> None:
    folder = _backtest_folder(setup)
    if problem == "library-versions":
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        record["library_versions"]["numpy"] = "0.0.0"
        (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")
    else:
        (folder / "metrics.csv").unlink()
    _refused_unchanged(setup)
    assert setup.paths.state() == "A"  # not consumed
