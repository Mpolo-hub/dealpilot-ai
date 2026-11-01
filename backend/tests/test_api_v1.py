"""
Spec 002 (API v1) acceptance criteria AC-API-01 to AC-API-17.

Data: the session seed-42 run from conftest (`generated_dir`). Expected values come from
SQL written here against the same Parquet files, not from dealpilot.analytics. Money is
compared as Decimal. AC-API-16 must stay the last test in this file: it checks that the
data files were not changed by any test before it.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from dealpilot import __version__
from dealpilot.analytics import dataset
from dealpilot.api.main import app

MONEY = re.compile(r"^[0-9]+\.[0-9]{2}$")
REQUIRED = ("metadata.json", "regions.parquet", "products.parquet", "orders.parquet",
            "order_lines.parquet")
V1_ENDPOINTS = ("/v1/metadata", "/v1/dimensions", "/v1/sales/metrics")
ERROR_KEYS = {"code", "message", "details"}


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def data_hashes(generated_dir: Path) -> dict[str, str]:
    """Bytes of every data file before any API test runs (for AC-API-16)."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in generated_dir.iterdir()}


@pytest.fixture
def client(generated_dir: Path, data_hashes: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    return TestClient(app)


@pytest.fixture(scope="module")
def db(generated_dir: Path):
    """Independent DuckDB connection over the same files (test oracle)."""
    con = duckdb.connect()
    for name in ("regions", "products", "orders", "order_lines"):
        con.read_parquet(str(generated_dir / f"{name}.parquet")).create_view(name)
    yield con
    con.close()


@pytest.fixture(scope="module")
def meta(generated_dir: Path) -> dict:
    return json.loads((generated_dir / "metadata.json").read_text(encoding="utf-8"))


def expected(db, start: str, end: str, group_cols: list[str] | None = None,
             where: str = "", params: tuple = ()) -> list[tuple]:
    """Oracle query: (group values..., units, revenue Decimal, orders, order_lines)."""
    group_cols = group_cols or []
    select = ", ".join(group_cols + [
        "SUM(l.quantity)", "SUM(l.line_total)", "COUNT(DISTINCT l.order_id)", "COUNT(*)"])
    group = f"GROUP BY {', '.join(group_cols)} ORDER BY {', '.join(group_cols)}" if group_cols else ""
    sql = (f"SELECT {select} FROM order_lines l JOIN orders o USING (order_id) "
           f"JOIN products p USING (product_id) "
           f"WHERE o.order_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) {where} {group}")
    return db.execute(sql, [start, end, *params]).fetchall()


def as_tuples(rows: list[dict], keys: list[str]) -> list[tuple]:
    return [tuple(r[k] for k in keys) + (r["units"], Decimal(r["revenue"]), r["orders"],
                                         r["order_lines"]) for r in rows]


def copy_data(src: Path, dst: Path, skip: str) -> Path:
    dst.mkdir()
    for f in src.iterdir():
        if f.name != skip:
            shutil.copy2(f, dst / f.name)
    return dst


def metrics(client: TestClient, query: str = "") -> dict:
    r = client.get(f"/v1/sales/metrics{query}")
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- AC-API-01

def test_ac_api_01_health_unchanged_without_data(tmp_path: Path, monkeypatch) -> None:
    """AC-API-01: /health is unchanged, ignores extra parameters and needs no data."""
    monkeypatch.setenv(dataset.ENV_VAR, str(tmp_path))  # empty folder
    c = TestClient(app)
    for url in ("/health", "/health?foo=1"):
        r = c.get(url)
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": __version__}
    r = c.post("/health")
    assert r.status_code == 405
    assert r.json() == {"detail": "Method Not Allowed"}
    assert r.headers["allow"] == "GET"


# --------------------------------------------------------------------------- AC-API-02/03

def test_ac_api_02_metadata_matches_file(client: TestClient, meta: dict) -> None:
    """AC-API-02: every returned field equals metadata.json; no `parameters`."""
    body = client.get("/v1/metadata").json()
    assert set(body) == {"seed", "start", "end", "generator_version", "library_versions",
                         "row_counts"}
    for key, value in body.items():
        assert value == meta.get(key), key
    assert "parameters" not in body


def test_ac_api_03_dimensions_match_files(client: TestClient, db, meta: dict) -> None:
    """AC-API-03: regions, products, categories equal the Parquet contents, sorted."""
    r = client.get("/v1/dimensions")
    body = r.json()
    regions = db.execute("SELECT region_id, name FROM regions ORDER BY region_id").fetchall()
    products = db.execute("SELECT product_id, name, category, launch_date, discontinue_date "
                          "FROM products ORDER BY product_id").fetchall()
    assert body["date_range"] == {"start": meta["start"], "end": meta["end"]}
    assert body["group_by"] == ["date", "product", "category", "region"]
    assert body["intervals"] == ["day", "week", "month"]
    assert body["metrics"] == ["units", "revenue", "orders", "order_lines"]
    assert [(x["region_id"], x["name"]) for x in body["regions"]] == regions
    assert len(body["regions"]) == 5
    assert body["categories"] == sorted({p[2] for p in products})
    assert len(body["categories"]) == 5
    assert len(body["products"]) == 50
    for got, (pid, name, category, launch, stop) in zip(body["products"], products):
        assert set(got) == {"product_id", "name", "category", "launch_date", "discontinue_date"}
        assert got == {"product_id": pid, "name": name, "category": category,
                       "launch_date": launch.isoformat(),
                       "discontinue_date": stop.isoformat() if stop else None}
    for forbidden in ("size_weight", "list_price", "base_demand"):
        assert forbidden not in r.text


# --------------------------------------------------------------------------- AC-API-04/05/06

def test_ac_api_04_totals_are_exact(client: TestClient, db, meta: dict) -> None:
    """AC-API-04: default range, no group_by: totals equal the raw sums."""
    body = metrics(client)
    units, revenue, orders, lines = expected(db, meta["start"], meta["end"])[0]
    assert body["rows"] == [] and body["row_count"] == 0
    assert body["totals"]["units"] == units
    assert Decimal(body["totals"]["revenue"]) == revenue
    assert body["totals"]["revenue"] == "75194247.93"  # seed 42 value from the spec
    assert body["totals"]["orders"] == orders == meta["row_counts"]["orders"] == 90_643
    assert body["totals"]["order_lines"] == lines == meta["row_counts"]["order_lines"] == 246_500


def test_ac_api_05_money_is_a_two_decimal_string(client: TestClient) -> None:
    """AC-API-05: every money value is a string matching ^[0-9]+\\.[0-9]{2}$."""
    queries = [
        "", "?group_by=product", "?group_by=category", "?group_by=region",
        "?group_by=date&interval=week", "?group_by=date&interval=month&group_by=region",
        "?start=2024-12-25&end=2024-12-25&group_by=date", "?product_id=P001&group_by=date",
    ]
    seen = 0
    for q in queries:
        body = metrics(client, q)
        for item in [body["totals"], *body["rows"]]:
            assert isinstance(item["revenue"], str) and MONEY.match(item["revenue"]), item
            seen += 1
    assert seen > 100


@pytest.mark.parametrize("dimension", ["date", "product", "category", "region"])
def test_ac_api_06_groups_add_up(client: TestClient, dimension: str) -> None:
    """AC-API-06: rows add up to totals; orders only for date and region."""
    body = metrics(client, f"?group_by={dimension}&start=2024-01-01&end=2024-12-31")
    totals, rows = body["totals"], body["rows"]
    assert sum(r["units"] for r in rows) == totals["units"]
    assert sum(r["order_lines"] for r in rows) == totals["order_lines"]
    assert sum(Decimal(r["revenue"]) for r in rows) == Decimal(totals["revenue"])
    if dimension in ("date", "region"):
        assert sum(r["orders"] for r in rows) == totals["orders"]
    else:  # an order can hold several products, so these overcount (section 4)
        assert sum(r["orders"] for r in rows) > totals["orders"]


# --------------------------------------------------------------------------- AC-API-07/08

def test_ac_api_07_date_buckets(client: TestClient, db, meta: dict) -> None:
    """AC-API-07: day/week/month buckets over the full range match the oracle."""
    start, end = meta["start"], meta["end"]
    closed = {d for d in (date(y, m, dd) for y in (2023, 2024, 2025) for m, dd in ((1, 1), (12, 25)))}

    day = metrics(client, "?group_by=date&interval=day")
    assert day["interval"] == "day" and day["row_count"] == 1_090
    assert not {date.fromisoformat(r["date"]) for r in day["rows"]} & closed
    assert as_tuples(day["rows"], ["date"]) == [
        (d.isoformat(), *rest) for d, *rest in expected(db, start, end, ["o.order_date"])]

    week = metrics(client, "?group_by=date&interval=week")
    assert week["row_count"] == 157
    assert all(date.fromisoformat(r["date"]).weekday() == 0 for r in week["rows"])
    assert week["rows"][0]["date"] == "2023-01-02"
    assert as_tuples(week["rows"], ["date"]) == [
        (d.isoformat(), *rest)
        for d, *rest in expected(db, start, end, ["CAST(date_trunc('week', o.order_date) AS DATE)"])]

    month = metrics(client, "?group_by=date&interval=month")
    assert month["row_count"] == 36
    assert all(r["date"].endswith("-01") for r in month["rows"])
    assert as_tuples(month["rows"], ["date"]) == [
        (d.isoformat(), *rest)
        for d, *rest in expected(db, start, end, ["CAST(date_trunc('month', o.order_date) AS DATE)"])]


def test_ac_api_08_only_groups_with_sales(client: TestClient, db, meta: dict) -> None:
    """AC-API-08: late launches have no rows before launch; a closed day returns no rows."""
    late = db.execute("SELECT product_id, launch_date FROM products "
                      "WHERE launch_date > CAST(? AS DATE)", [meta["start"]]).fetchall()
    assert ("P031", date(2024, 9, 13)) in late  # the spec's seed-42 example
    body = metrics(client, "?group_by=product&start=2024-01-01&end=2024-09-12")
    assert "P031" not in {r["product_id"] for r in body["rows"]}
    for pid, launch in late:
        before = (launch - timedelta(days=1)).isoformat()
        body = metrics(client, f"?group_by=product&start={meta['start']}&end={before}")
        assert pid not in {r["product_id"] for r in body["rows"]}

    body = metrics(client, "?group_by=date&start=2024-12-25&end=2024-12-25")
    assert body["rows"] == [] and body["row_count"] == 0
    assert body["totals"] == {"units": 0, "revenue": "0.00", "orders": 0, "order_lines": 0}


# --------------------------------------------------------------------------- AC-API-09

@pytest.mark.parametrize(("query", "where", "params"), [
    ("product_id=P001", "AND l.product_id IN (?)", ("P001",)),
    ("product_id=P002&product_id=P001&product_id=P002", "AND l.product_id IN (?, ?)",
     ("P001", "P002")),
    ("category=Home", "AND p.category IN (?)", ("Home",)),
    ("category=Home&category=Outdoor", "AND p.category IN (?, ?)", ("Home", "Outdoor")),
    ("region_id=R03", "AND o.region_id IN (?)", ("R03",)),
    ("region_id=R01&region_id=R05", "AND o.region_id IN (?, ?)", ("R01", "R05")),
    ("category=Home&category=Office&region_id=R02&product_id=P015&product_id=P021",
     "AND p.category IN (?, ?) AND o.region_id IN (?) AND l.product_id IN (?, ?)",
     ("Home", "Office", "R02", "P015", "P021")),
    ("category=Home&product_id=P001", "AND p.category IN (?) AND l.product_id IN (?)",
     ("Home", "P001")),  # no product is both: empty result
])
def test_ac_api_09_filters(client: TestClient, db, query: str, where: str, params: tuple) -> None:
    """AC-API-09: OR within a parameter, AND across; grouped rows and totals match."""
    start, end = "2024-03-01", "2024-08-31"
    body = metrics(client, f"?start={start}&end={end}&group_by=region&{query}")
    assert as_tuples(body["rows"], ["region_id"]) == expected(
        db, start, end, ["o.region_id"], where, params)
    (units, revenue, orders, lines), = expected(db, start, end, None, where, params)
    assert body["totals"]["units"] == (units or 0)
    assert Decimal(body["totals"]["revenue"]) == (revenue or Decimal(0))
    assert (body["totals"]["orders"], body["totals"]["order_lines"]) == (orders, lines)
    # Echo: each filter de-duplicated and sorted ascending (I5)
    for name in ("product_id", "category", "region_id"):
        given = [part.split("=", 1)[1] for part in query.split("&") if part.startswith(name + "=")]
        assert body["filters"][name] == sorted(set(given))


# --------------------------------------------------------------------------- AC-API-10/11

VALIDATION_CASES = [
    ("/v1/sales/metrics?start=2025-13-01", "invalid_date"),
    ("/v1/sales/metrics?start=yesterday", "invalid_date"),
    ("/v1/sales/metrics?start=2025-02-01&end=2025-01-01", "invalid_date_range"),
    ("/v1/sales/metrics?start=2022-12-31", "date_out_of_range"),
    ("/v1/sales/metrics?end=2026-01-01", "date_out_of_range"),
    ("/v1/sales/metrics?group_by=channel", "unsupported_dimension"),
    ("/v1/sales/metrics?group_by=date&group_by=date", "invalid_parameter"),
    ("/v1/sales/metrics?interval=week", "invalid_parameter"),
    ("/v1/sales/metrics?group_by=date&interval=year", "invalid_parameter"),
    ("/v1/sales/metrics?product_id=P999", "invalid_filter"),
    ("/v1/sales/metrics?product_id=", "invalid_filter"),
    ("/v1/sales/metrics?category=Toys", "invalid_filter"),
    ("/v1/sales/metrics?region_id=r01", "invalid_filter"),
    ("/v1/sales/metrics?foo=1", "unknown_parameter"),
    ("/v1/metadata?foo=1", "unknown_parameter"),
    ("/v1/dimensions?foo=1", "unknown_parameter"),
]


@pytest.mark.parametrize(("url", "code"), VALIDATION_CASES)
def test_ac_api_10_validation(client: TestClient, url: str, code: str) -> None:
    """AC-API-10: each bad request returns 422 and the stated error code."""
    r = client.get(url)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


def test_ac_api_10_check_order(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """Section 3.5 order: date order before range; empty filter before data; unknown first."""
    r = client.get("/v1/sales/metrics?start=2022-12-01&end=2022-11-01")
    assert r.json()["error"]["code"] == "invalid_date_range"
    r = client.get("/v1/sales/metrics?start=2025-13-01&foo=1")
    assert r.json()["error"]["code"] == "unknown_parameter"
    monkeypatch.setenv(dataset.ENV_VAR, str(tmp_path / "missing"))
    assert client.get("/v1/sales/metrics?product_id=").status_code == 422
    assert client.get("/v1/sales/metrics?product_id=P999").status_code == 503


def _assert_error_body(r) -> None:
    body = r.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == ERROR_KEYS
    assert isinstance(body["error"]["code"], str) and isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], list)
    for item in body["error"]["details"]:
        assert set(item) == {"parameter", "value", "reason"}
    assert "detail" not in body


