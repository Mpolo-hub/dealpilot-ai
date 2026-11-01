"""
AC-02 — Every DQ rule in section 7 passes.

Spec §7 (binding):
  DQ-01  Every primary key is unique and not null.
  DQ-02  Every foreign key points to an existing row.
  DQ-03  No nulls except the columns marked nullable.
  DQ-04  quantity >= 1 (int), unit_price > 0, line_total > 0.
  DQ-05  discount_pct in [0.00, 0.35].
  DQ-06  line_total = round_half_up(quantity * unit_price * (1 - discount_pct), 2).
  DQ-07  Every order_date within --start and --end.
  DQ-08  No order before the customer's signup_date.
  DQ-09  No line for a product before its launch_date or on/after discontinue_date.
  DQ-10  promo_id set exactly when a promo is active; discount_pct matches promo + Enterprise.
  DQ-11  orders.region_id matches the customer's region.
  DQ-12  Every order has at least one line.
  DQ-13  Money values have at most 2 decimal places.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from conftest import as_ns_dates

# ---------------------------------------------------------------------------
# DQ-01: PKs unique and not null
# ---------------------------------------------------------------------------

def test_ac_02_dq01_regions_pk(tables: dict) -> None:
    """DQ-01: regions.region_id is unique and not null."""
    df = tables["regions"]
    assert df["region_id"].notna().all(), "Null region_id found"
    assert df["region_id"].is_unique, "Duplicate region_id found"


def test_ac_02_dq01_products_pk(tables: dict) -> None:
    """DQ-01: products.product_id is unique and not null."""
    df = tables["products"]
    assert df["product_id"].notna().all()
    assert df["product_id"].is_unique


def test_ac_02_dq01_customers_pk(tables: dict) -> None:
    """DQ-01: customers.customer_id is unique and not null."""
    df = tables["customers"]
    assert df["customer_id"].notna().all()
    assert df["customer_id"].is_unique


def test_ac_02_dq01_promotions_pk(tables: dict) -> None:
    """DQ-01: promotions.promo_id is unique and not null."""
    df = tables["promotions"]
    assert df["promo_id"].notna().all()
    assert df["promo_id"].is_unique


def test_ac_02_dq01_orders_pk(tables: dict) -> None:
    """DQ-01: orders.order_id is unique and not null."""
    df = tables["orders"]
    assert df["order_id"].notna().all()
    assert df["order_id"].is_unique


def test_ac_02_dq01_order_lines_pk(tables: dict) -> None:
    """DQ-01: order_lines composite PK (order_id, line_no) is unique and not null."""
    df = tables["order_lines"]
    assert df["order_id"].notna().all()
    assert df["line_no"].notna().all()
    assert not df.duplicated(subset=["order_id", "line_no"]).any()


def test_ac_02_dq01_expected_demand_pk(tables: dict) -> None:
    """DQ-01: expected_demand PK (date, product_id, region_id) unique and not null."""
    df = tables["expected_demand"]
    for col in ("date", "product_id", "region_id"):
        assert df[col].notna().all(), f"Null {col} in expected_demand"
    assert not df.duplicated(subset=["date", "product_id", "region_id"]).any()


# ---------------------------------------------------------------------------
# DQ-02: FKs point to existing rows
# ---------------------------------------------------------------------------

def test_ac_02_dq02_customers_region_fk(tables: dict) -> None:
    """DQ-02: customers.region_id references regions."""
    valid = set(tables["regions"]["region_id"])
    bad = ~tables["customers"]["region_id"].isin(valid)
    assert not bad.any(), f"{bad.sum()} customers have invalid region_id"


def test_ac_02_dq02_promotions_product_fk(tables: dict) -> None:
    """DQ-02: promotions.product_id references products."""
    valid = set(tables["products"]["product_id"])
    bad = ~tables["promotions"]["product_id"].isin(valid)
    assert not bad.any()


def test_ac_02_dq02_promotions_region_fk(tables: dict) -> None:
    """DQ-02: promotions.region_id references regions when not null."""
    df = tables["promotions"]
    with_region = df["region_id"].dropna()
    valid = set(tables["regions"]["region_id"])
    bad = ~with_region.isin(valid)
    assert not bad.any()


def test_ac_02_dq02_orders_customer_fk(tables: dict) -> None:
    """DQ-02: orders.customer_id references customers."""
    valid = set(tables["customers"]["customer_id"])
    bad = ~tables["orders"]["customer_id"].isin(valid)
    assert not bad.any()


def test_ac_02_dq02_orders_region_fk(tables: dict) -> None:
    """DQ-02: orders.region_id references regions."""
    valid = set(tables["regions"]["region_id"])
    bad = ~tables["orders"]["region_id"].isin(valid)
    assert not bad.any()


def test_ac_02_dq02_order_lines_order_fk(tables: dict) -> None:
    """DQ-02: order_lines.order_id references orders."""
    valid = set(tables["orders"]["order_id"])
    bad = ~tables["order_lines"]["order_id"].isin(valid)
    assert not bad.any()


def test_ac_02_dq02_order_lines_product_fk(tables: dict) -> None:
    """DQ-02: order_lines.product_id references products."""
    valid = set(tables["products"]["product_id"])
    bad = ~tables["order_lines"]["product_id"].isin(valid)
    assert not bad.any()


def test_ac_02_dq02_order_lines_promo_fk(tables: dict) -> None:
    """DQ-02: order_lines.promo_id (when set) references promotions."""
    df = tables["order_lines"]
    with_promo = df["promo_id"].dropna()
    valid = set(tables["promotions"]["promo_id"])
    bad = ~with_promo.isin(valid)
    assert not bad.any()


def test_ac_02_dq02_expected_demand_product_fk(tables: dict) -> None:
    """DQ-02: expected_demand.product_id references products (spec §6.2)."""
    valid = set(tables["products"]["product_id"])
    bad = set(tables["expected_demand"]["product_id"]) - valid
    assert not bad, f"expected_demand has product_ids not in products: {sorted(bad)[:20]}"


def test_ac_02_dq02_expected_demand_region_fk(tables: dict) -> None:
    """DQ-02: expected_demand.region_id references regions (spec §6.2)."""
    valid = set(tables["regions"]["region_id"])
    bad = set(tables["expected_demand"]["region_id"]) - valid
    assert not bad, f"expected_demand has region_ids not in regions: {sorted(bad)[:20]}"


# ---------------------------------------------------------------------------
# DQ-03: No nulls except nullable columns
# ---------------------------------------------------------------------------

def test_ac_02_dq03_no_unexpected_nulls(tables: dict) -> None:
    """DQ-03: only the columns §4 marks nullable may be null."""
    nullable = {
        "products": {"discontinue_date"},
        "promotions": {"region_id"},
        "order_lines": {"promo_id"},
    }
    errors: list[str] = []
    for tname, df in tables.items():
        if tname == "metadata":
            continue
        allowed_null = nullable.get(tname, set())
        for col in df.columns:
            if col in allowed_null:
                continue
            n_null = df[col].isna().sum()
            if n_null:
                errors.append(f"{tname}.{col}: {n_null} nulls")
    assert not errors, "Unexpected nulls:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# DQ-04: quantity >= 1, unit_price > 0, line_total > 0
# ---------------------------------------------------------------------------

def test_ac_02_dq04_quantity_positive_int(tables: dict) -> None:
    """DQ-04: quantity is an integer >= 1."""
    df = tables["order_lines"]
    assert (df["quantity"] >= 1).all(), "quantity < 1 found"
    assert df["quantity"].dtype in (int, "int64", "int32"), "quantity is not integer type"


def test_ac_02_dq04_unit_price_positive(tables: dict) -> None:
    """DQ-04: unit_price > 0."""
    assert (tables["order_lines"]["unit_price"] > 0).all()


def test_ac_02_dq04_line_total_positive(tables: dict) -> None:
    """DQ-04: line_total > 0."""
    assert (tables["order_lines"]["line_total"] > 0).all()


# ---------------------------------------------------------------------------
# DQ-05: discount_pct in [0.00, 0.35]
# ---------------------------------------------------------------------------

def test_ac_02_dq05_discount_range(tables: dict) -> None:
    """DQ-05: discount_pct between 0.00 and 0.35 inclusive."""
    df = tables["order_lines"]
    assert (df["discount_pct"] >= 0.00).all(), "discount_pct < 0 found"
    assert (df["discount_pct"] <= 0.35).all(), "discount_pct > 0.35 found"


# ---------------------------------------------------------------------------
# DQ-06: line_total = round_half_up(quantity * unit_price * (1 - discount_pct), 2)
# ---------------------------------------------------------------------------

def test_ac_02_dq06_line_total_formula(tables: dict) -> None:
    """DQ-06: line_total matches the specified formula to the cent.

    Exact integer math instead of floats: prices in cents and discounts in hundredths, so
    quantity * cents * (100 - hundredths) is the total in 1/10,000 dollars. All terms are
    positive, so adding 50 before integer division by 100 rounds half-up to the cent.
    """
    df = tables["order_lines"]
    money_cols = ("unit_price", "discount_pct", "line_total")
    scaled = {c: df[c].astype(float).to_numpy() * 100 for c in money_cols}
    off_grid = [c for c, v in scaled.items() if (np.abs(v - np.round(v)) > 1e-6).any()]
    assert not off_grid, f"Columns with more than 2 decimals, formula undefined: {off_grid}"
    cents, hundredths, actual = (np.round(scaled[c]).astype(np.int64) for c in money_cols)

    qty = df["quantity"].to_numpy(dtype=np.int64)
    expected = (qty * cents * (100 - hundredths) + 50) // 100
    bad = expected != actual
    report = df.loc[bad, ["order_id", "line_no", "quantity", *money_cols]].assign(
        expected=expected[bad] / 100
    )
    assert not bad.any(), (
        f"line_total formula violations ({bad.sum()} rows), first 20:\n"
        + report.head(20).to_string(index=False)
    )


# ---------------------------------------------------------------------------
# DQ-07: order_date within --start and --end
# ---------------------------------------------------------------------------

def test_ac_02_dq07_order_date_within_range(tables: dict) -> None:
    """DQ-07: every order_date is within 2023-01-01 to 2025-12-31."""
    df = tables["orders"]
    dates = pd.to_datetime(df["order_date"])
    assert (dates >= "2023-01-01").all(), "order_date before start found"
    assert (dates <= "2025-12-31").all(), "order_date after end found"


# ---------------------------------------------------------------------------
# DQ-08: no order before customer's signup_date
# ---------------------------------------------------------------------------

def test_ac_02_dq08_no_order_before_signup(tables: dict) -> None:
    """DQ-08: order_date >= customer signup_date for every order."""
    orders = tables["orders"]
    customers = tables["customers"][["customer_id", "signup_date"]]
    merged = orders.merge(customers, on="customer_id", how="left")
    bad = pd.to_datetime(merged["order_date"]) < pd.to_datetime(merged["signup_date"])
    assert not bad.any(), f"{bad.sum()} orders placed before customer signup"


# ---------------------------------------------------------------------------
# DQ-09: no line outside product's active period
# ---------------------------------------------------------------------------

def test_ac_02_dq09_no_line_outside_active_period(tables: dict) -> None:
    """DQ-09: no order_line for a product before launch or on/after discontinue."""
    order_lines = tables["order_lines"]
    orders = tables["orders"][["order_id", "order_date"]]
    products = tables["products"][["product_id", "launch_date", "discontinue_date"]]

    merged = (
        order_lines[["order_id", "product_id"]]
        .merge(orders, on="order_id", how="left")
        .merge(products, on="product_id", how="left")
    )
    merged["order_date"] = pd.to_datetime(merged["order_date"])
    merged["launch_date"] = pd.to_datetime(merged["launch_date"])
    merged["discontinue_date"] = pd.to_datetime(merged["discontinue_date"])

    too_early = merged["order_date"] < merged["launch_date"]
    assert not too_early.any(), f"{too_early.sum()} lines before product launch"

    has_disc = merged["discontinue_date"].notna()
    too_late = has_disc & (merged["order_date"] >= merged["discontinue_date"])
    assert not too_late.any(), f"{too_late.sum()} lines on/after product discontinuation"


# ---------------------------------------------------------------------------
# DQ-10: promo_id and discount_pct consistency
# ---------------------------------------------------------------------------

def test_ac_02_dq10_promo_id_and_discount_consistency(tables: dict) -> None:
    """DQ-10: promo_id set iff a promo is active; discount_pct matches promo + Enterprise flag."""
    # One row per (product, region, day) a promo covers; all-region promos cover every region.
    all_regions = list(tables["regions"]["region_id"])
    promo_days = pd.DataFrame(
        [
            (p.product_id, r, d, p.promo_id, float(p.discount_pct))
            for p in tables["promotions"].itertuples()
            for r in (all_regions if pd.isna(p.region_id) else [p.region_id])
            for d in pd.date_range(p.start_date, p.end_date)
        ],
        columns=["product_id", "region_id", "order_date", "active_promo_id", "promo_disc"],
    )
    key = ["product_id", "region_id", "order_date"]
    overlap = promo_days[promo_days.duplicated(key, keep=False)]
    assert overlap.empty, f"More than one promo covers a product/region/day:\n{overlap.head(20)}"

    orders = tables["orders"][["order_id", "order_date", "customer_id", "region_id"]].copy()
    orders["order_date"] = as_ns_dates(orders["order_date"])
    merged = (
        tables["order_lines"]
        .merge(orders, on="order_id", how="left")
        .merge(tables["customers"][["customer_id", "segment"]], on="customer_id", how="left")
        .merge(promo_days, on=key, how="left")
    )

    enterprise_extra = np.where(merged["segment"] == "Enterprise", 0.05, 0.0)
    expected_disc = np.round(
        np.minimum(merged["promo_disc"].fillna(0.0).to_numpy() + enterprise_extra, 0.35), 2
    )
    promo_ok = (merged["promo_id"].isna() & merged["active_promo_id"].isna()) | (
        merged["promo_id"] == merged["active_promo_id"]
    )
    disc_ok = np.abs(merged["discount_pct"].astype(float).to_numpy() - expected_disc) <= 1e-9
    bad = ~promo_ok.to_numpy() | ~disc_ok
    report = merged.loc[
        bad, ["order_id", "line_no", "segment", "promo_id", "active_promo_id", "discount_pct"]
    ].assign(expected_discount=expected_disc[bad])
    assert not bad.any(), (
        f"DQ-10 violations ({bad.sum()} rows), first 20:\n" + report.head(20).to_string(index=False)
    )


# ---------------------------------------------------------------------------
# DQ-11: orders.region_id matches customer region
# ---------------------------------------------------------------------------

def test_ac_02_dq11_order_region_matches_customer(tables: dict) -> None:
    """DQ-11: orders.region_id always equals the customer's region."""
    orders = tables["orders"]
    customers = tables["customers"][["customer_id", "region_id"]].rename(
        columns={"region_id": "cust_region"}
    )
    merged = orders.merge(customers, on="customer_id", how="left")
    bad = merged["region_id"] != merged["cust_region"]
    assert not bad.any(), f"{bad.sum()} orders have region mismatch"


