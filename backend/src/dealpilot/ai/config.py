"""AI settings from environment variables (spec 004 section 4.3, spec 006 section 5).

Only the process environment is read; no `.env` file is loaded. A provider's API key is read
only when that provider is selected, and it is kept in a wrapper that never prints it. The
Gemini settings and the paid-provider limits are read only when the provider is `gemini`.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from dealpilot.ai.errors import AIConfigError

PROVIDER_VAR = "DEALPILOT_AI_PROVIDER"
MODEL_VAR = "DEALPILOT_AI_MODEL"
TIMEOUT_VAR = "DEALPILOT_AI_TIMEOUT_SECONDS"
META_BASE_URL_VAR = "DEALPILOT_META_BASE_URL"
META_KEY_VAR = "DEALPILOT_META_API_KEY"

GEMINI_KEY_VAR = "DEALPILOT_GEMINI_API_KEY"
GEMINI_MODEL_VAR = "DEALPILOT_GEMINI_MODEL"
GEMINI_BASE_URL_VAR = "DEALPILOT_GEMINI_BASE_URL"
GEMINI_DATA_CLASS_VAR = "DEALPILOT_GEMINI_DATA_CLASS"
GEMINI_PRICE_INPUT_VAR = "DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK"
GEMINI_PRICE_OUTPUT_VAR = "DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK"
GEMINI_PRICES_DATE_VAR = "DEALPILOT_GEMINI_PRICES_CHECKED_ON"
MAX_INPUT_CHARS_VAR = "DEALPILOT_AI_MAX_INPUT_CHARS"
MAX_OUTPUT_TOKENS_VAR = "DEALPILOT_AI_MAX_OUTPUT_TOKENS"
MONTHLY_BUDGET_VAR = "DEALPILOT_AI_MONTHLY_BUDGET_USD"
MAX_CALLS_VAR = "DEALPILOT_AI_MAX_CALLS_PER_HOUR"
USAGE_DIR_VAR = "DEALPILOT_AI_USAGE_DIR"
DATA_DIR_VAR = "DEALPILOT_DATA_DIR"  # spec 002 section 3.2, read here only for D13

DEFAULT_PROVIDER = "mock"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_META_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_USAGE_DIR = "data/ai-usage"
DEFAULT_DATA_DIR = "data/raw"

PROVIDERS = ("mock", "meta", "gemini")
SUPPORTED_MODELS = ("muse-spark-1.3",)
GEMINI_MODELS = ("gemini-3.5-flash-lite",)  # D2
DATA_CLASSES = ("synthetic", "real")  # D8
TIMEOUT_RANGE = (1.0, 120.0)
MIN_KEY_LENGTH = 16
MASK = "**********"

# Fixed maximums for paid providers (D4, D5): settings may lower them, never raise them.
MAX_INPUT_CHARS = 16_000
MAX_OUTPUT_TOKENS = 1_024
MAX_MONTHLY_BUDGET_USD = Decimal("5.00")
MAX_CALLS_PER_HOUR = 30
MAX_PRICE_USD_PER_MTOK = Decimal(1000)

_WHOLE = re.compile(r"[0-9]+")
_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")


class Secret:
    """Holds a secret string. `repr` and `str` show only a mask."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret('{MASK}')"

    def __str__(self) -> str:
        return MASK


@dataclass(frozen=True)
class AISettings:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    meta_base_url: str = DEFAULT_META_BASE_URL
    meta_api_key: Secret | None = None
    # Spec 006: set by load_settings only when the provider is `gemini`.
    gemini_api_key: Secret | None = None
    gemini_model: str | None = None
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    gemini_data_class: str | None = None
    gemini_price_input: Decimal | None = None
    gemini_price_output: Decimal | None = None
    gemini_prices_checked_on: date | None = None
    max_input_chars: int = MAX_INPUT_CHARS
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    monthly_budget_usd: Decimal = MAX_MONTHLY_BUDGET_USD
    max_calls_per_hour: int = MAX_CALLS_PER_HOUR
    usage_dir: Path | None = None


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value if value else None  # empty counts as not set


def _timeout(raw: str | None) -> float:
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    low, high = TIMEOUT_RANGE
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not low <= value <= high:  # also rejects nan
        raise AIConfigError(f"{TIMEOUT_VAR} must be a number from {low:g} to {high:g}")
    return value