def test_ac_api_11_one_error_format_on_v1(client: TestClient) -> None:
    """AC-API-11: all /v1 errors share the 3.5 body; outside /v1 FastAPI's defaults stay."""
    for url, code in VALIDATION_CASES:
        r = client.get(url)
        _assert_error_body(r)
        assert r.json()["error"]["code"] == code
    r = client.get("/v1/unknown")
    assert r.status_code == 404
    _assert_error_body(r)
    assert r.json()["error"]["code"] == "not_found"
    r = client.post("/v1/metadata")
    assert r.status_code == 405
    _assert_error_body(r)
    assert r.json()["error"]["code"] == "method_not_allowed"
    r = client.get("/unknown")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


# --------------------------------------------------------------------------- AC-API-12/13/14

def _data_cases(tmp_path: Path, generated_dir: Path) -> list[tuple[Path, list[str]]]:
    return [
        (tmp_path / "does_not_exist", ["data folder does not exist"]),
        (tmp_path / "empty", [f"{name} is missing" for name in REQUIRED]),
        (copy_data(generated_dir, tmp_path / "no_orders", skip="orders.parquet"),
         ["orders.parquet is missing"]),
    ]


def test_ac_api_12_data_unavailable(tmp_path: Path, generated_dir: Path, monkeypatch) -> None:
    """AC-API-12: missing folder or files -> 503 on every /v1 endpoint; /health stays 200."""
    (tmp_path / "empty").mkdir()
    c = TestClient(app)
    for folder, reasons in _data_cases(tmp_path, generated_dir):
        monkeypatch.setenv(dataset.ENV_VAR, str(folder))
        for url in V1_ENDPOINTS:
            r = c.get(url)
            assert r.status_code == 503, (url, r.text)
            _assert_error_body(r)
            error = r.json()["error"]
            assert error["code"] == "data_unavailable"
            assert "DEALPILOT_DATA_DIR" in error["message"]
            assert "dealpilot.data.generate" in error["message"]
            assert error["details"] == [
                {"parameter": "DEALPILOT_DATA_DIR", "value": "<absolute path>", "reason": reason}
                for reason in reasons]
            for form in {str(folder), folder.as_posix(), str(tmp_path), tmp_path.as_posix(),
                         json.dumps(str(tmp_path))[1:-1]}:
                assert form not in r.text
        assert c.get("/health").status_code == 200


