"""Results record: canonical JSON, hashes, run IDs and run files (spec 003 sections 5.4, 9).

CSV and JSON are UTF-8 with LF line endings; numbers use `%.10g`; rows are sorted by
model, level, window, day scope, then key. Nothing is ever overwritten.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from dealpilot.forecasting.baselines import ModelInfo
from dealpilot.forecasting.split import ForecastingError

MAX_SUFFIX = 99
_VERSION = re.compile(r"^[0-9]+(\.[0-9]+)*$")
LIBRARIES = ("numpy", "pandas", "duckdb", "pyarrow")

METRIC_COLUMNS = ("model", "level", "window", "scope", "wape", "mae", "bias", "mase_mean",
                  "mase_median", "relmae", "n_inactive", "n_tie", "n_base_perfect",
                  "n_cand_perfect", "n_folds_wape", "n_folds_mae", "n_folds_bias",
                  "n_folds_mase")
SERIES_COLUMNS = ("model", "window", "scope", "product_id", "region_id", "mae", "scale",
                  "mase", "r", "eligible", "inactive")
SIGNAL_COLUMNS = ("model", "level", "window", "scope", "signal_wape", "noise_floor")


def canonical_json(value) -> str:
    """Section 5.4 canonical JSON. Floats are refused: decimals are written as strings."""
    _refuse_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _refuse_floats(value) -> None:
    if isinstance(value, float):
        raise ForecastingError("floats are not allowed in hashed settings; use a string")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ForecastingError("object keys must be strings")
            _refuse_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _refuse_floats(item)
    elif not (value is None or isinstance(value, (str, int, bool))):
        raise ForecastingError(f"unsupported value type: {type(value).__name__}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def model_record(info: ModelInfo) -> dict:
    return {"name": info.name, "version": info.version, "settings": info.settings,
            "uses_holiday_calendar": info.uses_holiday_calendar,
            "uses_planned_promotions": info.uses_planned_promotions}


def version_key(version: str) -> tuple:
    """Numeric order: parts compared as integers, shorter first, then the text."""
    if not _VERSION.fullmatch(version):
        raise ForecastingError(f"invalid model version: {version!r}")
    return tuple(int(part) for part in version.split(".")), version


def config_hash(models: Iterable[ModelInfo]) -> str:
    """Section 9.3: every model of the run, sorted by name, then version (numeric)."""
    records = sorted((model_record(info) for info in models),
                     key=lambda r: (r["name"], version_key(r["version"])))
    return sha256_text(canonical_json(records))


def candidate_config_sha256(info: ModelInfo) -> str:
    """Section 5.4: the candidate's own record only."""
    return sha256_text(canonical_json(model_record(info)))


# --------------------------------------------------------------------------- run folders

def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def run_id_base(created: datetime, stage: str, config_sha: str) -> str:
    return f"{created.strftime('%Y%m%dT%H%M%SZ')}-{stage}-{config_sha[:8]}"


def run_id_candidates(base: str) -> list[str]:
    return [base] + [f"{base}-{n}" for n in range(2, MAX_SUFFIX + 1)]


def choose_run_id(results_dir: Path, base: str) -> str:
    """The first name of section 9.6 whose folder does not exist."""
    for name in run_id_candidates(base):
        if not (results_dir / name).exists():
            return name
    raise ForecastingError(f"run IDs {base} to {base}-{MAX_SUFFIX} all exist")


def create_run_folder(results_dir: Path, base: str) -> Path:
    """Create the folder exclusively, trying `-2` to `-99`; never reuse one."""
    results_dir.mkdir(parents=True, exist_ok=True)
    for name in run_id_candidates(base):
        folder = results_dir / name
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise ForecastingError(f"run IDs {base} to {base}-{MAX_SUFFIX} all exist")


# --------------------------------------------------------------------------- file formats

def format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".10g")  # the spec's %.10g
    return str(value)


def csv_text(columns: Sequence[str], rows: Iterable[dict], sort_by: Sequence[str]) -> str:
    """Values never hold commas, quotes or line breaks (fixed names and numbers)."""
    ordered = sorted(rows, key=lambda r: tuple(str(r.get(c, "")) for c in sort_by))
    lines = [",".join(columns)]
    for row in ordered:
        cells = [format_value(row.get(c)) for c in columns]
        if any(ch in cell for cell in cells for ch in ',"\r\n'):
            raise ForecastingError("a CSV value contains a separator")
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def write_new_file(path: Path, text: str) -> None:
    """Create a file that must not exist yet, UTF-8 with LF."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def json_text(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                      allow_nan=False) + "\n"


def write_json_atomic(path: Path, value) -> None:
    """Write to a temporary name in the same folder, sync, then rename (never half-written)."""
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json_text(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


# --------------------------------------------------------------------------- provenance

def library_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for name in LIBRARIES:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def source_manifest(project_root: Path) -> dict[str, str]:
    """Section 9.3: SHA-256 of every file under `backend/src/` and `specs/`, plus three files.

    Python byte-code caches are build output, not source, so they are left out.
    """
    files: list[Path] = []
    for folder in ("backend/src", "specs"):
        for path in sorted((project_root / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts \
                    and not any(part.endswith(".egg-info") for part in path.parts):
                files.append(path)
    for name in ("docs/evaluation.md", "backend/pyproject.toml",
                 "backend/requirements-dev.lock"):
        files.append(project_root / name)
    manifest = {}
    for path in files:
        if not path.is_file():
            raise ForecastingError(f"source file missing: {path.relative_to(project_root)}")
        manifest[path.relative_to(project_root).as_posix()] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    return dict(sorted(manifest.items()))


def spec_status(project_root: Path) -> str:
    """The `Status:` line of this spec, as recorded in `run.json` `spec`."""
    path = project_root / "specs" / "003-forecasting-baseline.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Status:"):
            return line.removeprefix("Status:").strip()
    raise ForecastingError("spec 003 has no Status line")
