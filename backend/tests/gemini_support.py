"""Shared helpers for the spec 006 tests (test_ai_gemini.py, test_ai_budget.py).

Not a test module. Everything is local: fake transports, a fake clock, synthetic replies
and temporary usage folders. No socket is opened and no real key exists: the fake key is
built at run time so the repository secret scan never sees a key-shaped literal.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dealpilot.ai import CompletionRequest, Message, load_settings
from dealpilot.ai.budget import Ledger
from dealpilot.ai.gemini import GeminiProvider

FAKE_KEY = "fake-test-" + "g" * 16
MODEL = "gemini-3.5-flash-lite"
PRICE_IN = Decimal("0.30")
PRICE_OUT = Decimal("2.50")
CHECKED_ON = "2026-10-30"
START = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def gemini_env(usage_dir: Path, **overrides: str | None) -> dict[str, str]:
    """A complete, valid `gemini` environment; an override of None removes the variable."""
    env = {
        "DEALPILOT_AI_PROVIDER": "gemini",
        "DEALPILOT_GEMINI_API_KEY": FAKE_KEY,
        "DEALPILOT_GEMINI_MODEL": MODEL,
        "DEALPILOT_GEMINI_DATA_CLASS": "synthetic",
        "DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK": str(PRICE_IN),
        "DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK": str(PRICE_OUT),
        "DEALPILOT_GEMINI_PRICES_CHECKED_ON": CHECKED_ON,
        "DEALPILOT_AI_USAGE_DIR": str(usage_dir),
    }
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


class FakeTime:
    """UTC wall clock and monotonic clock that only move when told (or when slept on)."""

    def __init__(self, start: datetime = START) -> None:
        self.current = start
        self.mono = 0.0
        self.slept = 0.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.current += timedelta(seconds=seconds)


def reply(text: str | None = "Sales rose by 4% last month.", finish: str | None = "STOP",
          usage: tuple[int, int, int | None] | None = (10, 5, None),
          parts: list | None = None, **extra) -> bytes:
    """A synthetic `generateContent` 2xx body."""
    candidate: dict = {}
    if parts is not None:
        candidate["content"] = {"role": "model", "parts": parts}
    elif text is not None:
        candidate["content"] = {"role": "model", "parts": [{"text": text}]}
    if finish is not None:
        candidate["finishReason"] = finish
    data: dict = {"candidates": [candidate]}
    if usage is not None:
        prompt, output, thoughts = usage
        data["usageMetadata"] = {"promptTokenCount": prompt, "candidatesTokenCount": output,
                                 "totalTokenCount": prompt + output + (thoughts or 0)}
        if thoughts is not None:
            data["usageMetadata"]["thoughtsTokenCount"] = thoughts
    data.update(extra)
    return json.dumps(data).encode("utf-8")


def error_body(status: int, usage: tuple[int, int] | None = None) -> bytes:
    """A synthetic error body in the documented `generateContent` shape (F5)."""
    data: dict = {"error": {"code": status, "message": "internal secret detail",
                            "status": "INVALID_ARGUMENT"}}
    if usage is not None:
        data["usageMetadata"] = {"promptTokenCount": usage[0],
                                 "candidatesTokenCount": usage[1]}
    return json.dumps(data).encode("utf-8")


class FakeTransport:
    """Records each call; returns `(status, body)` or raises `error`. `on_call` runs first."""

    def __init__(self, status: int = 200, body: bytes | None = None,
                 error: BaseException | None = None, on_call=None) -> None:
        self.status = status
        self.body = reply() if body is None else body
        self.error = error
        self.on_call = on_call
        self.calls: list[tuple[str, str, dict, bytes, float]] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes,
                 timeout: float) -> tuple[int, bytes]:
        self.calls.append((method, url, headers, body, timeout))
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        return self.status, self.body


def make_provider(usage_dir: Path, transport, clock: FakeTime | None = None,
                  **overrides: str | None) -> GeminiProvider:
    settings = load_settings(gemini_env(usage_dir, **overrides))
    clock = clock or FakeTime()
    ledger = Ledger(settings.usage_dir, now=clock.now, monotonic=clock.monotonic,
                    sleep=clock.sleep)
    return GeminiProvider(settings, transport=transport, ledger=ledger)


def request(text: str = "Explain these sales figures.", max_tokens: int = 100,
            messages: list[Message] | None = None) -> CompletionRequest:
    return CompletionRequest(messages or [Message("user", text)], max_tokens=max_tokens)


# --------------------------------------------------------------------------- ledger files

def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def entry(created: datetime, state: str = "settled", reserved: str = "0.000550",
          cost: str | None = "0.000550", entry_id: str | None = None, **extra) -> dict:
    data = {
        "id": entry_id or f"seed-{created.timestamp()}-{state}",
        "provider": "gemini", "model": MODEL, "state": state,
        "created_at": iso(created), "updated_at": iso(created),
        "input_chars": 1000, "input_bytes": 1000, "max_output_tokens": 100,
        "reserved_usd": reserved,
        "price_input_usd_per_mtok": str(PRICE_IN), "price_output_usd_per_mtok": str(PRICE_OUT),
        "prices_checked_on": CHECKED_ON,
    }
    if cost is not None and state in ("settled", "not_billed"):
        data["cost_usd"] = cost
    data.update(extra)
    return data


def seed_ledger(usage_dir: Path, by_month: dict[str, list[dict]],
                updated_at: datetime = START - timedelta(days=60)) -> None:
    """Write valid ledger files and `state.json` for the given months."""
    usage_dir.mkdir(parents=True, exist_ok=True)
    months = sorted(by_month)
    for month, entries in by_month.items():
        write_json(usage_dir / f"ledger-{month}.json",
                   {"version": 1, "month": month, "entries": entries})
    write_json(usage_dir / "state.json",
               {"version": 1, "first_month": months[0], "latest_month": months[-1],
                "months": months, "updated_at": iso(updated_at)})


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def read_entries(usage_dir: Path, month: str = "2026-10") -> list[dict]:
    path = usage_dir / f"ledger-{month}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["entries"]
