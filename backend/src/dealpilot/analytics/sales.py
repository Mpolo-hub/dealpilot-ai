"""Exact sales metrics over order lines (spec 002, sections 4 and 5.4).

User values only ever reach SQL as bound parameters. group_by and interval pick SQL
fragments from the fixed tables below.
"""
from __future__ import annotations

from datetime import date

import duckdb

ROW_LIMIT = 20_000  # D6
METRICS = ("units", "revenue", "orders", "order_lines")  # D11
DATE_BUCKETS = {  # Monday-start ISO weeks; bucket label = first day of the bucket
    "day": "o.order_date",
    "week": "CAST(date_trunc('week', o.order_date) AS DATE)",
    "month": "CAST(date_trunc('month', o.order_date) AS DATE)",
}
GROUP_COLUMNS = {  # group_by value -> (SQL expression, response key)
    "product": ("l.product_id", "product_id"),
    "category": ("p.category", "category"),
    "region": ("o.region_id", "region_id"),
}
FILTER_COLUMNS = {"product_id": "l.product_id", "category": "p.category", "region_id": "o.region_id"}

_FROM = (
    "FROM order_lines l JOIN orders o ON o.order_id = l.order_id "
    "JOIN products p ON p.product_id = l.product_id"
)
# Money stays DECIMAL and becomes text in DuckDB; COALESCE turns an empty sum into "0.00".
_METRICS_SQL = (
    "COALESCE(SUM(l.quantity), 0) AS units, "
    "CAST(CAST(COALESCE(SUM(l.line_total), 0) AS DECIMAL(38,2)) AS VARCHAR) AS revenue, "
    "COUNT(DISTINCT l.order_id) AS orders, "
    "COUNT(*) AS order_lines"
)


class ResultTooLarge(Exception):
    """More than ROW_LIMIT groups (D6)."""


def sales_metrics(
    con: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    group_by: list[str],
    interval: str,
    filters: dict[str, list[str]],
) -> tuple[list[dict], dict]:
    """Rows (only groups with sales, D5) and totals for order lines dated start..end."""
    where = ["o.order_date BETWEEN ? AND ?"]
    params: list = [start, end]
    for name, column in FILTER_COLUMNS.items():
        values = filters.get(name) or []
        if values:
            where.append(f"{column} IN ({', '.join('?' * len(values))})")
            params.extend(values)
    where_sql = "WHERE " + " AND ".join(where)

    rows: list[dict] = []
    if group_by:
        selects, keys = [], []
        for dimension in group_by:
            if dimension == "date":
                expr, key = DATE_BUCKETS[interval], "date"
            else:
                expr, key = GROUP_COLUMNS[dimension]
            selects.append(f'{expr} AS "{key}"')
            keys.append(key)
        positions = ", ".join(str(i) for i in range(1, len(keys) + 1))
        sql = (
            f"SELECT {', '.join(selects)}, {_METRICS_SQL} {_FROM} {where_sql} "
            f"GROUP BY {positions} ORDER BY {positions} LIMIT {ROW_LIMIT + 1}"
        )
        result = con.execute(sql, params).fetchall()
        if len(result) > ROW_LIMIT:
            raise ResultTooLarge
        names = keys + list(METRICS)
        rows = [_row(dict(zip(names, record))) for record in result]

    totals = con.execute(f"SELECT {_METRICS_SQL} {_FROM} {where_sql}", params).fetchone()
    return rows, _row(dict(zip(METRICS, totals)))


def _row(values: dict) -> dict:
    """JSON-ready: dates as YYYY-MM-DD, counts as int, revenue already a decimal string."""
    out = {}
    for key, value in values.items():
        if isinstance(value, date):
            value = value.isoformat()
        elif key in ("units", "orders", "order_lines"):
            value = int(value)
        out[key] = value
    return out
