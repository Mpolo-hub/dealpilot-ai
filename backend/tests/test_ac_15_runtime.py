"""
AC-15 — Runs fast enough.

Spec §8, AC-15:
  "Default run finishes in under 60 seconds."

The session's default run is timed in conftest (default_run fixture), so this test
doesn't need a run of its own.
"""
from __future__ import annotations

from pathlib import Path

RUNTIME_LIMIT_SECONDS = 60


def test_ac_15_default_run_under_60s(default_run: tuple[Path, float]) -> None:
    """AC-15: default generator run completes in under 60 seconds."""
    _, elapsed = default_run
    assert elapsed < RUNTIME_LIMIT_SECONDS, (
        f"AC-15: generator took {elapsed:.1f}s, exceeds {RUNTIME_LIMIT_SECONDS}s limit"
    )
