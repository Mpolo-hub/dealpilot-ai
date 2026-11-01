"""Spec 001 section 3 seed rule (decision 2026-10-30): 0 and positive integers only.

No acceptance-criterion ID: the rule is a recorded decision, not a new criterion. Every
run writes to a temporary folder.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from dealpilot.data.generate import GenerationError, check_seed, generate, main

START, END = date(2023, 1, 1), date(2024, 12, 30)  # 730 days


@pytest.mark.parametrize("seed", [-1, -42, np.int64(-3)])
def test_seed_rule_negative_seed_is_refused(seed) -> None:
    with pytest.raises(GenerationError, match="0 or more"):
        generate(seed, START, END)


@pytest.mark.parametrize("seed", [True, False, 1.0, 42.5, "42", None])
def test_seed_rule_non_integer_seed_is_refused(seed) -> None:
    with pytest.raises(GenerationError, match="must be an integer"):
        check_seed(seed)


@pytest.mark.parametrize("seed", [0, 1, 42, 2**40, np.int64(7)])
def test_seed_rule_zero_and_positive_are_accepted(seed) -> None:
    check_seed(seed)  # no error


def test_seed_rule_zero_generates(tmp_path: Path) -> None:
    """Seed 0 runs end to end (730-day range) and is recorded as given."""
    assert main(["--seed", "0", "--start", "2023-01-01", "--end", "2024-12-30",
                 "--out", str(tmp_path / "s0")]) == 0
    assert '"seed": 0,' in (tmp_path / "s0" / "metadata.json").read_text(encoding="utf-8")


def test_seed_rule_cli_negative_seed_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "neg"
    result = subprocess.run(
        [sys.executable, "-m", "dealpilot.data.generate", "--seed", "-1", "--out", str(out)],
        capture_output=True, text=True, check=False, timeout=120)
    assert result.returncode == 1
    assert "--seed must be 0 or more, got -1" in result.stderr
    assert "Nothing was written" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("value", ["abc", "1.5", "True"])
def test_seed_rule_cli_non_integer_text_is_refused(value: str, tmp_path: Path,
                                                   capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--seed", value, "--out", str(tmp_path / "x")])
    assert info.value.code == 2  # argparse usage error
    assert "--seed" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
