"""Usage ledger and two-phase cost reservation for paid providers (spec 006 section 7).

Phase 1 (`Ledger.reserve`) runs under an exclusive lock before the network call and writes
a `reserved` entry. Phase 3 (`Ledger.finish`) runs under the lock after the call and moves
the entry to `settled`, `not_billed`, `kept` or `released`. Every doubt fails closed: a
problem in phase 1 refuses the call (`AIBudgetError`); a problem in phase 3 leaves the entry
`reserved`, which keeps counting at its reservation. Locks are never removed automatically.

Files in the usage folder: `ledger-YYYY-MM.json` (one per UTC month), `state.json` and,
while a phase runs, `ledger.lock`. Prompts and replies are never stored.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from dealpilot.ai.errors import AIBudgetError

LOCK_NAME = "ledger.lock"
STATE_NAME = "state.json"
LOCK_WAIT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.1
HOUR = timedelta(seconds=3600)
MICRO = Decimal("0.000001")
PER_MTOK = Decimal(1_000_000)
STATES = ("reserved", "settled", "kept", "not_billed", "released")
VERSION = 1

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_MONEY = re.compile(r"[0-9]+\.[0-9]{6}")
_TEMP = re.compile(r"(ledger-\d{4}-\d{2}\.json|state\.json)\.tmp-.+")
_INT_FIELDS = ("input_chars", "input_bytes", "max_output_tokens")
_TOKEN_FIELDS = ("prompt_tokens", "output_tokens", "thoughts_tokens")


@dataclass(frozen=True)
class Prices:
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    checked_on: date


@dataclass(frozen=True)
class Reservation:
    entry_id: str
    month: str
    reserved_usd: Decimal


@dataclass(frozen=True)
class Outcome:
    """What phase 3 learned. `state` is `settled`, `not_billed`, `kept` or `released`."""

    state: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None


def money(value: Decimal) -> Decimal:
    """Round up to 6 decimals, so a stored cost or reservation is never below the real one."""
    return value.quantize(MICRO, rounding=ROUND_CEILING)


def reservation_usd(input_bytes: int, max_tokens: int, prices: Prices) -> Decimal:
    """Section 7.3 step 3 (D11): UTF-8 input bytes and `max_tokens`, per 1M tokens."""
    return money((input_bytes * prices.input_usd_per_mtok
                  + max_tokens * prices.output_usd_per_mtok) / PER_MTOK)


def cost_usd(prompt_tokens: int, output_tokens: int, thoughts_tokens: int,
             prices: Prices) -> Decimal:
    """Section 7.3 phase 3: prompt x input price + (candidates + thoughts) x output price."""
    return money((prompt_tokens * prices.input_usd_per_mtok
                  + (output_tokens + thoughts_tokens) * prices.output_usd_per_mtok) / PER_MTOK)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _month_of(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m")


def _previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


class _Invalid(Exception):
    """The ledger can't be trusted (section 7.3, step 1)."""


