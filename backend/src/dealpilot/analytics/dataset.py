"""Find and open the spec 001 dataset for read-only DuckDB queries (spec 002, 3.2 and 3.7).

Nothing is cached (D7): every call resolves the folder again and opens a new in-memory
DuckDB connection over the Parquet files.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

ENV_VAR = "DEALPILOT_DATA_DIR"
DEFAULT_DATA_DIR = "data/raw"
ABSOLUTE_PLACEHOLDER = "<absolute path>"

# The v1 dataset (3.2). Every /v1 endpoint requires all of them, even ones it doesn't read.
# expected_demand.parquet is deliberately absent: the API never reads it (3.8).
REQUIRED_FILES = (
    "metadata.json", "regions.parquet", "products.parquet", "orders.parquet",
    "order_lines.parquet",
)
METADATA_FIELDS = ("seed", "start", "end", "generator_version", "row_counts")
# Columns and DuckDB types the API relies on (section 4).
SCHEMAS = {
    "regions": {"region_id": "VARCHAR", "name": "VARCHAR"},
    "products": {
        "product_id": "VARCHAR", "name": "VARCHAR", "category": "VARCHAR",
        "launch_date": "DATE", "discontinue_date": "DATE",
    },
    "orders": {"order_id": "VARCHAR", "order_date": "DATE", "region_id": "VARCHAR"},
    "order_lines": {
        "order_id": "VARCHAR", "product_id": "VARCHAR", "quantity": "BIGINT",
        "line_total": "DECIMAL(12,2)",
    },
}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class DataUnavailable(Exception):
    """The dataset can't be used. `reasons` never contain paths other than file names."""

    def __init__(self, configured: str, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.configured = configured
        self.reasons = reasons


@dataclass
class Dataset:
    con: duckdb.DuckDBPyConnection
    metadata: dict
    start: date
    end: date


def parse_iso_date(text: str) -> date | None:
    """A strict YYYY-MM-DD date, or None. (date.fromisoformat alone also accepts 20250101.)"""
    if not _ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def find_project_root(start: Path | None = None) -> Path | None:
    """Nearest folder above the dealpilot package that holds backend/pyproject.toml."""
    for folder in (start or Path(__file__)).resolve().parents:
        if (folder / "backend" / "pyproject.toml").is_file():
            return folder
    return None


def shown_value(configured: str | None) -> str:
    """What a 503 may say about DEALPILOT_DATA_DIR: never an absolute path (3.7)."""
    if not configured:
        return DEFAULT_DATA_DIR
    return ABSOLUTE_PLACEHOLDER if Path(configured).is_absolute() else configured


def resolve_data_dir(configured: str | None, project_root: Path | None) -> Path:
    """Section 3.2: absolute as is; relative (and the default) joined to the project root."""
    path = Path(configured or DEFAULT_DATA_DIR)
    if path.is_absolute():
        return path
    if project_root is None:
        raise DataUnavailable(shown_value(configured), ["project root not found"])
    return project_root / path


@contextmanager
def open_dataset(tables: tuple[str, ...]) -> Iterator[Dataset]:
    """Check the dataset (3.7), then expose `tables` as DuckDB views for one request."""
    configured = os.environ.get(ENV_VAR) or None
    shown = shown_value(configured)
    folder = resolve_data_dir(configured, find_project_root())
    if not folder.is_dir():
        raise DataUnavailable(shown, ["data folder does not exist"])
    missing = [f"{name} is missing" for name in REQUIRED_FILES if not (folder / name).is_file()]
    if missing:
        raise DataUnavailable(shown, missing)

    problems: list[str] = []
    metadata = _read_metadata(folder / "metadata.json", problems)
    con = duckdb.connect()
    try:
        for name in tables:
            _register(con, folder, name, problems)
        if problems:
            raise DataUnavailable(shown, problems)
        yield Dataset(con, metadata, metadata["start"], metadata["end"])
    finally:
        con.close()


def _read_metadata(path: Path, problems: list[str]) -> dict:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        problems.append("metadata.json is unreadable")
        return {}
    except ValueError:
        problems.append("metadata.json is not valid JSON")
        return {}
    if not isinstance(metadata, dict):
        problems.append("metadata.json is not a JSON object")
        return {}
    for field in METADATA_FIELDS:
        if field not in metadata:
            problems.append(f"metadata.json has no field {field}")
    for field in ("start", "end"):
        if field in metadata:
            parsed = parse_iso_date(metadata[field]) if isinstance(metadata[field], str) else None
            if parsed is None:
                problems.append(f"metadata.json has an invalid {field}")
            else:
                metadata[field] = parsed
    return metadata


def _register(con: duckdb.DuckDBPyConnection, folder: Path, name: str, problems: list[str]) -> None:
    file = f"{name}.parquet"
    try:
        relation = con.read_parquet(str(folder / file))
        actual = dict(zip(relation.columns, (str(t) for t in relation.types)))
    except duckdb.Error:
        problems.append(f"{file} is unreadable")
        return
    found_all = True
    for column, expected in SCHEMAS[name].items():
        if column not in actual:
            problems.append(f"{file} has no column {column}")
            found_all = False
        elif actual[column] != expected:
            problems.append(f"{file} column {column} has type {actual[column]}, expected {expected}")
            found_all = False
    if found_all:
        relation.create_view(name)
