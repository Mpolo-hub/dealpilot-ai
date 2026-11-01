"""
AC-16 — Patterns in metadata.

Spec §8, AC-16:
  "metadata.json holds the seed, date range, row counts and every parameter
   from section 5."

Checks actual values, not just presence:
  - seed, start, end match the run; generator_version is set.
  - row_counts match the real table sizes.
  - every fixed §5 parameter equals the spec value (conftest.SPEC_PARAMS).
  - the drawn per-product base demand obeys §5.2.

Field names, fixed values and drawn-value rules follow spec 001 §3.1.
"""
from __future__ import annotations

import math

import pandas as pd

from conftest import (
    DEFAULT_END,
    DEFAULT_SEED,
    DEFAULT_START,
    REGION_SIZE_WEIGHTS,
    SPEC_PARAMS,
    TABLE_NAMES,
)


def _same(actual, expected) -> bool:
    """Deep equality, with a float tolerance for numbers."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_same(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(map(_same, actual, expected))
        )
    if isinstance(expected, (int, float)):
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
        )
    return actual == expected


def test_ac_16_run_settings(tables: dict) -> None:
    """AC-16: seed, date range and generator version are recorded."""
    meta = tables["metadata"]
    seed = meta.get("seed")
    assert type(seed) is int and seed == DEFAULT_SEED, f"seed={seed!r}"
    assert meta.get("start") == DEFAULT_START, f"start={meta.get('start')!r}"
    assert meta.get("end") == DEFAULT_END, f"end={meta.get('end')!r}"
    version = meta.get("generator_version")
    assert isinstance(version, str) and version, f"generator_version={version!r}"


def test_ac_16_row_counts_match_tables(tables: dict) -> None:
    """AC-16: row_counts holds the real row count of every output table."""
    actual = {name: len(tables[name]) for name in TABLE_NAMES}
    recorded = tables["metadata"].get("row_counts")
    assert recorded == actual, f"row_counts={recorded!r}, tables have {actual}"


def test_ac_16_fixed_parameters_match_spec(tables: dict) -> None:
    """AC-16: every fixed §5 parameter in metadata equals the spec value."""
    params = tables["metadata"].get("parameters", {})
    wrong = {
        key: params.get(key, "<missing>")
        for key, expected in SPEC_PARAMS.items()
        if not _same(params.get(key), expected)
    }
    assert not wrong, "metadata.json parameters differ from spec §5:\n" + "\n".join(
        f"  {k}: got {v!r}, expected {SPEC_PARAMS[k]!r}" for k, v in wrong.items()
    )


def test_ac_16_base_demand_follows_section_5_2(tables: dict) -> None:
    """AC-16 / §5.2: the drawn base(p) values hit 250 units, 20% per category, max 6%."""
    base = tables["metadata"].get("parameters", {}).get("base_demand")
    products = tables["products"].copy()
    assert isinstance(base, dict), "parameters.base_demand missing or not an object"
    assert set(base) == set(products["product_id"]), "base_demand must cover exactly all products"
    not_numbers = {
        k: v for k, v in base.items()
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
    }
    assert not not_numbers, f"base_demand values must be finite numbers: {not_numbers}"

    start = pd.Timestamp(DEFAULT_START)
    products["launch_date"] = pd.to_datetime(products["launch_date"])
    products["discontinue_date"] = pd.to_datetime(products["discontinue_date"])
    active_at_start = (products["launch_date"] <= start) & (
        products["discontinue_date"].isna() | (start < products["discontinue_date"])
    )
    # sum over all regions of base(p) * size_weight(r)
    products["units"] = products["product_id"].map(base) * sum(REGION_SIZE_WEIGHTS.values())

    total = SPEC_PARAMS["base_total_units"]
    assert (products["units"] > 0).all(), "every product needs a base above 0"
    assert math.isclose(products.loc[active_at_start, "units"].sum(), total, rel_tol=1e-9)
    by_cat = products[active_at_start].groupby("category")["units"].sum()
    share = SPEC_PARAMS["base_category_share"]
    bad_cats = {c: u for c, u in by_cat.items() if not math.isclose(u, total * share, rel_tol=1e-9)}
    assert not bad_cats, f"categories not at {share:.0%} of {total}: {bad_cats}"
    cap = SPEC_PARAMS["base_max_share"] * total
    too_big = products.loc[products["units"] > cap + 1e-9, ["product_id", "units"]]
    assert too_big.empty, f"products above {cap} units/day:\n{too_big.to_string(index=False)}"
