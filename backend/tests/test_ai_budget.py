"""Spec 006 section 7: usage ledger, two-phase reservation, lock and usage folder.

Criteria AC-GEM-10 to 20 (the "B" file of spec 006 section 11). Fake transports, a fake
clock and temporary folders only; AC-GEM-16 runs two real subprocesses that share one
temporary usage folder. No socket is opened. Helpers are in gemini_support.py.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from dealpilot.ai import (
    AIBlockedError,
    AIBudgetError,
    AIConfigError,
    AIProviderError,
    AIRequestError,
    AIResponseError,
    AITimeoutError,
    get_provider,
    load_settings,
)
from dealpilot.ai import config as ai_config
from dealpilot.ai.budget import Ledger, Prices
from dealpilot.ai.meta import MAX_RESPONSE_BYTES
from gemini_support import (
    START,
    FakeTime,
    FakeTransport,
    entry,
    error_body,
    gemini_env,
    make_provider,
    read_entries,
    reply,
    request,
    seed_ledger,
    write_json,
)

OCT, SEP = "2026-10", "2026-09"
# "a" x 1,000 with max_tokens 100: 1,000 x 0.30 + 100 x 2.50 = 550 per 1M = 0.000550 USD.
TEXT = "a" * 1000
RESERVATION = Decimal("0.000550")
PRICES = Prices(Decimal("0.30"), Decimal("2.50"), datetime(2026, 10, 30).date())


def _call(provider, text: str = TEXT, max_tokens: int = 100):
    return provider.complete(request(text, max_tokens=max_tokens))


def _states(usage: Path, month: str = OCT) -> list[str]:
    return [e["state"] for e in read_entries(usage, month)]


# --------------------------------------------------------------------------- AC-GEM-10

def test_ac_gem_10_default_budget_exactly_reached(tmp_path) -> None:
    seed_ledger(tmp_path, {OCT: [entry(START - timedelta(days=2), cost="4.999450")]})
    transport = FakeTransport(body=reply(usage=(1000, 100, None)))  # costs its reservation
    provider = make_provider(tmp_path, transport)
    _call(provider)  # 4.999450 + 0.000550 = 5.000000: equal is allowed
    with pytest.raises(AIBudgetError, match="monthly budget"):
        _call(provider)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(("budget", "runs"), [("0.00055", True), ("0.000549", False),
                                              ("2", True), ("0", False), ("0.00", False)])
def test_ac_gem_10_budget_setting(tmp_path, budget, runs) -> None:
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport, DEALPILOT_AI_MONTHLY_BUDGET_USD=budget)
    if runs:
        _call(provider)
    else:
        with pytest.raises(AIBudgetError):
            _call(provider)
        assert read_entries(tmp_path) == []
    assert len(transport.calls) == int(runs)


@pytest.mark.parametrize("budget", ["5.01", "6", "-1", "-0.01", "five", "nan", "inf", "1e0"])
def test_ac_gem_10_invalid_budget_setting(tmp_path, budget) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_MONTHLY_BUDGET_USD"):
        load_settings(gemini_env(tmp_path, DEALPILOT_AI_MONTHLY_BUDGET_USD=budget))


@pytest.mark.parametrize("failing", ["open", "fsync", "replace", "state"])
def test_ac_gem_10_phase_1_write_failure(tmp_path, monkeypatch, failing) -> None:
    seed_ledger(tmp_path, {OCT: [entry(START - timedelta(days=1))]})
    before = (tmp_path / f"ledger-{OCT}.json").read_bytes()
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport)
    real_replace, real_fsync = os.replace, os.fsync

    def bad_replace(src, dst):
        if failing == "replace" or (failing == "state" and Path(dst).name == "state.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    def bad_fsync(fd):
        if failing == "fsync":
            raise OSError("disk full")
        return real_fsync(fd)

    monkeypatch.setattr(os, "replace", bad_replace)
    monkeypatch.setattr(os, "fsync", bad_fsync)
    if failing == "open":
        monkeypatch.setattr(Ledger, "_write_json",
                            lambda self, path, data: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(AIBudgetError, match="can't be written"):
        _call(provider)
    assert transport.calls == []
    monkeypatch.undo()
    if failing == "state":  # the reservation reached the ledger: it stays, never released
        assert _states(tmp_path) == ["settled", "reserved"]
    else:
        assert (tmp_path / f"ledger-{OCT}.json").read_bytes() == before
    assert "released" not in _states(tmp_path)


def test_ac_gem_10_mock_never_touches_the_ledger(tmp_path) -> None:
    usage = tmp_path / "usage"
    env = gemini_env(usage, DEALPILOT_AI_PROVIDER="mock")
    get_provider(load_settings(env)).complete(request())
    assert not usage.exists()


# --------------------------------------------------------------------------- AC-GEM-11

def test_ac_gem_11_default_hourly_limit(tmp_path) -> None:
    clock, transport = FakeTime(), FakeTransport()
    provider = make_provider(tmp_path, transport, clock)
    for _ in range(30):
        _call(provider)
        clock.advance(60)
    with pytest.raises(AIBudgetError, match="hourly call limit"):  # 30 in the last hour
        _call(provider)
    assert len(transport.calls) == 30


def test_ac_gem_11_lower_hourly_setting(tmp_path) -> None:
    clock, transport = FakeTime(), FakeTransport()
    provider = make_provider(tmp_path, transport, clock, DEALPILOT_AI_MAX_CALLS_PER_HOUR="10")
    for _ in range(10):
        _call(provider)
        clock.advance(1)
    with pytest.raises(AIBudgetError, match="hourly"):
        _call(provider)
    assert len(transport.calls) == 10


@pytest.mark.parametrize("value", ["31", "0", "-1", "1.5", "ten"])
def test_ac_gem_11_invalid_hourly_setting(tmp_path, value) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_MAX_CALLS_PER_HOUR"):
        load_settings(gemini_env(tmp_path, DEALPILOT_AI_MAX_CALLS_PER_HOUR=value))


@pytest.mark.parametrize(("age", "state", "runs"), [
    (3600, "settled", True),       # exactly 3,600 s old: no longer counts
    (3599, "settled", False),
    (0, "released", True),         # released entries never count
    (0, "not_billed", False),      # sent, so it counts
    (0, "kept", False),
])
def test_ac_gem_11_window_and_states(tmp_path, age, state, runs) -> None:
    created = START - timedelta(seconds=age)
    seed_ledger(tmp_path, {OCT: [entry(created, state=state, cost="0.000000",
                                       entry_id=f"e{i}") for i in range(30)]})
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport)
    if runs:
        _call(provider)
    else:
        with pytest.raises(AIBudgetError, match="hourly"):
            _call(provider)
    assert len(transport.calls) == int(runs)


# --------------------------------------------------------------------------- AC-GEM-12

def test_ac_gem_12_reservation_before_the_call(tmp_path) -> None:
    text = "Sales " + "\U0001F600" * 3  # 6 ASCII bytes + 3 emojis of 4 bytes = 18 bytes
    seen: list = []

    def spy() -> None:
        seen.append((read_entries(tmp_path), (tmp_path / "ledger.lock").exists()))

    transport = FakeTransport(on_call=spy)
    _call(make_provider(tmp_path, transport), text=text, max_tokens=200)
    [(entries, locked)] = seen
    [reserved] = entries
    assert reserved["state"] == "reserved"
    assert (reserved["input_chars"], reserved["input_bytes"]) == (9, 18)
    # 18 x 0.30 + 200 x 2.50 = 505.4 per 1M = 0.0005054, stored rounded up to 6 decimals
    assert reserved["reserved_usd"] == "0.000506"
    assert not locked
    assert len(transport.calls) == 1
    assert all("countTokens" not in call[1] for call in transport.calls)


# --------------------------------------------------------------------------- AC-GEM-13

@pytest.mark.parametrize("body", [
    reply(usage=(40, 10, 5)),
    reply(finish="SAFETY", usage=(40, 10, 5)),
    reply(text="  ", usage=(40, 10, 5)),
])
def test_ac_gem_13_settled_with_real_cost(tmp_path, body) -> None:
    try:
        _call(make_provider(tmp_path, FakeTransport(body=body)))
    except (AIBlockedError, AIResponseError):
        pass  # the reply is refused, but the usage was billed
    [settled] = read_entries(tmp_path)
    assert settled["state"] == "settled"
    assert (settled["prompt_tokens"], settled["output_tokens"], settled["thoughts_tokens"]) == (
        40, 10, 5)
    # 40 x 0.30 + (10 + 5) x 2.50 = 49.5 per 1M = 0.0000495 -> 0.000050 (6 decimals, up)
    assert settled["cost_usd"] == "0.000050"


def test_ac_gem_13_settled_only_after_a_durable_write(tmp_path, monkeypatch) -> None:
    real_replace = os.replace

    def fail_after_call():
        monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError()))

    result = _call(make_provider(tmp_path, FakeTransport(on_call=fail_after_call)))
    monkeypatch.setattr(os, "replace", real_replace)
    assert result.text  # the reply is still returned
    assert _states(tmp_path) == ["reserved"]


# --------------------------------------------------------------------------- AC-GEM-14

def test_ac_gem_14_complete_400_with_usage_is_not_billed(tmp_path) -> None:
    transport = FakeTransport(status=400, body=error_body(400, usage=(1000, 0)))
    provider = make_provider(tmp_path, transport, DEALPILOT_AI_MONTHLY_BUDGET_USD="0.00055",
                             DEALPILOT_AI_MAX_CALLS_PER_HOUR="2")
    with pytest.raises(AIProviderError):
        _call(provider)
    [stored] = read_entries(tmp_path)
    assert (stored["state"], stored["cost_usd"], stored["prompt_tokens"]) == (
        "not_billed", "0.000000", 1000)
    # Counts 0 in the month total: a second reservation of the whole budget still fits.
    transport.status, transport.body = 200, reply(usage=(1000, 100, None))
    _call(provider)
    # Counts 1 in the hourly count: with a limit of 2, a third call is refused.
    with pytest.raises(AIBudgetError, match="hourly"):
        _call(provider)


KEPT_CASES = {
    "500 with usage is not_billed": (500, error_body(500, usage=(5, 0)), "not_billed"),
    "400 without usage": (400, error_body(400), "kept"),
    "500 invalid usage": (500, json.dumps({"usageMetadata": {"promptTokenCount": -1}})
                          .encode(), "kept"),
    "400 not json": (400, b"<html>bad gateway</html>", "kept"),
    "500 over 1 MiB": (500, b" " * (MAX_RESPONSE_BYTES + 1), "kept"),
    "2xx without usage": (200, reply(usage=None), "kept"),
    "2xx invalid usage": (200, reply(usage=(10, -5, None)), "kept"),
    "2xx text usage": (200, reply(usage=(10, 5, None)).replace(b'"promptTokenCount": 10',
                                                              b'"promptTokenCount": 10.5'),
                       "kept"),
    "2xx not json": (200, b"{truncated", "kept"),
    "2xx over 1 MiB": (200, b" " * (MAX_RESPONSE_BYTES + 1), "kept"),
    "503": (503, error_body(503, usage=(5, 0)), "kept"),
    "504": (504, error_body(504), "kept"),
    "other 4xx with usage": (404, error_body(404, usage=(5, 0)), "kept"),
}


@pytest.mark.parametrize("case", list(KEPT_CASES))
def test_ac_gem_14_reconciliation_states(tmp_path, case) -> None:
    status, body, state = KEPT_CASES[case]
    try:
        _call(make_provider(tmp_path, FakeTransport(status=status, body=body)))
    except (AIProviderError, AIResponseError, AIConfigError):
        pass
    [stored] = read_entries(tmp_path)
    assert stored["state"] == state
    if state == "kept":
        assert stored["reserved_usd"] == str(RESERVATION)
        assert "cost_usd" not in stored


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionResetError(), socket.gaierror()])
def test_ac_gem_14_failures_in_transit_are_kept(tmp_path, error) -> None:
    with pytest.raises((AITimeoutError, AIProviderError)):
        _call(make_provider(tmp_path, FakeTransport(error=error)))
    assert _states(tmp_path) == ["kept"]


def test_ac_gem_14_refused_requests_leave_no_entry(tmp_path) -> None:
    """Released is only for requests never handed to the transport; a request refused
    before the ledger leaves no entry at all, and no sent request is ever released."""
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport)
    with pytest.raises(AIRequestError):  # refused before the ledger
        _call(provider, max_tokens=2000)
    assert read_entries(tmp_path) == []
    _call(provider)
    assert "released" not in _states(tmp_path)


# --------------------------------------------------------------------------- AC-GEM-15

def test_ac_gem_15_crash_after_phase_1(tmp_path) -> None:
    settings = load_settings(gemini_env(tmp_path, DEALPILOT_AI_MONTHLY_BUDGET_USD="0.00055"))
    clock = FakeTime()
    ledger = Ledger(settings.usage_dir, now=clock.now)
    ledger.reserve(provider="gemini", model=settings.gemini_model, input_chars=1000,
                   input_bytes=1000, max_output_tokens=100, prices=PRICES,
                   budget_usd=settings.monthly_budget_usd, max_calls_per_hour=30)
    # The process "stops" here: phase 3 never runs.
    transport = FakeTransport()
    with pytest.raises(AIBudgetError, match="monthly budget"):
        _call(make_provider(tmp_path, transport, clock,
                            DEALPILOT_AI_MONTHLY_BUDGET_USD="0.00055"))
    assert transport.calls == []
    assert _states(tmp_path) == ["reserved"]


def test_ac_gem_15_failure_before_replace_keeps_previous_ledger(tmp_path, monkeypatch) -> None:
    seed_ledger(tmp_path, {OCT: [entry(START - timedelta(days=1))]})
    before = (tmp_path / f"ledger-{OCT}.json").read_bytes()
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError()))
    transport = FakeTransport()
    with pytest.raises(AIBudgetError):
        _call(make_provider(tmp_path, transport))
    monkeypatch.undo()
    assert (tmp_path / f"ledger-{OCT}.json").read_bytes() == before
    orphans = [p.name for p in tmp_path.iterdir() if ".tmp-" in p.name]
    assert len(orphans) == 1
    _call(make_provider(tmp_path, transport))  # the next phase 1 removes the orphan
    assert [p for p in tmp_path.iterdir() if ".tmp-" in p.name] == []


def test_ac_gem_15_lock_busy_in_phase_3(tmp_path) -> None:
    clock = FakeTime()
    lock = tmp_path / "ledger.lock"
    transport = FakeTransport(on_call=lambda: lock.write_text("held by another process"))
    result = _call(make_provider(tmp_path, transport, clock))
    assert result.text
    assert _states(tmp_path) == ["reserved"]
    assert clock.slept >= 5.0
    assert lock.read_text() == "held by another process"  # never removed automatically
    lock.unlink()
    with pytest.raises(AIBudgetError, match="monthly budget"):  # still counted as spent
        _call(make_provider(tmp_path, transport, clock,
                            DEALPILOT_AI_MONTHLY_BUDGET_USD="0.001"))


def test_ac_gem_15_ledger_not_trusted_in_phase_3(tmp_path) -> None:
    path = tmp_path / f"ledger-{OCT}.json"
    transport = FakeTransport(on_call=lambda: path.write_text("{ corrupted"))
    result = _call(make_provider(tmp_path, transport))
    assert result.text
    assert path.read_text() == "{ corrupted"  # nothing written
    second = FakeTransport()
    with pytest.raises(AIBudgetError, match="person must check"):
        _call(make_provider(tmp_path, second))
    assert second.calls == []


@pytest.mark.parametrize("body", [reply(), reply(finish="SAFETY")])
def test_ac_gem_15_write_failure_in_phase_3(tmp_path, monkeypatch, body) -> None:
    def fail_writes():
        monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("io")))

    transport = FakeTransport(body=body, on_call=fail_writes)
    provider = make_provider(tmp_path, transport)
    if b"SAFETY" in body:
        with pytest.raises(AIBlockedError):  # the response's own error, not a network one
            _call(provider)
    else:
        assert _call(provider).text == "Sales rose by 4% last month."
    monkeypatch.undo()
    assert len(transport.calls) == 1
    assert _states(tmp_path) == ["reserved"]
    _call(make_provider(tmp_path, FakeTransport()))  # ledger still valid: next call runs


def test_ac_gem_15_invalid_ledger_after_phase_3_failure_blocks(tmp_path, monkeypatch) -> None:
    path = tmp_path / f"ledger-{OCT}.json"

    def break_ledger():
        path.write_text("[]")  # a bad shape, as a half-written repair could leave

    _call(make_provider(tmp_path, FakeTransport(on_call=break_ledger)))
    second = FakeTransport()
    with pytest.raises(AIBudgetError):
        _call(make_provider(tmp_path, second))
    assert second.calls == []


# --------------------------------------------------------------------------- AC-GEM-16

SUBPROCESS_SCRIPT = """
import json, os, sys, time
from pathlib import Path
from dealpilot.ai import AIBudgetError, CompletionRequest, Message, load_settings
from dealpilot.ai.gemini import GeminiProvider
env, calls = json.loads(sys.argv[1]), Path(sys.argv[2])
body = json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]},
                                   "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 1000,
                                     "candidatesTokenCount": 100}}).encode()