def test_ac_api_13_data_path_rule(tmp_path: Path, monkeypatch) -> None:
    """AC-API-13: absolute as is; relative and default joined to the project root."""
    root = dataset.find_project_root()
    assert root is not None and (root / "backend" / "pyproject.toml").is_file()
    assert (root / "specs").is_dir()  # it is the repository root, not backend/
    monkeypatch.chdir(tmp_path)  # the server's current folder must not matter
    assert dataset.resolve_data_dir(str(tmp_path), root) == tmp_path
    assert dataset.resolve_data_dir("some/where", root) == root / "some" / "where"
    assert dataset.resolve_data_dir(None, root) == root / "data" / "raw"
    assert dataset.resolve_data_dir("", root) == root / "data" / "raw"
    assert dataset.resolve_data_dir(str(tmp_path), None) == tmp_path
    with pytest.raises(dataset.DataUnavailable) as err:
        dataset.resolve_data_dir("data/raw", None)
    assert err.value.reasons == ["project root not found"]
    assert dataset.shown_value(None) == "data/raw"
    assert dataset.shown_value("rel/dir") == "rel/dir"
    assert dataset.shown_value(str(tmp_path)) == "<absolute path>"


def test_ac_api_14_expected_demand_is_never_used(tmp_path: Path, generated_dir: Path,
                                                 monkeypatch) -> None:
    """AC-API-14: same answers without expected_demand.parquet; no hidden fields leak."""
    urls = ["/v1/metadata", "/v1/dimensions", "/v1/sales/metrics",
            "/v1/sales/metrics?group_by=date&interval=month&group_by=category",
            "/v1/sales/metrics?group_by=product&start=2025-01-01&end=2025-03-31"]
    c = TestClient(app)
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    full = {url: c.get(url) for url in urls}
    without = copy_data(generated_dir, tmp_path / "no_expected", skip="expected_demand.parquet")
    monkeypatch.setenv(dataset.ENV_VAR, str(without))
    for url in urls:
        r = c.get(url)
        assert r.status_code == 200 == full[url].status_code
        assert r.json() == full[url].json()
        for hidden in ("expected_units", "parameters", "base_demand"):
            assert hidden not in r.text