def _base_url(raw: str | None, var: str = META_BASE_URL_VAR,
              default: str = DEFAULT_META_BASE_URL) -> str:
    if raw is None:
        return default
    message = f"{var} must be an https:// URL with a host"
    try:
        parts = urlsplit(raw)
        _ = parts.port  # raises ValueError for a bad port
    except ValueError:
        raise AIConfigError(message) from None
    if parts.scheme != "https" or not parts.hostname:
        raise AIConfigError(message)
    return raw.rstrip("/")


def _api_key(raw: str | None, var: str = META_KEY_VAR, provider: str = "meta") -> Secret:
    if raw is None:
        raise AIConfigError(f"{var} is not set", provider=provider)
    if len(raw) < MIN_KEY_LENGTH or not raw.isprintable() or any(c.isspace() for c in raw):
        raise AIConfigError(f"{var} is malformed", provider=provider)
    return Secret(raw)


# --------------------------------------------------------------------------- spec 006

def _required(env: Mapping[str, str], var: str) -> str:
    raw = _get(env, var)
    if raw is None:
        raise AIConfigError(f"{var} is not set", provider="gemini")
    return raw


def _whole_limit(raw: str | None, var: str, maximum: int) -> int:
    """Section 5: unset means the maximum; a value may only lower it, never widen it."""
    if raw is None:
        return maximum
    if not _WHOLE.fullmatch(raw) or not 1 <= int(raw) <= maximum:
        raise AIConfigError(f"{var} must be a whole number from 1 to {maximum}",
                            provider="gemini")
    return int(raw)


def _budget(raw: str | None) -> Decimal:
    if raw is None:
        return MAX_MONTHLY_BUDGET_USD
    if not _DECIMAL.fullmatch(raw) or Decimal(raw) > MAX_MONTHLY_BUDGET_USD:
        raise AIConfigError(f"{MONTHLY_BUDGET_VAR} must be a number from 0 to "
                            f"{MAX_MONTHLY_BUDGET_USD}", provider="gemini")
    return Decimal(raw)


def _price(env: Mapping[str, str], var: str) -> Decimal:
    raw = _required(env, var)
    # Digits only: no sign, exponent, nan or inf. 0 is refused, because it would make every
    # reservation 0 and turn off the budget; nothing is ever replaced by a default.
    if not _DECIMAL.fullmatch(raw) or not 0 < Decimal(raw) <= MAX_PRICE_USD_PER_MTOK:
        raise AIConfigError(f"{var} must be a number above 0 and at most "
                            f"{MAX_PRICE_USD_PER_MTOK}", provider="gemini")
    return Decimal(raw)


def _checked_on(env: Mapping[str, str]) -> date:
    raw = _required(env, GEMINI_PRICES_DATE_VAR)
    try:
        value = date.fromisoformat(raw) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else None
    except ValueError:
        value = None
    if value is None or value > datetime.now(UTC).date():
        raise AIConfigError(f"{GEMINI_PRICES_DATE_VAR} must be an ISO date (YYYY-MM-DD) that "
                            "is not in the future", provider="gemini")
    return value


def _find_project_root() -> Path | None:
    """Spec 002 section 3.2: the first folder above the package with backend/pyproject.toml."""
    for folder in Path(__file__).resolve().parents:
        if (folder / "backend" / "pyproject.toml").is_file():
            return folder
    return None


def _check_path_text(raw: str, var: str) -> None:
    """D13 rule 4: refuse values whose meaning is ambiguous."""
    message = f"{var} is ambiguous; use a plain relative or absolute path"
    if "\0" in raw or raw != raw.strip() or raw.startswith("~"):
        raise AIConfigError(message, provider="gemini")
    if os.name == "nt":
        path = Path(raw)
        if bool(path.drive) != bool(path.root):  # C:folder or \folder
            raise AIConfigError(message, provider="gemini")


def _resolve(raw: str, root: Path) -> Path:
    path = Path(raw)
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _same_or_inside(inner: Path, outer: Path) -> bool:
    a = Path(os.path.normcase(str(inner)))
    b = Path(os.path.normcase(str(outer)))
    return a == b or a.is_relative_to(b)


