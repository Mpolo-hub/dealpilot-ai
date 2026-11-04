"""/v1 endpoints (spec 002 section 5, and /v1/forecasts from spec 003 section 10 since the
2026-11-04 amendment of spec 002 D10). Read-only; never touches expected_demand.parquet.

Query parameters are read from the raw request so the checks run in the exact order of
section 3.5 (unknown parameters first, then data-free checks, then data, then data-based
checks, then result size). They are still listed in the OpenAPI docs via openapi_extra.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import APIRouter, Request
from starlette.datastructures import QueryParams

from dealpilot.analytics.dataset import open_dataset, parse_iso_date
from dealpilot.analytics.sales import (
    DATE_BUCKETS,
    FILTER_COLUMNS,
    METRICS,
    ROW_LIMIT,
    ResultTooLarge,
    sales_metrics,
)
from dealpilot.api.errors import APIError, detail
from dealpilot.forecasting.serving import (
    MAX_HORIZON,
    MIN_HISTORY_DAYS,
    SeriesKey,
    forecast_response,
)

router = APIRouter(prefix="/v1")

GROUP_BY = ("date", "product", "category", "region")
INTERVALS = tuple(DATE_BUCKETS)  # day, week, month
FILTERS = tuple(FILTER_COLUMNS)  # product_id, category, region_id
SINGLE_PARAMS = ("start", "end", "interval")
METRICS_PARAMS = {*SINGLE_PARAMS, "group_by", *FILTERS}
SALES_TABLES = ("regions", "products", "orders", "order_lines")


def _query_doc(name: str, description: str, repeatable: bool = False) -> dict:
    schema = {"type": "array", "items": {"type": "string"}} if repeatable else {"type": "string"}
    return {"name": name, "in": "query", "required": False, "description": description,
            "schema": schema, "explode": True}


def _reject_unknown(params: QueryParams, allowed: set[str]) -> None:
    """Step 1."""
    unknown = sorted({key for key in params if key not in allowed})
    if unknown:
        raise APIError(422, "unknown_parameter", "The request has parameters this endpoint "
                       "doesn't accept.", [detail(k, params.get(k), "unknown parameter")
                                           for k in unknown])


@router.get("/metadata")
def metadata(request: Request) -> dict:
    """Facts about the loaded dataset (5.2). Never returns `parameters`."""
    _reject_unknown(request.query_params, set())
    with open_dataset(()) as ds:
        meta = ds.metadata
        return {
            "seed": meta["seed"],
            "start": ds.start.isoformat(),
            "end": ds.end.isoformat(),
            "generator_version": meta["generator_version"],
            "library_versions": meta.get("library_versions"),
            "row_counts": meta["row_counts"],
        }


@router.get("/dimensions")
def dimensions(request: Request) -> dict:
    """What can be filtered and grouped (5.3). No size_weight, no list_price."""
    _reject_unknown(request.query_params, set())
    with open_dataset(("regions", "products")) as ds:
        regions = ds.con.execute("SELECT region_id, name FROM regions ORDER BY region_id").fetchall()
        products = ds.con.execute(
            "SELECT product_id, name, category, launch_date, discontinue_date "
            "FROM products ORDER BY product_id"
        ).fetchall()
        return {
            "date_range": {"start": ds.start.isoformat(), "end": ds.end.isoformat()},
            "group_by": list(GROUP_BY),
            "intervals": list(INTERVALS),
            "metrics": list(METRICS),
            "regions": [{"region_id": r, "name": n} for r, n in regions],
            "categories": sorted({p[2] for p in products}),
            "products": [
                {"product_id": pid, "name": name, "category": category,
                 "launch_date": launch.isoformat(),
                 "discontinue_date": stop.isoformat() if stop else None}
                for pid, name, category, launch, stop in products
            ],
        }


@router.get(
    "/sales/metrics",
    openapi_extra={"parameters": [
        _query_doc("start", "First day, YYYY-MM-DD. Default: dataset start."),
        _query_doc("end", "Last day, YYYY-MM-DD. Default: dataset end."),
        _query_doc("group_by", "date, product, category or region. Repeatable.", True),
        _query_doc("interval", "day, week or month. Only with group_by=date."),
        _query_doc("product_id", "Filter. Repeatable.", True),
        _query_doc("category", "Filter. Repeatable.", True),
        _query_doc("region_id", "Filter. Repeatable.", True),
    ]},
)
def sales_metrics_endpoint(request: Request) -> dict:
    """Exact sales totals, optionally filtered and grouped (5.4)."""
    params = request.query_params
    _reject_unknown(params, METRICS_PARAMS)

    # Step 2: checks that need no data.
    repeated = [detail(name, None, "given more than once") for name in SINGLE_PARAMS
                if len(params.getlist(name)) > 1]
    single = {name: params.get(name) if len(params.getlist(name)) == 1 else None
              for name in SINGLE_PARAMS}
    dates: dict[str, date | None] = {}
    bad_dates = []
    for name in ("start", "end"):
        raw = single[name]
        dates[name] = parse_iso_date(raw) if raw is not None else None
        if raw is not None and dates[name] is None:
            bad_dates.append(detail(name, raw, "not a real date in YYYY-MM-DD format"))
    if bad_dates:
        raise APIError(422, "invalid_date", "start and end must be real dates in YYYY-MM-DD "
                       "format.", bad_dates)

    group_by = params.getlist("group_by")
    unsupported = [detail("group_by", g, "must be one of: " + ", ".join(GROUP_BY))
                   for g in group_by if g not in GROUP_BY]
    if unsupported:
        raise APIError(422, "unsupported_dimension", "group_by has an unsupported value.",
                       unsupported)

    bad_params = list(repeated)
    bad_params += [detail("group_by", g, "given more than once")
                   for g in sorted({g for g in group_by if group_by.count(g) > 1})]
    interval = single["interval"]
    if interval is not None and interval not in INTERVALS:
        bad_params.append(detail("interval", interval, "must be one of: " + ", ".join(INTERVALS)))
    if interval is not None and "date" not in group_by:
        bad_params.append(detail("interval", interval, "only allowed with group_by=date"))
    if bad_params:
        raise APIError(422, "invalid_parameter", "The request has an invalid parameter.",
                       bad_params)

    filters = {name: params.getlist(name) for name in FILTERS}
    empty = [detail(name, value, "empty value")
             for name, values in filters.items() for value in values if value == ""]
    if empty:
        raise APIError(422, "invalid_filter", "Filter values must not be empty.", empty)
    filters = {name: sorted(set(values)) for name, values in filters.items()}

    # Step 3: data availability (raises DataUnavailable -> 503).
    with open_dataset(SALES_TABLES) as ds:
        # Step 4: checks against the data, after defaults.
        start = dates["start"] or ds.start
        end = dates["end"] or ds.end
        if start > end:
            raise APIError(422, "invalid_date_range", "start must not be after end.",
                           [detail("start", start.isoformat(), f"after end {end.isoformat()}")])
        outside = [detail(name, value.isoformat(),
                          f"outside the dataset range {ds.start.isoformat()} to "
                          f"{ds.end.isoformat()}")
                   for name, value in (("start", start), ("end", end))
                   if not ds.start <= value <= ds.end]
        if outside:
            raise APIError(422, "date_out_of_range", "Dates must be inside the dataset range.",
                           outside)
        unknown = _unknown_filter_values(ds.con, filters)
        if unknown:
            raise APIError(422, "invalid_filter", "A filter value doesn't exist in the data.",
                           unknown)

        # Step 5: query, with the row limit.
        use_interval = (interval or "day") if "date" in group_by else None
        try:
            rows, totals = sales_metrics(ds.con, start, end, group_by, use_interval or "day",
                                         filters)
        except ResultTooLarge:
            raise APIError(
                422, "result_too_large",
                f"The answer has more than {ROW_LIMIT} rows. Use a coarser interval, fewer "
                "group_by values, a shorter date range or more filters.",
                [detail("group_by", ",".join(group_by), f"more than {ROW_LIMIT} rows")],
            ) from None

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": group_by,
        "interval": use_interval,
        "filters": filters,
        "metrics": list(METRICS),
        "rows": rows,
        "totals": totals,
        "row_count": len(rows),
    }


def _unknown_filter_values(con, filters: dict[str, list[str]]) -> list[dict]:
    known = {
        "product_id": {r[0] for r in con.execute("SELECT product_id FROM products").fetchall()},
        "category": {r[0] for r in con.execute("SELECT DISTINCT category FROM products").fetchall()},
        "region_id": {r[0] for r in con.execute("SELECT region_id FROM regions").fetchall()},
    }
    return [detail(name, value, "not found in the data")
            for name, values in filters.items() for value in values if value not in known[name]]


# --------------------------------------------------------------------------- forecasts

FORECAST_LEVELS = ("total", "category", "product_region")
FORECAST_KEYS = {"total": (), "category": ("category",),
                 "product_region": ("product_id", "region_id")}
FORECAST_PARAMS = {"level", "category", "product_id", "region_id", "cutoff", "horizon"}
FORECAST_TABLES = ("regions", "products", "orders", "order_lines")
_DIGITS = re.compile(r"[0-9]{1,3}")


@router.get(
    "/forecasts",
    openapi_extra={"parameters": [
        _query_doc("level", "total, category or product_region. Required."),
        _query_doc("category", "Required when level=category, otherwise not allowed."),
        _query_doc("product_id", "Required when level=product_region, otherwise not allowed."),
        _query_doc("region_id", "Required when level=product_region, otherwise not allowed."),
        _query_doc("cutoff", "Last day of training data, YYYY-MM-DD. Default: dataset end."),
        _query_doc("horizon", "Days forecast after cutoff, 1 to 28. Default 28."),
    ]},
)
def forecasts_endpoint(request: Request) -> dict:
    """Seasonal naive forecast for one series (spec 003 section 10, D11 approved
    2026-11-04; spec 002 D10 amended). Never reads expected_demand.parquet or parameters."""
    params = request.query_params
    _reject_unknown(params, FORECAST_PARAMS)  # step 1

    # invalid_date: cutoff is not a real date (a repeated cutoff is invalid_parameter).
    cutoff_values = params.getlist("cutoff")
    cutoff_raw = cutoff_values[0] if len(cutoff_values) == 1 else None
    cutoff = parse_iso_date(cutoff_raw) if cutoff_raw is not None else None
    if cutoff_raw is not None and cutoff is None:
        raise APIError(422, "invalid_date", "cutoff must be a real date in YYYY-MM-DD format.",
                       [detail("cutoff", cutoff_raw, "not a real date in YYYY-MM-DD format")])

    # invalid_parameter: level, horizon, missing, extra or repeated key parameters.
    bad = [detail(name, None, "given more than once")
           for name in ("level", "cutoff", "horizon", "category", "product_id", "region_id")
           if len(params.getlist(name)) > 1]
    level = params.get("level") if len(params.getlist("level")) == 1 else None
    if "level" not in params:
        bad.append(detail("level", None, "required"))
    elif level is not None and level not in FORECAST_LEVELS:
        bad.append(detail("level", level, "must be one of: " + ", ".join(FORECAST_LEVELS)))
    horizon = MAX_HORIZON
    if len(params.getlist("horizon")) == 1:
        raw = params["horizon"]
        if _DIGITS.fullmatch(raw) and 1 <= int(raw) <= MAX_HORIZON:
            horizon = int(raw)
        else:
            bad.append(detail("horizon", raw, "must be an integer from 1 to 28"))
    if level in FORECAST_KEYS:
        needed = FORECAST_KEYS[level]
        bad += [detail(name, None, f"required when level={level}")
                for name in needed if name not in params]
        bad += [detail(name, params.get(name), f"not allowed when level={level}")
                for name in ("category", "product_id", "region_id")
                if name in params and name not in needed]
    if bad:
        raise APIError(422, "invalid_parameter", "The request has an invalid parameter.", bad)

    # invalid_filter: an empty key value.
    keys = {name: params[name] for name in FORECAST_KEYS[level]}
    empty = [detail(name, value, "empty value") for name, value in keys.items() if value == ""]
    if empty:
        raise APIError(422, "invalid_filter", "Key values must not be empty.", empty)

    with open_dataset(FORECAST_TABLES) as ds:  # data_unavailable (503)
        cutoff = cutoff or ds.end
        if not ds.start <= cutoff <= ds.end:
            raise APIError(422, "date_out_of_range", "cutoff must be inside the dataset range.",
                           [detail("cutoff", cutoff.isoformat(),
                                   f"outside the dataset range {ds.start.isoformat()} to "
                                   f"{ds.end.isoformat()}")])
        earliest = ds.start + timedelta(days=MIN_HISTORY_DAYS)
        if cutoff < earliest:
            raise APIError(422, "invalid_parameter", "Not enough history before the cutoff.",
                           [detail("cutoff", cutoff.isoformat(),
                                   f"must be on or after {earliest.isoformat()}")])
        unknown = _unknown_filter_values(ds.con, {name: [value] for name, value in keys.items()})
        if unknown:
            raise APIError(422, "invalid_filter", "A key value doesn't exist in the data.",
                           unknown)
        return forecast_response(ds.con, SeriesKey(level, **keys), ds.start, cutoff, horizon)
