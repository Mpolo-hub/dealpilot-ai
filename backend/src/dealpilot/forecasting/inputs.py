"""Evaluation data and model-visible inputs (spec 003 sections 4.3, 4.4 and 9.4).

Every input file is read once as raw bytes. Its SHA-256 is taken from those bytes, and the
tables are parsed from the same bytes, so what is scored is exactly what was hashed.
`metadata.json` `parameters` and `regions.size_weight` are never kept (section 4.4).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dealpilot.forecasting.series import TOTAL_KEY, SeriesSet, build_series
from dealpilot.forecasting.split import ForecastingError, TimeSplit, make_split

# A1: the five files of the spec 002 v1 dataset, in ascending byte order of file name
# (the order of the holdout `data_hash`, section 9.4).
A1_FILES = ("metadata.json", "order_lines.parquet", "orders.parquet", "products.parquet",
            "regions.parquet")
EXPECTED_FILE = "expected_demand.parquet"
# Evaluation-only metadata fields (section 4.4). `parameters` is never kept.
METADATA_FIELDS = ("seed", "start", "end", "generator_version", "row_counts")
_COLUMNS = {
    "regions": ("region_id",),
    "products": ("product_id", "category", "launch_date", "discontinue_date"),
    "orders": ("order_id", "order_date", "region_id"),
    "order_lines": ("order_id", "product_id", "quantity"),
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def data_hash(file_hashes: dict[str, str]) -> str:
    """Section 9.4: SHA-256 over the five A1 file hashes, each followed by LF."""
    missing = [name for name in A1_FILES if name not in file_hashes]
    if missing:
        raise ForecastingError(f"missing A1 file hash: {', '.join(missing)}")
    text = "".join(file_hashes[name] + "\n" for name in A1_FILES)
    return sha256_hex(text.encode("utf-8"))


@dataclass(frozen=True)
class Product:
    product_id: str
    category: str
    launch_date: date
    discontinue_date: date | None


@dataclass(frozen=True)
class EvalData:
    """Everything evaluation code may use; model code only gets `visible_inputs`."""
    metadata: dict  # METADATA_FIELDS only, start and end as dates
    split: TimeSplit
    series: SeriesSet
    products: tuple[Product, ...]  # full table, evaluation only (section 4.4)
    region_ids: tuple[str, ...]
    file_hashes: dict[str, str]  # every file read, by name
    expected: np.ndarray | None  # product_region expected units [series, day], or None

    @property
    def start(self) -> date:
        return self.split.start

    @property
    def end(self) -> date:
        return self.split.end


def read_files(folder: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    """Raw bytes of each file; a missing file stops the run."""
    out = {}
    for name in names:
        path = folder / name
        if not path.is_file():
            raise ForecastingError(f"{name} is missing from the data folder")
        out[name] = path.read_bytes()
    return out


def _metadata(raw: bytes) -> dict:
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ForecastingError("metadata.json is not valid UTF-8 JSON") from None
    if not isinstance(loaded, dict):
        raise ForecastingError("metadata.json is not a JSON object")
    missing = [f for f in METADATA_FIELDS if f not in loaded]
    if missing:
        raise ForecastingError(f"metadata.json has no field {', '.join(missing)}")
    kept = {f: loaded[f] for f in METADATA_FIELDS}  # drops `parameters` (section 4.4)
    for field in ("start", "end"):
        try:
            kept[field] = date.fromisoformat(kept[field])
        except (TypeError, ValueError):
            raise ForecastingError(f"metadata.json has an invalid {field}") from None
    return kept


def _table(name: str, raw: bytes) -> pa.Table:
    try:
        table = pq.read_table(pa.BufferReader(raw))
    except (pa.ArrowException, OSError):
        raise ForecastingError(f"{name}.parquet is unreadable") from None
    missing = [c for c in _COLUMNS[name] if c not in table.column_names]
    if missing:
        raise ForecastingError(f"{name}.parquet has no column {', '.join(missing)}")
    return table.select(list(_COLUMNS[name]))  # drops size_weight, list_price, names


def parse_data(raw: dict[str, bytes], with_expected: bool) -> EvalData:
    """Parse the hashed bytes into evaluation data."""
    metadata = _metadata(raw["metadata.json"])
    split = make_split(metadata["start"], metadata["end"])
    tables = {name: _table(name, raw[f"{name}.parquet"]) for name in _COLUMNS}
    con = duckdb.connect()
    try:
        for name, table in tables.items():
            con.register(name, table)
        series = build_series(con, split.start, split.end)
    finally:
        con.close()
    p = tables["products"].to_pydict()
    products = tuple(sorted(
        (Product(*row) for row in zip(p["product_id"], p["category"], p["launch_date"],
                                       p["discontinue_date"])),
        key=lambda product: product.product_id))
    region_ids = tuple(sorted(tables["regions"].column("region_id").to_pylist()))
    expected = _expected(raw[EXPECTED_FILE], series, split) if with_expected else None
    hashes = {name: sha256_hex(data) for name, data in raw.items()}
    return EvalData(metadata, split, series, products, region_ids, hashes, expected)


def _expected(raw: bytes, series: SeriesSet, split: TimeSplit) -> np.ndarray:
    """Expected units per product-region series and day (signal recovery only)."""
    try:
        table = pq.read_table(pa.BufferReader(raw),
                              columns=["date", "product_id", "region_id", "expected_units"])
    except (pa.ArrowException, OSError, KeyError):
        raise ForecastingError(f"{EXPECTED_FILE} is unreadable") from None
    keys = series.keys["product_region"]
    row = {key: i for i, key in enumerate(keys)}
    out = np.zeros((len(keys), len(series.days)), dtype=np.float64)
    d = table.to_pydict()
    for day, product_id, region_id, units in zip(d["date"], d["product_id"], d["region_id"],
                                                 d["expected_units"]):
        if split.start <= day <= split.end and (product_id, region_id) in row:
            out[row[(product_id, region_id)], (day - split.start).days] += units
    return out


def load_data(folder: Path, with_expected: bool = True) -> EvalData:
    names = A1_FILES + ((EXPECTED_FILE,) if with_expected else ())
    return parse_data(read_files(Path(folder), names), with_expected)


# --------------------------------------------------------------------------- visible inputs

@dataclass(frozen=True)
class VisibleProduct:
    product_id: str
    category: str
    launch_date: date
    discontinue_date: date | None  # only when it is <= the cutoff


@dataclass(frozen=True)
class VisibleInputs:
    """What model code receives at a cutoff (section 4.3, D13), and nothing else."""
    metadata: dict  # {"start", "cutoff"} only
    products: tuple[VisibleProduct, ...]
    regions: tuple[str, ...]  # region_id only
    history: dict[str, tuple[tuple, np.ndarray]]  # level -> (visible keys, [series, day])

    @property
    def start(self) -> date:
        return self.metadata["start"]

    @property
    def cutoff(self) -> date:
        return self.metadata["cutoff"]


def visible_metadata(metadata: dict, cutoff: date) -> dict:
    """The only metadata reader model code uses: `start` and the cutoff (AC-FC-07)."""
    return {"start": metadata["start"], "cutoff": cutoff}


def visible_inputs(data: EvalData, cutoff: date) -> VisibleInputs:
    """Inputs known at `cutoff`: launched products, history from `start` to `cutoff`."""
    if not data.start <= cutoff <= data.end:
        raise ForecastingError("the cutoff must lie inside the data range")
    products = tuple(
        VisibleProduct(p.product_id, p.category, p.launch_date,
                       p.discontinue_date if p.discontinue_date is not None
                       and p.discontinue_date <= cutoff else None)
        for p in data.products if p.launch_date <= cutoff)
    n = (cutoff - data.start).days + 1
    pr_keys = data.series.keys["product_region"]
    launched = {p.product_id for p in products}
    rows = [i for i, (product_id, _) in enumerate(pr_keys) if product_id in launched]
    pr_values = data.series.values["product_region"][rows, :n].copy()
    category_of = {p.product_id: p.category for p in products}
    categories = tuple(sorted(set(category_of.values())))
    by_category = np.zeros((len(categories), n), dtype=np.int64)
    for j, i in enumerate(rows):
        by_category[categories.index(category_of[pr_keys[i][0]])] += pr_values[j]
    total_keys = (TOTAL_KEY,) if rows else ()
    history = {
        "total": (total_keys, pr_values.sum(axis=0, keepdims=True) if rows
                  else np.zeros((0, n), dtype=np.int64)),
        "category": (categories, by_category),
        "product_region": (tuple(pr_keys[i] for i in rows), pr_values),
    }
    return VisibleInputs(visible_metadata(data.metadata, cutoff), products,
                         data.region_ids, history)