def _usage_dir(env: Mapping[str, str]) -> Path:
    """Spec 006 section 5, "Usage folder" (D13, D15)."""
    usage_raw = _get(env, USAGE_DIR_VAR) or DEFAULT_USAGE_DIR
    data_raw = _get(env, DATA_DIR_VAR) or DEFAULT_DATA_DIR
    _check_path_text(usage_raw, USAGE_DIR_VAR)
    _check_path_text(data_raw, DATA_DIR_VAR)
    root = _find_project_root()
    if root is None:  # D15: the data/raw checks need the root, so never skip them
        raise AIConfigError(f"{USAGE_DIR_VAR} can't be checked: project root not found",
                            provider="gemini")
    try:
        usage = _resolve(usage_raw, root)
        data = _resolve(data_raw, root)
        raw_data = _resolve(DEFAULT_DATA_DIR, root)
        refused = any((
            _same_or_inside(usage, raw_data), _same_or_inside(raw_data, usage),
            _same_or_inside(usage, data), _same_or_inside(data, usage),
            usage.exists() and not usage.is_dir(),
        ))
    except (OSError, ValueError, RuntimeError):
        refused = True
    if refused:
        raise AIConfigError(f"{USAGE_DIR_VAR} must be a folder outside data/raw and outside "
                            f"the folder named by {DATA_DIR_VAR}", provider="gemini")
    return usage


def _gemini_fields(env: Mapping[str, str]) -> dict:
    model = _required(env, GEMINI_MODEL_VAR)
    if model not in GEMINI_MODELS:
        raise AIConfigError(f"{GEMINI_MODEL_VAR} must be one of {', '.join(GEMINI_MODELS)}",
                            provider="gemini")
    data_class = _required(env, GEMINI_DATA_CLASS_VAR)
    if data_class not in DATA_CLASSES:
        raise AIConfigError(f"{GEMINI_DATA_CLASS_VAR} must be one of "
                            f"{', '.join(DATA_CLASSES)}", provider="gemini")
    return {
        "gemini_api_key": _api_key(_get(env, GEMINI_KEY_VAR), GEMINI_KEY_VAR, "gemini"),
        "gemini_model": model,
        "gemini_base_url": _base_url(_get(env, GEMINI_BASE_URL_VAR), GEMINI_BASE_URL_VAR,
                                     DEFAULT_GEMINI_BASE_URL),
        "gemini_data_class": data_class,
        "gemini_price_input": _price(env, GEMINI_PRICE_INPUT_VAR),
        "gemini_price_output": _price(env, GEMINI_PRICE_OUTPUT_VAR),
        "gemini_prices_checked_on": _checked_on(env),
        "max_input_chars": _whole_limit(_get(env, MAX_INPUT_CHARS_VAR), MAX_INPUT_CHARS_VAR,
                                        MAX_INPUT_CHARS),
        "max_output_tokens": _whole_limit(_get(env, MAX_OUTPUT_TOKENS_VAR),
                                          MAX_OUTPUT_TOKENS_VAR, MAX_OUTPUT_TOKENS),
        "monthly_budget_usd": _budget(_get(env, MONTHLY_BUDGET_VAR)),
        "max_calls_per_hour": _whole_limit(_get(env, MAX_CALLS_VAR), MAX_CALLS_VAR,
                                           MAX_CALLS_PER_HOUR),
        "usage_dir": _usage_dir(env),
    }


def load_settings(env: Mapping[str, str] | None = None) -> AISettings:
    """Read and validate settings from `env` (default: `os.environ`)."""
    env = os.environ if env is None else env
    provider = _get(env, PROVIDER_VAR) or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise AIConfigError(f"{PROVIDER_VAR} must be one of {', '.join(PROVIDERS)}")
    model = _get(env, MODEL_VAR) or DEFAULT_MODEL
    if model not in SUPPORTED_MODELS:
        raise AIConfigError(f"{MODEL_VAR} must be one of {', '.join(SUPPORTED_MODELS)}")
    timeout = _timeout(_get(env, TIMEOUT_VAR))
    base_url = _base_url(_get(env, META_BASE_URL_VAR))
    # The mock provider never reads a key, so a missing or bad key can't affect it.
    key = _api_key(_get(env, META_KEY_VAR)) if provider == "meta" else None
    extra = _gemini_fields(env) if provider == "gemini" else {}
    return AISettings(provider, model, timeout, base_url, key, **extra)