# ---------------------------------------------------------------------------
# DQ-12: every order has at least one line
# ---------------------------------------------------------------------------

def test_ac_02_dq12_every_order_has_a_line(tables: dict) -> None:
    """DQ-12: every order_id in orders appears in order_lines."""
    order_ids = set(tables["orders"]["order_id"])
    line_order_ids = set(tables["order_lines"]["order_id"])
    missing = order_ids - line_order_ids
    assert not missing, f"{len(missing)} orders have no lines"


# ---------------------------------------------------------------------------
# DQ-13: money values have at most 2 decimal places
# ---------------------------------------------------------------------------

def test_ac_02_dq13_money_has_two_decimals(tables: dict) -> None:
    """DQ-13: list_price, unit_price, line_total, discount_pct have at most 2 decimals."""
    errors: list[str] = []

    def check_col(df: pd.DataFrame, table: str, col: str) -> None:
        vals = df[col].dropna()
        bad = vals.apply(lambda v: round(v, 2) != v)
        if bad.any():
            errors.append(f"{table}.{col}: {bad.sum()} values with more than 2 decimal places")

    check_col(tables["products"], "products", "list_price")
    check_col(tables["order_lines"], "order_lines", "unit_price")
    check_col(tables["order_lines"], "order_lines", "line_total")
    check_col(tables["order_lines"], "order_lines", "discount_pct")
    assert not errors, "\n".join(errors)