# --------------------------------------------------------------------------- AC-API-15/17

def test_ac_api_15_size_limit(client: TestClient, db, meta: dict) -> None:
    """AC-API-15: 48,427 groups are rejected; 8,212 are allowed."""
    r = client.get("/v1/sales/metrics?group_by=date&group_by=product")
    assert r.status_code == 422 and r.json()["error"]["code"] == "result_too_large"
    assert r.json()["error"]["details"] == [
        {"parameter": "group_by", "value": "date,product", "reason": "more than 20000 rows"}]
    body = metrics(client, "?group_by=date&interval=month&group_by=product&group_by=region")
    month_expr = "CAST(date_trunc('month', o.order_date) AS DATE)"
    assert body["row_count"] == len(expected(
        db, meta["start"], meta["end"], [month_expr, "l.product_id", "o.region_id"])) == 8_212


def test_ac_api_17_forecasting_is_not_served(client: TestClient) -> None:
    """AC-API-17: /v1/forecasts is not a route; the schema has no forecast path."""
    r = client.get("/v1/forecasts")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "forecast" in p]
    assert {"/health", "/v1/metadata", "/v1/dimensions", "/v1/sales/metrics"} <= set(paths)


def test_api_sorting_follows_group_by_order(client: TestClient) -> None:
    """Section 5.4: rows sort by group columns in the order given; group_by echoes it."""
    body = metrics(client, "?group_by=region&group_by=date&interval=month&start=2025-01-01"
                           "&end=2025-03-31")
    assert body["group_by"] == ["region", "date"]
    keys = [(r["region_id"], r["date"]) for r in body["rows"]]
    assert keys == sorted(keys) and keys[0] == ("R01", "2025-01-01")


# --------------------------------------------------------------------------- AC-API-16 (last)

def test_ac_api_16_read_only(generated_dir: Path, data_hashes: dict) -> None:
    """AC-API-16: every data file has the same bytes as before the API tests ran."""
    now = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in generated_dir.iterdir()}
    assert now == data_hashes
