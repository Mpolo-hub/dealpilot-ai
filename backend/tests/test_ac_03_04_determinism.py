"""
AC-03 — Same seed gives identical data.
AC-04 — A different seed gives different data.

Spec §8:
  AC-03: "Run twice with seed 42. All 7 tables are equal, row by row."
  AC-04: "Seed 42 vs seed 7: order_lines differ."

The session's default run is the first seed-42 run; each test adds one more run.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from conftest import DEFAULT_END, DEFAULT_SEED, DEFAULT_START, load_tables, run_generator_ok


def test_ac_03_same_seed_identical_tables(
    generated_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """AC-03: all 7 tables are equal row-by-row across two runs with seed 42."""
    out2 = tmp_path_factory.mktemp("seed42_run2")
    run_generator_ok(DEFAULT_SEED, DEFAULT_START, DEFAULT_END, out2)
    tables1, tables2 = load_tables(generated_dir), load_tables(out2)
    for name, df1 in tables1.items():
        df1 = df1.sort_index(axis=1)
        df2 = tables2[name].sort_index(axis=1)
        # Sort rows deterministically before comparing
        sort_cols = list(df1.columns)
        df1 = df1.sort_values(sort_cols).reset_index(drop=True)
        df2 = df2.sort_values(sort_cols).reset_index(drop=True)
        pd.testing.assert_frame_equal(df1, df2, obj=f"Table '{name}'")


def test_ac_04_different_seed_different_order_lines(
    generated_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """AC-04: seed 42 vs seed 7 produce different order_lines."""
    out7 = tmp_path_factory.mktemp("seed7_ac04")
    run_generator_ok(7, DEFAULT_START, DEFAULT_END, out7)
    lines42 = load_tables(generated_dir, ["order_lines"])["order_lines"]
    lines7 = load_tables(out7, ["order_lines"])["order_lines"]
    assert not lines42.equals(lines7), "order_lines for seed 42 and seed 7 are identical"