class Ledger:
    """One usage folder. Clocks and sleep are injectable for tests."""

    def __init__(self, folder: Path, *, now: Callable[[], datetime] | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.folder = Path(folder)
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleep = sleep

    # ----------------------------------------------------------------- public API

    def reserve(self, *, provider: str, model: str, input_chars: int, input_bytes: int,
                max_output_tokens: int, prices: Prices, budget_usd: Decimal,
                max_calls_per_hour: int) -> Reservation:
        """Phase 1. Raises `AIBudgetError`; then the transport must not be called."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise AIBudgetError("usage ledger folder can't be created",
                                provider=provider) from None
        self._lock(phase=1, provider=provider)
        try:
            return self._reserve_locked(provider, model, input_chars, input_bytes,
                                        max_output_tokens, prices, budget_usd,
                                        max_calls_per_hour)
        finally:
            self._unlock()

    def finish(self, reservation: Reservation, outcome: Outcome) -> bool:
        """Phase 3. Never raises: on any problem the entry stays `reserved` (fail closed).

        Returns True only when the new state was durably written.
        """
        try:
            self._lock(phase=3, provider=None)
        except AIBudgetError:
            return False  # lock busy: nothing is written
        try:
            return self._finish_locked(reservation, outcome)
        except (_Invalid, OSError, ValueError):
            return False  # ledger not trusted, or write failure (D17)
        finally:
            self._unlock()

    # ----------------------------------------------------------------- lock

    def _lock(self, *, phase: int, provider: str | None) -> None:
        path = self.folder / LOCK_NAME
        start = self._monotonic()
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._monotonic() - start >= LOCK_WAIT_SECONDS:
                    raise AIBudgetError("usage ledger is busy", provider=provider) from None
                self._sleep(LOCK_RETRY_SECONDS)
                continue
            except OSError:
                raise AIBudgetError("usage ledger lock can't be created",
                                    provider=provider) from None
            break
        info = {"pid": os.getpid(), "host": socket.gethostname(),
                "created_at": _iso(self._now()), "phase": phase}
        try:
            os.write(fd, json.dumps(info).encode("utf-8"))
        finally:
            os.close(fd)

    def _unlock(self) -> None:
        # Only our own lock, at the end of our own phase. If this fails the lock stays, and
        # every later paid call is refused until a person removes it (section 7.4).
        try:
            os.remove(self.folder / LOCK_NAME)
        except OSError:
            pass

    # ----------------------------------------------------------------- phase 1

    def _reserve_locked(self, provider: str, model: str, input_chars: int, input_bytes: int,
                        max_output_tokens: int, prices: Prices, budget_usd: Decimal,
                        max_calls_per_hour: int) -> Reservation:
        now = self._now()
        month = _month_of(now)
        try:
            self._remove_orphans()
            state, current, previous = self._load(now)
        except (_Invalid, OSError, ValueError):
            raise AIBudgetError("usage ledger can't be trusted; a person must check it",
                                provider=provider) from None

        recent = [e for e in current + previous if e["state"] != "released"
                  and now - HOUR < datetime.fromisoformat(e["created_at"]) <= now]
        if len(recent) >= max_calls_per_hour:
            raise AIBudgetError("hourly call limit reached", provider=provider)

        reserved = reservation_usd(input_bytes, max_output_tokens, prices)
        if _month_total(current) + reserved > budget_usd:
            raise AIBudgetError("monthly budget would be exceeded", provider=provider)

        entry = {
            "id": secrets.token_hex(16), "provider": provider, "model": model,
            "state": "reserved", "created_at": _iso(now), "updated_at": _iso(now),
            "input_chars": input_chars, "input_bytes": input_bytes,
            "max_output_tokens": max_output_tokens, "reserved_usd": str(reserved),
            "price_input_usd_per_mtok": str(prices.input_usd_per_mtok),
            "price_output_usd_per_mtok": str(prices.output_usd_per_mtok),
            "prices_checked_on": prices.checked_on.isoformat(),
        }
        months = sorted(set(state["months"]) | {month})
        new_state = {"version": VERSION, "first_month": months[0], "latest_month": months[-1],
                     "months": months, "updated_at": _iso(now)}
        try:  # D17: a failure here refuses the call; nothing is tidied up
            self._write_json(self._ledger_path(month),
                             {"version": VERSION, "month": month, "entries": current + [entry]})
            self._write_json(self.folder / STATE_NAME, new_state)
        except OSError:
            raise AIBudgetError("usage ledger can't be written", provider=provider) from None
        return Reservation(entry["id"], month, reserved)

    # ----------------------------------------------------------------- phase 3

    def _finish_locked(self, reservation: Reservation, outcome: Outcome) -> bool:
        now = self._now()
        state, current, previous = self._load(now)
        if reservation.month == _month_of(now):
            entries = current
        elif reservation.month == _previous_month(_month_of(now)):
            entries = previous
        else:
            entries = self._read_ledger(reservation.month, now, state)
        matches = [e for e in entries if e["id"] == reservation.entry_id]
        if len(matches) != 1 or matches[0]["state"] != "reserved":
            return False
        entry = matches[0]
        prices = Prices(Decimal(entry["price_input_usd_per_mtok"]),
                        Decimal(entry["price_output_usd_per_mtok"]),
                        date.fromisoformat(entry["prices_checked_on"]))
        entry["state"] = outcome.state
        entry["updated_at"] = _iso(now)
        if outcome.state in ("settled", "not_billed"):
            entry["prompt_tokens"] = outcome.prompt_tokens
            entry["output_tokens"] = outcome.output_tokens
            entry["thoughts_tokens"] = outcome.thoughts_tokens
        if outcome.state == "settled":
            entry["cost_usd"] = str(cost_usd(outcome.prompt_tokens, outcome.output_tokens,
                                             outcome.thoughts_tokens, prices))
        elif outcome.state == "not_billed":
            entry["cost_usd"] = str(money(Decimal(0)))  # F9: usage data only, not billed
        self._write_json(self._ledger_path(reservation.month),
                         {"version": VERSION, "month": reservation.month, "entries": entries})
        return True

    # ----------------------------------------------------------------- files

    def _ledger_path(self, month: str) -> Path:
        return self.folder / f"ledger-{month}.json"

    def _remove_orphans(self) -> None:
        for path in self.folder.iterdir():
            if _TEMP.fullmatch(path.name):
                path.unlink()

    def _write_json(self, path: Path, data: dict) -> None:
        """Temporary file, flush, fsync, then `os.replace` (the only commit)."""
        temp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        with open(temp, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if os.name != "nt":  # best effort; not available on Windows (section 7.4)
            try:
                fd = os.open(self.folder, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass

    def _load(self, now: datetime) -> tuple[dict, list[dict], list[dict]]:
        """Section 7.3 step 1: `state.json`, this month's and last month's ledgers."""
        state = self._read_state(now)
        month = _month_of(now)
        return (state, self._read_ledger(month, now, state),
                self._read_ledger(_previous_month(month), now, state))

    def _read_state(self, now: datetime) -> dict:
        path = self.folder / STATE_NAME
        if not path.exists():
            if any(p.name.startswith("ledger-") and p.name.endswith(".json")
                   for p in self.folder.iterdir()):
                raise _Invalid("ledger files without state.json")
            return {"months": []}
        data = _read_json(path)
        months = data.get("months") if isinstance(data, dict) else None
        if (not isinstance(months, list) or not months
                or not all(isinstance(m, str) and _MONTH.fullmatch(m) for m in months)
                or months != sorted(set(months))
                or data.get("version") != VERSION
                or data.get("first_month") != months[0]
                or data.get("latest_month") != months[-1]
                or months[-1] > _month_of(now)):
            raise _Invalid("bad state.json")
        _check_time(data.get("updated_at"), now)
        return data

    def _read_ledger(self, month: str, now: datetime, state: dict) -> list[dict]:
        path = self._ledger_path(month)
        written = month in state["months"]
        if not path.exists():
            if written:
                raise _Invalid("a month in state.json has no ledger file")
            return []
        if not written:
            raise _Invalid("a ledger file is not in state.json")
        data = _read_json(path)
        if (not isinstance(data, dict) or data.get("version") != VERSION
                or data.get("month") != month or not isinstance(data.get("entries"), list)):
            raise _Invalid("bad ledger file")
        entries = data["entries"]
        for entry in entries:
            _check_entry(entry, month, now)
        if len({e["id"] for e in entries}) != len(entries):
            raise _Invalid("duplicate entry id")
        return entries


def _read_json(path: Path) -> object:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _Invalid("unreadable file") from None


def _check_time(value: object, now: datetime) -> datetime:
    if not isinstance(value, str):
        raise _Invalid("bad time")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise _Invalid("bad time") from None
    if moment.tzinfo is None or moment > now:
        raise _Invalid("time missing a zone or later than now")
    return moment


def _is_money(value: object) -> bool:
    return isinstance(value, str) and bool(_MONEY.fullmatch(value))


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_entry(entry: object, month: str, now: datetime) -> None:
    """Section 7.2: shape, state, amounts, times; fail closed on anything odd."""
    if not isinstance(entry, dict):
        raise _Invalid("entry is not an object")
    if entry.get("state") not in STATES:
        raise _Invalid("unknown state")
    for key in ("id", "provider", "model"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise _Invalid("bad entry field")
    created = _check_time(entry.get("created_at"), now)
    _check_time(entry.get("updated_at"), now)
    if _month_of(created) != month:
        raise _Invalid("entry in the wrong month file")
    if not all(_is_count(entry.get(key)) for key in _INT_FIELDS):
        raise _Invalid("bad entry count")
    for key in ("reserved_usd", "price_input_usd_per_mtok", "price_output_usd_per_mtok"):
        if not isinstance(entry.get(key), str):
            raise _Invalid("bad amount")
    if not _is_money(entry["reserved_usd"]):  # also refuses a negative amount
        raise _Invalid("bad reserved_usd")
    for key in ("price_input_usd_per_mtok", "price_output_usd_per_mtok"):
        if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", entry[key]) or Decimal(entry[key]) <= 0:
            raise _Invalid("bad price")
    try:
        date.fromisoformat(entry.get("prices_checked_on"))
    except (TypeError, ValueError):
        raise _Invalid("bad price date") from None
    if "cost_usd" in entry and not _is_money(entry["cost_usd"]):
        raise _Invalid("bad cost_usd")
    if entry["state"] == "settled" and "cost_usd" not in entry:
        raise _Invalid("settled entry without cost_usd")
    if entry["state"] == "not_billed" and entry.get("cost_usd") != str(money(Decimal(0))):
        raise _Invalid("not_billed entry with a cost")
    for key in _TOKEN_FIELDS:
        if key in entry and entry[key] is not None and not _is_count(entry[key]):
            raise _Invalid("bad token count")


def _month_total(entries: list[dict]) -> Decimal:
    """Section 7.2: settled at cost; reserved and kept at their reservation; others 0."""
    total = Decimal(0)
    for entry in entries:
        if entry["state"] == "settled":
            total += Decimal(entry["cost_usd"])
        elif entry["state"] in ("reserved", "kept"):
            total += Decimal(entry["reserved_usd"])
    return total
