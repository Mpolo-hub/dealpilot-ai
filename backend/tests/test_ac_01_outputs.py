"""
AC-01 — All 7 Parquet files and metadata.json are written to --out.

Spec §8, AC-01:
  "All 7 Parquet files and `metadata.json` are written to `--out`.
   Files exist and load with DuckDB."
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from conftest import EXPECTED_FILES, EXPECTED_PARQUET_FILES


def test_ac_01_all_output_files_exist(generated_dir: Path) -> None:
    """AC-01: every required output file is present."""
    missing = [f for f in EXPECTED_FILES if not (generated_dir / f).exists()]
    assert not missing, f"Missing output files: {missing}"


def test_ac_01_parquet_files_load_with_duckdb(generated_dir: Path) -> None:
    """AC-01: every Parquet file loads without error in DuckDB."""
    con = duckdb.connect()
    errors: list[str] = []
    for fname in EXPECTED_PARQUET_FILES:
        try:
            con.execute(f"SELECT COUNT(*) FROM read_parquet('{generated_dir / fname}')").fetchone()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fname}: {exc}")
    con.close()
    assert not errors, "DuckDB failed to load:\n" + "\n".join(errors)


def test_ac_01_metadata_json_is_valid_json(generated_dir: Path) -> None:
    """AC-01: metadata.json is valid JSON and is not empty."""
    import json

    raw = (generated_dir / "metadata.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict) and data, "metadata.json is empty or not a JSON object"