def transport(method, url, headers, data, timeout):
    (calls / f"call-{os.getpid()}").write_text("x")
    time.sleep(0.5)
    return 200, body
provider = GeminiProvider(load_settings(env), transport=transport)
try:
    provider.complete(CompletionRequest([Message("user", "a" * 1000)], max_tokens=100))
    print("ok")
except AIBudgetError:
    print("budget")
"""


def test_ac_gem_16_two_processes_one_budget(tmp_path) -> None:
    calls = tmp_path / "calls"
    calls.mkdir()
    env = gemini_env(tmp_path / "usage", DEALPILOT_AI_MONTHLY_BUDGET_USD="0.00055")
    procs = [subprocess.Popen([sys.executable, "-c", SUBPROCESS_SCRIPT, json.dumps(env),
                               str(calls)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) for _ in range(2)]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        outputs.append(out.strip())
    assert sorted(outputs) == ["budget", "ok"]
    assert len(list(calls.iterdir())) == 1
    month = datetime.now(UTC).strftime("%Y-%m")
    assert [e["state"] for e in read_entries(tmp_path / "usage", month)] == ["settled"]


# --------------------------------------------------------------------------- AC-GEM-17

def test_ac_gem_17_held_lock_refuses_after_5_seconds(tmp_path) -> None:
    tmp_path.mkdir(exist_ok=True)
    lock = tmp_path / "ledger.lock"
    lock.write_text('{"pid": 1, "host": "elsewhere", "created_at": "2020-01-01", "phase": 1}')
    old = lock.read_bytes()
    clock, transport = FakeTime(), FakeTransport()
    with pytest.raises(AIBudgetError, match="usage ledger is busy"):
        _call(make_provider(tmp_path, transport, clock))
    assert transport.calls == []
    assert 5.0 <= clock.slept < 5.2
    assert lock.read_bytes() == old  # an old lock is never deleted automatically


def test_ac_gem_17_lock_content(tmp_path, monkeypatch) -> None:
    seen: list[dict] = []
    real_write = Ledger._write_json

    def spy(self, path, data):
        seen.append(json.loads((self.folder / "ledger.lock").read_text()))
        return real_write(self, path, data)

    monkeypatch.setattr(Ledger, "_write_json", spy)
    clock = FakeTime()
    _call(make_provider(tmp_path, FakeTransport(), clock))
    phases = sorted({info["phase"] for info in seen})
    assert phases == [1, 3]
    for info in seen:
        assert info["pid"] == os.getpid()
        assert info["host"] == socket.gethostname()
        assert datetime.fromisoformat(info["created_at"]) == clock.current
    assert not (tmp_path / "ledger.lock").exists()


# --------------------------------------------------------------------------- AC-GEM-18

def test_ac_gem_18_utc_month_boundary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")  # UTC+14: never used by the ledger
    kiritimati = timezone(timedelta(hours=14))
    clock = FakeTime(datetime(2026, 11, 1, 13, 59, 30, tzinfo=kiritimati))  # 23:59:30 UTC
    transport = FakeTransport()
    provider = make_provider(tmp_path, transport, clock, DEALPILOT_AI_MAX_CALLS_PER_HOUR="2")
    settings = provider.settings
    Ledger(settings.usage_dir, now=clock.now).reserve(  # stays reserved in October
        provider="gemini", model=settings.gemini_model, input_chars=1, input_bytes=1,
        max_output_tokens=1, prices=PRICES, budget_usd=Decimal(5), max_calls_per_hour=30)
    clock.advance(40)  # 00:00:10 UTC on 1 November
    _call(provider)
    assert _states(tmp_path, "2026-10") == ["reserved"]
    assert _states(tmp_path, "2026-11") == ["settled"]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["months"] == ["2026-10", "2026-11"]
    clock.advance(10)
    with pytest.raises(AIBudgetError, match="hourly"):  # the window spans both files
        _call(provider)


# --------------------------------------------------------------------------- AC-GEM-19

def _corrupt(usage: Path, month: str, case: str) -> None:
    path = usage / f"ledger-{month}.json"
    data = json.loads(path.read_text())
    first = data["entries"][0]
    if case == "future entry time":
        first["created_at"] = (START + timedelta(hours=1)).isoformat()
        if month == SEP:
            first["created_at"] = (START + timedelta(days=60)).isoformat()
    elif case == "invalid json":
        path.write_text("{oops")
        return
    elif case == "wrong shape":
        data = {"entries": "none"}
    elif case == "unknown state":
        first["state"] = "maybe"
    elif case == "negative amount":
        first["reserved_usd"] = "-0.000550"
    elif case == "settled without cost":
        first.pop("cost_usd")
    elif case == "reserved without reservation":
        first["state"] = "reserved"
        first.pop("reserved_usd")
    elif case == "kept with bad reservation":
        first["state"] = "kept"
        first["reserved_usd"] = "lots"
    elif case == "unreadable file":
        path.unlink()
        path.mkdir()
        return
    elif case == "missing file":
        path.unlink()
        return
    write_json(path, data)


CORRUPTIONS = ["future entry time", "invalid json", "wrong shape", "unknown state",
               "negative amount", "settled without cost", "reserved without reservation",
               "kept with bad reservation", "unreadable file", "missing file"]


@pytest.mark.parametrize("month", [OCT, SEP])
@pytest.mark.parametrize("case", CORRUPTIONS)
def test_ac_gem_19_untrusted_ledger(tmp_path, month, case) -> None:
    seed_ledger(tmp_path, {SEP: [entry(datetime(2026, 9, 30, 12, tzinfo=UTC))],
                           OCT: [entry(START - timedelta(days=1))]})
    _corrupt(tmp_path, month, case)
    transport = FakeTransport()
    with pytest.raises(AIBudgetError):
        _call(make_provider(tmp_path, transport))
    assert transport.calls == []


def test_ac_gem_19_state_time_later_than_now(tmp_path) -> None:
    seed_ledger(tmp_path, {OCT: [entry(START - timedelta(days=1))]},
                updated_at=START + timedelta(minutes=5))
    transport = FakeTransport()
    with pytest.raises(AIBudgetError):
        _call(make_provider(tmp_path, transport))
    assert transport.calls == []


def test_ac_gem_19_seeded_ledger_is_valid(tmp_path) -> None:
    """Control for the cases above: the same seed, untouched, lets the call run."""
    seed_ledger(tmp_path, {SEP: [entry(datetime(2026, 9, 30, 12, tzinfo=UTC))],
                           OCT: [entry(START - timedelta(days=1))]})
    _call(make_provider(tmp_path, FakeTransport()))


# --------------------------------------------------------------------------- AC-GEM-20

@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    """A temporary fake project root with a data/raw folder."""
    fake = tmp_path / "project"
    (fake / "data" / "raw").mkdir(parents=True)
    monkeypatch.setattr(ai_config, "_find_project_root", lambda: fake)
    return fake


def _usage_env(root: Path, usage: str | None, data: str | None = None) -> dict[str, str]:
    env = gemini_env(Path("unused"), DEALPILOT_AI_USAGE_DIR=usage)
    if data is not None:
        env["DEALPILOT_DATA_DIR"] = data
    return env


def test_ac_gem_20_default_usage_folder(root) -> None:
    settings = load_settings(_usage_env(root, None))
    assert settings.usage_dir == (root / "data" / "ai-usage").resolve()
    assert not settings.usage_dir.exists()


REFUSED_USAGE = ["data/raw", "data/raw/ledgers", "data/x/../raw", "data", ".",
                 "data/raw/../raw/sub"]


@pytest.mark.parametrize("usage", REFUSED_USAGE)
def test_ac_gem_20_near_data_raw(root, usage) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_USAGE_DIR") as info:
        load_settings(_usage_env(root, usage))
    assert str(root) not in str(info.value)


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are a Windows rule")
def test_ac_gem_20_case_on_windows(root) -> None:
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_USAGE_DIR"):
        load_settings(_usage_env(root, "DATA/RAW"))


def test_ac_gem_20_configured_data_folder(root, tmp_path) -> None:
    data = tmp_path / "elsewhere" / "sales"
    data.mkdir(parents=True)
    for usage in (data, data / "usage", data.parent):
        with pytest.raises(AIConfigError, match="DEALPILOT_AI_USAGE_DIR") as info:
            load_settings(_usage_env(root, str(usage), str(data)))
        assert str(tmp_path) not in str(info.value)
    ok = load_settings(_usage_env(root, str(tmp_path / "usage"), str(data)))
    assert ok.usage_dir == (tmp_path / "usage").resolve()
    # Relative data folders join the root, like the API (spec 002 section 3.2).
    with pytest.raises(AIConfigError):
        load_settings(_usage_env(root, "custom/usage", "custom"))


def test_ac_gem_20_usage_folder_is_a_file(root, tmp_path) -> None:
    file = tmp_path / "a-file"
    file.write_text("x")
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_USAGE_DIR"):
        load_settings(_usage_env(root, str(file)))


def test_ac_gem_20_link_to_data_raw(root, tmp_path) -> None:
    link = tmp_path / "innocent-looking"
    target = root / "data" / "raw"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("links can't be created here")
        try:
            import _winapi  # junctions need no special right on Windows

            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, OSError):
            pytest.skip("links and junctions can't be created here")
    with pytest.raises(AIConfigError, match="DEALPILOT_AI_USAGE_DIR"):
        load_settings(_usage_env(root, str(link / "usage")))


@pytest.mark.parametrize("data", [None, "absolute"])
def test_ac_gem_20_no_project_root(tmp_path, monkeypatch, data) -> None:
    monkeypatch.setattr(ai_config, "_find_project_root", lambda: None)
    data_dir = str(tmp_path / "sales") if data else None
    with pytest.raises(AIConfigError, match="project root not found"):
        load_settings(_usage_env(tmp_path, str(tmp_path / "usage"), data_dir))


AMBIGUOUS = ["usage\0x", " usage", "usage ", "~/usage", "~"]
if os.name == "nt":
    AMBIGUOUS += ["C:usage", "\\usage"]


@pytest.mark.parametrize("var", ["DEALPILOT_AI_USAGE_DIR", "DEALPILOT_DATA_DIR"])
@pytest.mark.parametrize("value", AMBIGUOUS)
def test_ac_gem_20_ambiguous_values(root, tmp_path, var, value) -> None:
    env = _usage_env(root, str(tmp_path / "usage")) | {var: value}
    with pytest.raises(AIConfigError, match=var) as info:
        load_settings(env)
    assert str(tmp_path) not in str(info.value)
    assert not (tmp_path / "usage").exists()


@pytest.mark.parametrize("provider", ["mock", "meta"])
def test_ac_gem_20_mock_and_meta_ignore_usage_folder(root, provider) -> None:
    env = {"DEALPILOT_AI_PROVIDER": provider, "DEALPILOT_AI_USAGE_DIR": "data/raw",
           "DEALPILOT_DATA_DIR": " ambiguous", "DEALPILOT_META_API_KEY": "fake-test-" + "m" * 16}
    assert load_settings(env).usage_dir is None
