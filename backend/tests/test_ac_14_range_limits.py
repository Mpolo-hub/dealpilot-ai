"""
AC-14 — Range limits are enforced.

Spec §8, AC-14:
  "A range under 730 days or over 1096 days fails with a clear error
   and writes nothing."

Spec §3: --start and --end, counting both end dates, must be 730 to 1096 days.

A missing generator, a crash (traceback) or a message that doesn't name the broken
limit all count as failures. A non-zero exit code alone is not enough.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from conftest import (
    DEFAULT_END,
    DEFAULT_SEED,
    DEFAULT_START,
    EXPECTED_FILES,
    run_generator,
    run_generator_ok,
)


@pytest.mark.parametrize(
    ("start", "end", "limit"),
    [
        pytest.param("2023-01-01", "2024-12-29", "730", id="729_days"),
        pytest.param("2023-01-01", "2026-01-01", "1096", id="1097_days"),
    ],
)
def test_ac_14_invalid_range_fails_clearly(
    start: str, end: str, limit: str, tmp_path: Path
) -> None:
    """AC-14: out-of-range dates exit non-zero, name the limit, and write nothing."""
    out = tmp_path / "out"
    result = run_generator(DEFAULT_SEED, start, end, out)
    output = result.stdout + result.stderr

    assert "No module named" not in output, f"Generator could not be imported:\n{output}"
    assert result.returncode != 0, f"Generator accepted an invalid range {start}..{end}"
    assert "Traceback" not in output, f"Generator crashed instead of a clear error:\n{output}"
    assert limit in output, f"Error message does not name the {limit}-day limit:\n{output}"
    written = list(out.iterdir()) if out.exists() else []
    assert not written, f"Generator wrote files for invalid range: {[f.name for f in written]}"


def test_ac_14_exact_boundary_730_days_succeeds(tmp_path: Path) -> None:
    """AC-14: 2023-01-01 to 2024-12-30 (exactly 730 days) succeeds and writes all files."""
    out = tmp_path / "out_730"
    run_generator_ok(DEFAULT_SEED, "2023-01-01", "2024-12-30", out)
    missing = [f for f in EXPECTED_FILES if not (out / f).exists()]
    assert not missing, f"Missing output files: {missing}"


def test_ac_14_exact_boundary_1096_days_succeeds(generated_dir: Path) -> None:
    """AC-14: the default range is exactly 1096 days; the session run proves it succeeds."""
    days = (date.fromisoformat(DEFAULT_END) - date.fromisoformat(DEFAULT_START)).days + 1
    assert days == 1096
    missing = [f for f in EXPECTED_FILES if not (generated_dir / f).exists()]
    assert not missing, f"Missing output files: {missing}"
