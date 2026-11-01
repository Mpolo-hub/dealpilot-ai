"""
conftest.py — shared fixtures for DealPilot generator tests.

The generator is invoked as a subprocess:
    python -m dealpilot.data.generate --seed <N> --start ... --end ... --out <dir>

The default run (seed 42) happens once per session and is shared by every test that
reads its output. If the generator is missing or exits non-zero, tests FAIL with the
generator's output. They never skip.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from git_repo_support import AC_FC_26_VALUE, AC_FC_26_VARIABLE, ac_fc_26_authorized

# ---------------------------------------------------------------------------
# Constants derived from the spec (§3, §4, §6)
# ---------------------------------------------------------------------------
DEFAULT_SEED = 42
DEFAULT_START = "2023-01-01"
DEFAULT_END = "2025-12-31"

EXPECTED_PARQUET_FILES = [
    "regions.parquet",
    "products.parquet",
    "customers.parquet",
    "promotions.parquet",
    "orders.parquet",
    "order_lines.parquet",
    "expected_demand.parquet",
]
EXPECTED_FILES = EXPECTED_PARQUET_FILES + ["metadata.json"]
TABLE_NAMES = [f.removesuffix(".parquet") for f in EXPECTED_PARQUET_FILES]

CLOSED_DAYS = [
    # All Dec 25 and Jan 1 in the default range
    "2023-01-01",
    "2023-12-25",
    "2024-01-01",
    "2024-12-25",
    "2025-01-01",
    "2025-12-25",
]

# Region size weights from spec §4 (fixed; tests never read them from generator output)
REGION_SIZE_WEIGHTS = {"R01": 0.28, "R02": 0.22, "R03": 0.20, "R04": 0.16, "R05": 0.14}

# Weekly multipliers from spec §5.4 (Mon=0, ..., Sun=6)
WEEKLY_MULTIPLIERS = {0: 0.85, 1: 0.90, 2: 0.95, 3: 1.00, 4: 1.10, 5: 1.25, 6: 0.95}

# Fixed §5 parameters, as they must appear under metadata.json "parameters" (spec §3.1).
# AC-17(c) recomputes from these, never from the generator's metadata copy.
SPEC_PARAMS = {
    "base_total_units": 250,
    "base_category_share": 0.20,
    "base_lognormal_sigma": 0.5,
    "base_max_share": 0.06,
    "trend_rates": {
        "Electronics": 0.15, "Home": 0.08, "Office": 0.06, "Outdoor": 0.10, "Apparel": 0.00,
    },
    "trend_days_per_year": 365.25,
    "weekly_multipliers": [0.85, 0.90, 0.95, 1.00, 1.10, 1.25, 0.95],
    "yearly_anchor_day": 15,
    "yearly_anchors": {
        "standard": [0.90, 0.80, 0.88, 0.95, 1.00, 0.98, 0.95, 1.00, 0.98, 1.03, 1.13, 1.20],
        "outdoor": [0.80, 0.85, 0.95, 1.05, 1.15, 1.25, 1.25, 1.15, 1.05, 0.95, 0.85, 0.80],
    },
    "yearly_curve_by_category": {
        "Electronics": "standard", "Home": "standard", "Office": "standard",
        "Outdoor": "outdoor", "Apparel": "standard",
    },
    "promo_lift_base": 1.15,
    "promo_lift_per_discount": 1.5,
    "promo_dip_factor": 0.90,
    "promo_pre_window_days": 14,
    "promo_post_window_days": 7,
    "promo_max_concurrent": 3,
    "promo_min_pre_window_units": 14,
    "closed_days": ["12-25", "01-01"],
    "noise_nb_size": 2,
    "price_increase_min": 0.02,
    "price_increase_max": 0.04,
}


# ---------------------------------------------------------------------------
# AC-FC-26 guard (spec 003 section 13.3)
# ---------------------------------------------------------------------------
# A command-line -m replaces the addopts marker filter, so `pytest -m "not slow"` would
# select the formal_checker tests. Without the explicit authorization variable they are
# removed here, whatever -m says, and the run says so.
_AC_FC_26_BLOCKED = pytest.StashKey[int]()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ac_fc_26_authorized():
        return
    blocked = [item for item in items if item.get_closest_marker("formal_checker")]
    if blocked:
        config.hook.pytest_deselected(items=blocked)
        items[:] = [item for item in items if not item.get_closest_marker("formal_checker")]
    config.stash[_AC_FC_26_BLOCKED] = len(blocked)


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    blocked = config.stash.get(_AC_FC_26_BLOCKED, 0)
    if blocked:
        terminalreporter.write_line(
            f"AC-FC-26: {blocked} formal_checker tests not run. They need "
            f"{AC_FC_26_VARIABLE}={AC_FC_26_VALUE}, set only after O2 gate 6 is approved.",
            yellow=True)


# ---------------------------------------------------------------------------
# Generator runner helpers
# ---------------------------------------------------------------------------

def run_generator(seed: int, start: str, end: str, out_dir: Path) -> subprocess.CompletedProcess:
    """Invoke the generator as a subprocess. Returns CompletedProcess."""
    return subprocess.run(
        [
            sys.executable, "-m", "dealpilot.data.generate",
            "--seed", str(seed),
            "--start", start,
            "--end", end,
            "--out", str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,  # callers inspect returncode; AC-14 expects non-zero exits
    )


def run_generator_ok(seed: int, start: str, end: str, out_dir: Path) -> None:
    """Run the generator and fail (never skip) if it is missing or exits non-zero."""
    result = run_generator(seed, start, end, out_dir)
    if result.returncode != 0:
        pytest.fail(
            f"Generator (seed={seed}, {start}..{end}) exited with code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def as_ns_dates(values) -> pd.Series:
    """Dates as datetime64[ns] so merge keys match whatever unit DuckDB/pandas returns."""
    return pd.Series(pd.to_datetime(values)).astype("datetime64[ns]")


def open_days(start: str = DEFAULT_START, end: str = DEFAULT_END) -> pd.DatetimeIndex:
    """Every date from start to end inclusive, minus the §5.7 closed days (Dec 25, Jan 1)."""
    days = pd.date_range(start, end)  # datetime64[ns]
    closed = ((days.month == 12) & (days.day == 25)) | ((days.month == 1) & (days.day == 1))
    return days[~closed]


def load_tables(out_dir: Path, names: list[str] = TABLE_NAMES) -> dict:
    """Load the named Parquet tables from out_dir as DataFrames."""
    import duckdb

    con = duckdb.connect()
    data = {
        name: con.execute(f"SELECT * FROM read_parquet('{out_dir / (name + '.parquet')}')").df()
        for name in names
    }
    con.close()
    return data


# ---------------------------------------------------------------------------
# Session-scoped fixtures: one default run (seed 42)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def default_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, float]:
    """Run the generator once with default settings. Returns (out_dir, seconds taken)."""
    out = tmp_path_factory.mktemp("generated")
    t_start = time.monotonic()
    run_generator_ok(DEFAULT_SEED, DEFAULT_START, DEFAULT_END, out)
    return out, time.monotonic() - t_start


@pytest.fixture(scope="session")
def generated_dir(default_run: tuple[Path, float]) -> Path:
    """Output folder of the default run."""
    return default_run[0]


@pytest.fixture(scope="session")
def tables(generated_dir: Path):
    """Load all Parquet tables and metadata as a dict of DataFrames + metadata dict."""
    data = load_tables(generated_dir)
    with open(generated_dir / "metadata.json", encoding="utf-8") as f:
        data["metadata"] = json.load(f)
    return data
