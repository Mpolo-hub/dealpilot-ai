"""
Spec 003 section 10 (`GET /v1/forecasts`), criteria AC-FC-API-01 to AC-FC-API-05, binding
since D11 was approved on 2026-11-04 (spec 002 D10 and AC-API-17 amended the same day).

Data: the session seed-42 run from conftest (`generated_dir`). Expected forecasts come from
an independent DuckDB query and the section 6.1 formula written here, never from
`dealpilot.forecasting`. AC-FC-API-05 must stay the last test in this file.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from dealpilot.analytics import dataset
from dealpilot.api.main import app

URL = "/v1/forecasts"
CLOSED = {(12, 25), (1, 1)}  # spec 001 section 5.7
OTHER_CUTOFF = "2025-06-30"


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def data_hashes(generated_dir: Path) -> dict[str, str]:
    """Bytes of every data file before any test of this module (AC-FC-API-05)."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in generated_dir.iterdir()}


@pytest.fixture
def client(generated_dir: Path, data_hashes: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    return TestClient(app)


@pytest.fixture(scope="module")
def meta(generated_dir: Path) -> dict:
    return json.loads((generated_dir / "metadata.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def db(generated_dir: Path):
    con = duckdb.connect()
    for name in ("products", "orders", "order_lines"):
        con.read_parquet(str(generated_dir / f"{name}.parquet")).create_view(name)
    yield con
    con.close()


# --------------------------------------------------------------------------- oracle

def oracle_series(db, start: date, cutoff: date, where: str, params: list) -> dict[date, int]:
    rows = db.execute(
        "SELECT o.order_date, SUM(l.quantity) FROM orders o JOIN order_lines l USING (order_id) "
        f"JOIN products p USING (product_id) WHERE o.order_date <= ? {where} GROUP BY 1",
        [cutoff, *params]).fetchall()
    return {day: int(units) for day, units in rows if day >= start}


def oracle_forecast(series: dict[date, int], start: date, cutoff: date,
                    horizon: int) -> list[float]:
    """Spec 003 section 6.1, written independently of the code under test."""
    out = []
    for h in range(1, horizon + 1):
        source = cutoff - timedelta(days=6) + timedelta(days=(h - 1) % 7)
        while source >= start and (source.month, source.day) in CLOSED:
            source -= timedelta(days=7)
        out.append(float(series.get(source, 0)) if source >= start else 0.0)
    return out


CASES = [
    ("level=total", "", []),
    ("level=category&category=Outdoor", "AND p.category = ?", ["Outdoor"]),
    ("level=product_region&product_id=P001&region_id=R03",
     "AND l.product_id = ? AND o.region_id = ?", ["P001", "R03"]),
    # P031 launches on 2024-09-13 (AC-API-08): no history before then, so the forecast is 0.
    ("level=product_region&product_id=P031&region_id=R01",
     "AND l.product_id = ? AND o.region_id = ?", ["P031", "R01"]),
]


# --------------------------------------------------------------------------- AC-FC-API-01

@pytest.mark.parametrize(("query", "where", "params"), CASES)
@pytest.mark.parametrize("cutoff", [None, OTHER_CUTOFF])
def test_ac_fc_api_01_forecast_equals_section_6_1(client, db, meta, query, where, params,
                                                    cutoff) -> None:
    start = date.fromisoformat(meta["start"])
    use = date.fromisoformat(cutoff or meta["end"])
    url = f"{URL}?{query}" + (f"&cutoff={cutoff}" if cutoff else "")
    r = client.get(url)
    assert r.status_code == 200, r.text
    body = r.json()
    expected = oracle_forecast(oracle_series(db, start, use, where, params), start, use, 28)
    assert [p["forecast"] for p in body["points"]] == expected
    assert [p["date"] for p in body["points"]] == [
        (use + timedelta(days=h)).isoformat() for h in range(1, 29)]
    assert all(p["lower_80"] is None and p["upper_80"] is None for p in body["points"])
    assert body["cutoff"] == use.isoformat() and body["horizon"] == 28
    assert body["model"] == {"name": "seasonal_naive", "version": "1.0",
                             "settings": {"lag_days": 7, "closed_day_fallback": "weekly"}}
    assert body["uses_planned_promotions"] is False
    assert set(body) == {"level", "key", "cutoff", "horizon", "model",
                         "uses_planned_promotions", "points"}


def test_ac_fc_api_01_keys_horizon_and_closed_source(client, db, meta) -> None:
    """Keys per level, a short horizon, and the weekly fallback over Dec 25 and Jan 1."""
    assert client.get(f"{URL}?level=total").json()["key"] == {}
    assert client.get(f"{URL}?level=category&category=Outdoor").json()["key"] == {
        "category": "Outdoor"}
    body = client.get(f"{URL}?level=product_region&product_id=P001&region_id=R03"
                      "&horizon=7").json()
    assert body["key"] == {"product_id": "P001", "region_id": "R03"} and len(body["points"]) == 7
    start = date.fromisoformat(meta["start"])
    cutoff = date(2025, 1, 2)  # sources include 2024-12-27 .. 2025-01-02, with Jan 1 closed
    body = client.get(f"{URL}?level=total&cutoff={cutoff}&horizon=14").json()
    expected = oracle_forecast(oracle_series(db, start, cutoff, "", []), start, cutoff, 14)
    assert [p["forecast"] for p in body["points"]] == expected
    assert all(v > 0 for v in expected)  # the closed source day was replaced by lag 14


# --------------------------------------------------------------------------- AC-FC-API-02

INVALID = [
    # (query, status, code); the order of section 10 decides when several things are wrong.
    ("level=total&foo=1", 422, "unknown_parameter"),
    ("level=bogus&foo=1&cutoff=nope", 422, "unknown_parameter"),
    ("level=total&cutoff=2025-13-01", 422, "invalid_date"),
    ("level=total&cutoff=yesterday", 422, "invalid_date"),
    ("level=total&cutoff=", 422, "invalid_date"),
    ("level=bogus&cutoff=nope", 422, "invalid_date"),
    ("", 422, "invalid_parameter"),
    ("level=", 422, "invalid_parameter"),
    ("level=bogus", 422, "invalid_parameter"),
    ("level=Total", 422, "invalid_parameter"),
    ("level=total&level=total", 422, "invalid_parameter"),
    ("level=total&horizon=0", 422, "invalid_parameter"),
    ("level=total&horizon=29", 422, "invalid_parameter"),
    ("level=total&horizon=abc", 422, "invalid_parameter"),
    ("level=total&horizon=", 422, "invalid_parameter"),
    ("level=total&horizon=7&horizon=7", 422, "invalid_parameter"),
    ("level=category", 422, "invalid_parameter"),
    ("level=category&category=Outdoor&category=Outdoor", 422, "invalid_parameter"),
    ("level=total&category=Outdoor", 422, "invalid_parameter"),
    ("level=category&category=Outdoor&product_id=P001", 422, "invalid_parameter"),
    ("level=product_region&product_id=P001", 422, "invalid_parameter"),
    ("level=product_region&region_id=R01", 422, "invalid_parameter"),
    ("level=product_region&product_id=P001&region_id=R01&category=Outdoor", 422,
     "invalid_parameter"),
    ("level=total&product_id=", 422, "invalid_parameter"),  # extra beats empty
    ("level=category&category=", 422, "invalid_filter"),
    ("level=product_region&product_id=&region_id=R01", 422, "invalid_filter"),
    ("level=total&cutoff=2022-12-31", 422, "date_out_of_range"),
    ("level=total&cutoff=2026-01-01", 422, "date_out_of_range"),
    ("level=total&cutoff=2023-01-06", 422, "invalid_parameter"),  # before start + 6
    ("level=category&category=Toys", 422, "invalid_filter"),
    ("level=product_region&product_id=P999&region_id=R01", 422, "invalid_filter"),
    ("level=product_region&product_id=P001&region_id=r01", 422, "invalid_filter"),
    ("level=category&category=Toys&cutoff=2022-12-31", 422, "date_out_of_range"),
    ("level=category&category=Toys&cutoff=2023-01-02", 422, "invalid_parameter"),
]


@pytest.mark.parametrize(("query", "status", "code"), INVALID)
def test_ac_fc_api_02_parameter_table_and_check_order(client, query, status, code) -> None:
    r = client.get(f"{URL}?{query}")
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code


def test_ac_fc_api_02_edges_and_data_checks(client, generated_dir, tmp_path, monkeypatch) -> None:
    """Horizon 1 and 28 and cutoff start + 6 are accepted; missing data gives 503 before
    any data-based check, and an empty value is still checked before the data."""
    assert client.get(f"{URL}?level=total&horizon=1").status_code == 200
    assert client.get(f"{URL}?level=total&horizon=28").status_code == 200
    assert client.get(f"{URL}?level=total&cutoff=2023-01-07").status_code == 200
    monkeypatch.setenv(dataset.ENV_VAR, str(tmp_path / "missing"))
    assert client.get(f"{URL}?level=category&category=").json()["error"]["code"] == "invalid_filter"
    r = client.get(f"{URL}?level=category&category=Toys&cutoff=2022-12-31")
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"


# --------------------------------------------------------------------------- AC-FC-API-03

def _change_after(source: Path, target: Path, cutoff: date) -> None:
    """Copy of the data where every sales row after `cutoff` has a different quantity."""
    shutil.copytree(source, target)
    orders = pq.read_table(target / "orders.parquet", columns=["order_id", "order_date"])
    late = pc.filter(orders["order_id"],
                     pc.greater(orders["order_date"], pa.scalar(cutoff, pa.date32())))
    lines = pq.read_table(target / "order_lines.parquet")
    is_late = pc.is_in(lines["order_id"], value_set=late)
    quantity = lines["quantity"]
    changed = pc.if_else(is_late, pc.add(pc.multiply(quantity, 5), 3), quantity)
    index = lines.schema.get_field_index("quantity")
    lines = lines.set_column(index, lines.schema.field(index), changed.cast(quantity.type))
    pq.write_table(lines, target / "order_lines.parquet")


@pytest.mark.parametrize("cutoff", ["2024-10-03", OTHER_CUTOFF])
def test_ac_fc_api_03_no_data_after_the_cutoff(client, generated_dir, tmp_path, monkeypatch,
                                               cutoff) -> None:
    queries = [q for q, _, _ in CASES]
    before = {q: client.get(f"{URL}?{q}&cutoff={cutoff}").json() for q in queries}
    copy = tmp_path / "changed"
    _change_after(generated_dir, copy, date.fromisoformat(cutoff))
    monkeypatch.setenv(dataset.ENV_VAR, str(copy))
    # The copy really differs after the cutoff...
    later = date.fromisoformat(cutoff) + timedelta(days=28)
    changed = client.get(f"{URL}?level=total&cutoff={later}").json()
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    assert changed != client.get(f"{URL}?level=total&cutoff={later}").json()
    # ...but forecasts made at the cutoff are identical.
    monkeypatch.setenv(dataset.ENV_VAR, str(copy))
    for q in queries:
        assert client.get(f"{URL}?{q}&cutoff={cutoff}").json() == before[q]


# --------------------------------------------------------------------------- AC-FC-API-04

def test_ac_fc_api_04_no_expected_demand_or_parameters(client, generated_dir, tmp_path,
                                                       monkeypatch) -> None:
    queries = [q for q, _, _ in CASES]
    full = {q: client.get(f"{URL}?{q}").json() for q in queries}
    copy = tmp_path / "stripped"
    shutil.copytree(generated_dir, copy)
    (copy / "expected_demand.parquet").unlink()
    metadata = json.loads((copy / "metadata.json").read_text(encoding="utf-8"))
    del metadata["parameters"]
    (copy / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setenv(dataset.ENV_VAR, str(copy))
    for q in queries:
        r = client.get(f"{URL}?{q}")
        assert r.status_code == 200 and r.json() == full[q]
        for hidden in ("expected_units", "parameters", "base_demand", "size_weight"):
            assert hidden not in r.text


# --------------------------------------------------------------------------- AC-FC-API-05

def test_ac_fc_api_05_data_folder_is_unchanged(client, generated_dir, data_hashes) -> None:
    """Last test of the file: the data files have the same bytes as before."""
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in generated_dir.iterdir()}
    assert after == data_hashes
