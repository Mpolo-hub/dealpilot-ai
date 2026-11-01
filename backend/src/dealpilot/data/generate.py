"""Synthetic sales data generator (spec 001).

    python -m dealpilot.data.generate --seed 42 --start 2023-01-01 --end 2025-12-31 --out data/raw

All randomness comes from one numpy Generator seeded with --seed, drawn in a fixed order,
so the same arguments always give the same files. Money is handled as integer cents and
discounts as integer hundredths, so every rounding is exact.
"""
from __future__ import annotations

import argparse
import json
import numbers
import platform
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dealpilot import __version__

# --- Fixed inputs from the spec ---------------------------------------------------------

MIN_DAYS, MAX_DAYS = 730, 1096  # §3, both end dates counted

REGIONS = [  # §4: (region_id, name, size_weight)
    ("R01", "North", 0.28),
    ("R02", "South", 0.22),
    ("R03", "East", 0.20),
    ("R04", "West", 0.16),
    ("R05", "Central", 0.14),
]
CATEGORIES = ["Electronics", "Home", "Office", "Outdoor", "Apparel"]
PRODUCTS_PER_CATEGORY = 10
N_LATE_LAUNCH, N_DISCONTINUED = 5, 3
MAX_LIFECYCLE_PER_CATEGORY = 2
LIST_PRICE_CENTS = (500, 150_000)  # 5.00 to 1500.00
N_CUSTOMERS = 2000
SEGMENTS = [("Consumer", 0.70), ("SMB", 0.25), ("Enterprise", 0.05)]
SIGNUP_BEFORE_START_SHARE = 0.60
SIGNUP_LOOKBACK_DAYS = 3 * 365  # "up to 3 years before"
N_PROMOS = 40
PROMO_DAYS = (3, 14)
PROMO_DISCOUNTS = [10, 15, 20, 25, 30]  # hundredths
ENTERPRISE_EXTRA, MAX_DISCOUNT = 5, 35  # hundredths
ONLINE_SHARE = 0.60
LINE_EXTRA_POISSON = 0.5  # §5.10: quantity = min(units left, 1 + Poisson(0.5))
MAX_ORDER_LINES = 5
PLACEMENT_ATTEMPTS = 20_000  # per promo; generous, then fail loudly (§5.6)
BASE_REDRAWS = 1_000

# §5 parameters, written to metadata.json "parameters" exactly as listed in spec §3.1.
PARAMS = {
    "base_total_units": 250,
    "base_category_share": 0.20,
    "base_lognormal_sigma": 0.5,
    "base_max_share": 0.06,
    "trend_rates": {
        "Electronics": 0.15, "Home": 0.08, "Office": 0.06, "Outdoor": 0.10, "Apparel": 0.00,
    },
    "trend_days_per_year": 365.25,
    "weekly_multipliers": [0.85, 0.90, 0.95, 1.00, 1.10, 1.25, 0.95],
    "yearly_anchor_day": 15,
    "yearly_anchors": {
        "standard": [0.90, 0.80, 0.88, 0.95, 1.00, 0.98, 0.95, 1.00, 0.98, 1.03, 1.13, 1.20],
        "outdoor": [0.80, 0.85, 0.95, 1.05, 1.15, 1.25, 1.25, 1.15, 1.05, 0.95, 0.85, 0.80],
    },
    "yearly_curve_by_category": {
        "Electronics": "standard", "Home": "standard", "Office": "standard",
        "Outdoor": "outdoor", "Apparel": "standard",
    },
    "promo_lift_base": 1.15,
    "promo_lift_per_discount": 1.5,
    "promo_dip_factor": 0.90,
    "promo_pre_window_days": 14,
    "promo_post_window_days": 7,
    "promo_max_concurrent": 3,
    "promo_min_pre_window_units": 14,
    "closed_days": ["12-25", "01-01"],
    "noise_nb_size": 2,
    "price_increase_min": 0.02,
    "price_increase_max": 0.04,
}

ADJECTIVES = ["Nova", "Apex", "Terra", "Luma", "Vivo", "Orbit", "Pique", "Halo", "Zest", "Brio"]
NOUNS = {
    "Electronics": "Speaker", "Home": "Lamp", "Office": "Organizer",
    "Outdoor": "Tent", "Apparel": "Jacket",
}


class GenerationError(RuntimeError):
    """The spec's rules can't be met (e.g. promos can't be placed). Never silently degraded."""


# --- CLI ---------------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m dealpilot.data.generate", description="Generate synthetic sales data."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    args = parser.parse_args(argv)
    if args.end <= args.start:
        parser.error(f"--end ({args.end}) must be after --start ({args.start})")
    n_days = (args.end - args.start).days + 1
    if not MIN_DAYS <= n_days <= MAX_DAYS:
        parser.error(
            f"date range is {n_days} days; it must be {MIN_DAYS} to {MAX_DAYS} days "
            f"counting both --start and --end. Nothing was written."
        )
    return args


# --- Calendar and demand factors (§5.3-5.5, §5.7) ---------------------------------------

def make_calendar(start: date, end: date) -> dict:
    days = np.arange(np.datetime64(start, "D"), np.datetime64(end, "D") + np.timedelta64(1, "D"))
    months = days.astype("datetime64[M]")
    month = months.astype(int) % 12 + 1
    day_of_month = (days - months.astype("datetime64[D]")).astype(int) + 1
    closed = {tuple(int(x) for x in md.split("-")) for md in PARAMS["closed_days"]}
    is_open = ~np.array([(m, d) in closed for m, d in zip(month, day_of_month)])
    year = days.astype("datetime64[Y]").astype(int) + 1970
    return {
        "days": days,
        "open": is_open,
        "weekday": (days.astype(int) + 3) % 7,  # 1970-01-01 was a Thursday; Mon = 0
        "year_index": year - year[0],
        "n_years": int(year[-1] - year[0] + 1),
        "since_start": np.arange(len(days)),
    }


def yearly_factor(days: np.ndarray, curve: str) -> np.ndarray:
    """§5.5: straight line between monthly anchors on the 15th, in real calendar days."""
    first = int(days[0].astype("datetime64[Y]").astype(int)) + 1970
    last = int(days[-1].astype("datetime64[Y]").astype(int)) + 1970
    years = range(first - 1, last + 2)
    anchor_day = PARAMS["yearly_anchor_day"]
    anchors = np.array(
        [f"{y}-{m:02d}-{anchor_day:02d}" for y in years for m in range(1, 13)], "datetime64[D]"
    )
    values = np.tile(PARAMS["yearly_anchors"][curve], len(years))
    return np.interp(days.astype(float), anchors.astype(float), values)


# --- Products and base demand (§4, §5.2, §5.8) -------------------------------------------

def make_products(rng: np.random.Generator, n_days: int, n_years: int) -> dict:
    n = len(CATEGORIES) * PRODUCTS_PER_CATEGORY
    category = np.repeat(np.arange(len(CATEGORIES)), PRODUCTS_PER_CATEGORY)

    # Lifecycle: 8 products, at most 2 per category, split into 5 late launches + 3 discontinued.
    n_lifecycle = N_LATE_LAUNCH + N_DISCONTINUED
    per_cat = [MAX_LIFECYCLE_PER_CATEGORY] * (n_lifecycle - len(CATEGORIES)) + [1] * (
        2 * len(CATEGORIES) - n_lifecycle
    )
    per_cat = rng.permutation(per_cat)
    lifecycle = np.concatenate([
        rng.choice(np.flatnonzero(category == c), size=k, replace=False)
        for c, k in enumerate(per_cat)
    ])
    lifecycle = rng.permutation(lifecycle)
    late, discontinued = lifecycle[:N_LATE_LAUNCH], lifecycle[N_LATE_LAUNCH:]

    launch = np.zeros(n, int)  # day index
    launch[late] = rng.integers(90, n_days - 1 - 180 + 1, size=len(late))
    stop = np.full(n, n_days)  # first day no longer sold; n_days = never inside range
    stop[discontinued] = rng.integers(180, n_days - 1 - 90 + 1, size=len(discontinued))

    base = draw_base_demand(rng, category, launch)

    # §5.8: price at --start, then +2% to +4% each January 1 after the first year.
    lo, hi = LIST_PRICE_CENTS
    cents = np.round(np.exp(rng.uniform(np.log(lo), np.log(hi), size=n))).astype(np.int64)
    prices = np.empty((n, n_years), np.int64)
    prices[:, 0] = np.clip(cents, lo, hi)
    for y in range(1, n_years):
        bps = rng.integers(200, 401, size=n)  # 2.00% to 4.00% in basis points
        prices[:, y] = (prices[:, y - 1] * (10_000 + bps) + 5_000) // 10_000  # half-up

    return {
        "ids": [f"P{i + 1:03d}" for i in range(n)],
        "names": [
            f"{ADJECTIVES[i % PRODUCTS_PER_CATEGORY]} {NOUNS[CATEGORIES[category[i]]]}"
            for i in range(n)
        ],
        "category": category,
        "launch": launch,
        "stop": stop,
        "base": base,
        "prices": prices,
    }


def draw_base_demand(rng: np.random.Generator, category: np.ndarray, launch: np.ndarray) -> np.ndarray:
    """§5.2: each category's products active on --start share 20% of 250 units/day."""
    total = PARAMS["base_total_units"]
    share = total * PARAMS["base_category_share"]
    cap = total * PARAMS["base_max_share"]
    base = np.zeros(len(category))
    for c in range(len(CATEGORIES)):
        members = np.flatnonzero(category == c)
        at_start = launch[members] == 0
        for _ in range(BASE_REDRAWS):
            z = rng.lognormal(0.0, PARAMS["base_lognormal_sigma"], size=len(members))
            # Late launches use the same scale as their category, on top of the 250.
            candidate = share * z / z[at_start].sum()
            if candidate.max() <= cap:
                base[members] = candidate
                break
        else:
            raise GenerationError(f"no base demand draw for {CATEGORIES[c]} met the 6% cap")
    return base


def unit_factors(cal: dict, prod: dict) -> np.ndarray:
    """f[p, d] = open * active * base * trend * weekly * yearly (no region, no promo)."""
    t = cal["since_start"]
    active = (t[None, :] >= prod["launch"][:, None]) & (t[None, :] < prod["stop"][:, None])
    rates = np.array([PARAMS["trend_rates"][CATEGORIES[c]] for c in prod["category"]])
    trend = (1 + rates[:, None]) ** (t[None, :] / PARAMS["trend_days_per_year"])
    weekly = np.asarray(PARAMS["weekly_multipliers"])[cal["weekday"]]
    curves = {
        name: yearly_factor(cal["days"], name) for name in PARAMS["yearly_anchors"]
    }
    yearly = np.stack([
        curves[PARAMS["yearly_curve_by_category"][CATEGORIES[c]]] for c in prod["category"]
    ])
    usable = cal["open"][None, :] & active
    return usable * prod["base"][:, None] * trend * weekly[None, :] * yearly


# --- Promotions (§5.6) ---------------------------------------------------------------------

def place_promotions(rng: np.random.Generator, f: np.ndarray, sw: np.ndarray) -> list[dict]:
    """Place N_PROMOS promos under rules 1-5; raise if any can't be placed."""
    n_p, n_d = f.shape
    n_r = len(sw)
    pre, post = PARAMS["promo_pre_window_days"], PARAMS["promo_post_window_days"]
    usable = f > 0  # open and active (rules 1-2)
    taken = np.zeros((n_p, n_r, n_d), bool)  # rule 3
    running = np.zeros(n_d, int)  # rule 4
    n_all = N_PROMOS // 2  # "about half" all-region
    all_region_flags = rng.permutation([True] * n_all + [False] * (N_PROMOS - n_all))
    placed = []
    for i, all_regions in enumerate(all_region_flags):
        for _ in range(PLACEMENT_ATTEMPTS):
            p = int(rng.integers(n_p))
            regions = np.arange(n_r) if all_regions else np.array([rng.integers(n_r)])
            length = int(rng.integers(PROMO_DAYS[0], PROMO_DAYS[1] + 1))
            first = int(rng.integers(pre, n_d - post - length + 1))
            w0, w1 = first - pre, first + length + post
            if not usable[p, w0:w1].all():
                continue
            if taken[p][np.ix_(regions, np.arange(w0, w1))].any():
                continue
            if (running[first:first + length] >= PARAMS["promo_max_concurrent"]).any():
                continue
            pre_units = sw[regions] * f[p, w0:first].sum()
            if (pre_units < PARAMS["promo_min_pre_window_units"]).any():
                continue
            taken[p][np.ix_(regions, np.arange(w0, w1))] = True
            running[first:first + length] += 1
            placed.append({
                "product": p,
                "region": None if all_regions else int(regions[0]),
                "first": first,
                "last": first + length - 1,
                "discount": int(rng.choice(PROMO_DISCOUNTS)),
            })
            break
        else:
            raise GenerationError(
                f"could only place {i} of {N_PROMOS} promotions under spec §5.6 rules"
            )
    return sorted(
        placed, key=lambda q: (q["first"], q["product"], -1 if q["region"] is None else q["region"])
    )


def promo_arrays(promos: list[dict], n_p: int, n_r: int, n_d: int):
    """Promo factor (lift/dip/1.0) and promo index (-1 for none) per product, region, day."""
    factor = np.ones((n_p, n_r, n_d))
    index = np.full((n_p, n_r, n_d), -1)
    post = PARAMS["promo_post_window_days"]
    for k, q in enumerate(promos):
        regions = slice(None) if q["region"] is None else q["region"]
        days = slice(q["first"], q["last"] + 1)
        lift = PARAMS["promo_lift_base"] + PARAMS["promo_lift_per_discount"] * (q["discount"] / 100)
        after = slice(q["last"] + 1, q["last"] + 1 + post)
        factor[q["product"], regions, days] = lift
        factor[q["product"], regions, after] = PARAMS["promo_dip_factor"]
        index[q["product"], regions, days] = k
    return factor, index


# --- Customers and orders (§4, §5.10) ------------------------------------------------------

def make_customers(rng: np.random.Generator, n_days: int) -> dict:
    weights = np.array([w for *_, w in REGIONS])
    counts = np.round(weights * N_CUSTOMERS).astype(int)
    counts[0] += N_CUSTOMERS - counts.sum()
    region = rng.permutation(np.repeat(np.arange(len(REGIONS)), counts))
    segment = rng.choice(len(SEGMENTS), size=N_CUSTOMERS, p=[s for _, s in SEGMENTS])
    n_before = round(N_CUSTOMERS * SIGNUP_BEFORE_START_SHARE)
    signup = np.concatenate([
        rng.integers(-SIGNUP_LOOKBACK_DAYS, 0, size=n_before),  # day index, before --start
        rng.integers(0, n_days, size=N_CUSTOMERS - n_before),
    ])
    signup = rng.permutation(signup)
    return {"region": region, "segment": segment, "signup": signup}


def make_orders(rng: np.random.Generator, units: np.ndarray, customers: dict) -> dict:
    """Split observed units into lines and orders. Sum of quantity per cell == units."""
    _, n_r, n_d = units.shape
    total = int(units.sum())
    extra = rng.poisson(LINE_EXTRA_POISSON, size=total)  # each line uses >= 1 unit
    sizes = rng.integers(1, MAX_ORDER_LINES + 1, size=total)
    by_region = []
    for r in range(n_r):
        members = np.flatnonzero(customers["region"] == r)
        members = members[np.argsort(customers["signup"][members], kind="stable")]
        by_region.append((members, customers["signup"][members]))

    o_day, o_region, o_customer, o_online = [], [], [], []
    l_order, l_no, l_product, l_qty = [], [], [], []
    k_extra = k_size = 0
    for d in range(n_d):
        for r in range(n_r):
            lines = []
            for p in np.flatnonzero(units[:, r, d]):
                left = int(units[p, r, d])
                while left:
                    q = min(left, 1 + int(extra[k_extra]))
                    k_extra += 1
                    lines.append((int(p), q))
                    left -= q
            if not lines:
                continue
            members, signups = by_region[r]
            n_eligible = int(np.searchsorted(signups, d, side="right"))
            if n_eligible == 0:
                raise GenerationError(f"no signed-up customer in {REGIONS[r][0]} on day {d}")
            first_order = len(o_day)
            in_order: set[int] = set()
            target = 0
            for idx in rng.permutation(len(lines)):
                p, q = lines[idx]
                if len(in_order) == target or p in in_order:
                    in_order, target = set(), int(sizes[k_size])
                    k_size += 1
                    o_day.append(d)
                    o_region.append(r)
                in_order.add(p)
                l_order.append(len(o_day) - 1)
                l_no.append(len(in_order))
                l_product.append(p)
                l_qty.append(q)
            n_new = len(o_day) - first_order
            o_customer.extend(members[rng.integers(0, n_eligible, size=n_new)].tolist())
            o_online.extend((rng.random(n_new) < ONLINE_SHARE).tolist())
    return {
        "day": np.array(o_day), "region": np.array(o_region),
        "customer": np.array(o_customer), "online": np.array(o_online, bool),
        "line_order": np.array(l_order), "line_no": np.array(l_no),
        "product": np.array(l_product), "qty": np.array(l_qty, np.int64),
    }


# --- Output ---------------------------------------------------------------------------------

def _decimal(hundredths: np.ndarray, precision: int) -> pa.Array:
    return pa.array(
        [Decimal(int(v)).scaleb(-2) for v in hundredths], pa.decimal128(precision, 2)
    )


def _dates(days: np.ndarray) -> pa.Array:
    return pa.array(days.astype("datetime64[D]"), pa.date32())


def check_seed(seed: object) -> None:
    """§3 (decision 2026-10-30): 0 or a positive integer; never a bool or a negative."""
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise GenerationError(f"--seed must be an integer, got {type(seed).__name__}")
    if seed < 0:
        raise GenerationError(f"--seed must be 0 or more, got {seed}")


def generate(seed: int, start: date, end: date) -> tuple[dict[str, pa.Table], dict]:
    check_seed(seed)
    rng = np.random.default_rng(seed)
    cal = make_calendar(start, end)
    days, n_d = cal["days"], len(cal["days"])
    sw = np.array([w for *_, w in REGIONS])
    n_r = len(REGIONS)

    prod = make_products(rng, n_d, cal["n_years"])
    n_p = len(prod["ids"])
    f = unit_factors(cal, prod)
    promos = place_promotions(rng, f, sw)
    factor, promo_index = promo_arrays(promos, n_p, n_r, n_d)

    expected = f[:, None, :] * sw[None, :, None] * factor  # §5.1, [p, r, d]
    k = PARAMS["noise_nb_size"]
    units = rng.negative_binomial(k, k / (k + expected))  # mean = expected, size k
    customers = make_customers(rng, n_d)
    orders = make_orders(rng, units, customers)

    # Line prices and discounts (§4): promo discount + 0.05 Enterprise, max 0.35.
    line_day = orders["day"][orders["line_order"]]
    line_region = orders["region"][orders["line_order"]]
    line_promo = promo_index[orders["product"], line_region, line_day]
    promo_disc = np.array([q["discount"] for q in promos])
    enterprise = SEGMENTS.index(("Enterprise", 0.05))
    is_enterprise = customers["segment"][orders["customer"]][orders["line_order"]] == enterprise
    discount = np.minimum(
        np.where(line_promo >= 0, promo_disc[line_promo], 0) + ENTERPRISE_EXTRA * is_enterprise,
        MAX_DISCOUNT,
    )
    unit_cents = prod["prices"][orders["product"], cal["year_index"][line_day]]
    total_cents = (orders["qty"] * unit_cents * (100 - discount) + 50) // 100  # half-up

    region_ids = [r for r, *_ in REGIONS]
    order_ids = [f"O{i + 1:07d}" for i in range(len(orders["day"]))]
    promo_ids = [f"PR{i + 1:03d}" for i in range(len(promos))]
    tables = {
        "regions": pa.table({
            "region_id": region_ids,
            "name": [name for _, name, _ in REGIONS],
            "size_weight": _decimal(np.round(sw * 100), 3),
        }),
        "products": pa.table({
            "product_id": prod["ids"],
            "name": prod["names"],
            "category": [CATEGORIES[c] for c in prod["category"]],
            "list_price": _decimal(prod["prices"][:, 0], 10),
            "launch_date": _dates(days[prod["launch"]]),
            "discontinue_date": pa.array(
                [days[s].item() if s < n_d else None for s in prod["stop"]], pa.date32()
            ),
        }),
        "customers": pa.table({
            "customer_id": [f"C{i + 1:05d}" for i in range(N_CUSTOMERS)],
            "region_id": [region_ids[r] for r in customers["region"]],
            "segment": [SEGMENTS[s][0] for s in customers["segment"]],
            "signup_date": _dates(days[0] + customers["signup"].astype("timedelta64[D]")),
        }),
        "promotions": pa.table({
            "promo_id": promo_ids,
            "product_id": [prod["ids"][q["product"]] for q in promos],
            "region_id": pa.array(
                [None if q["region"] is None else region_ids[q["region"]] for q in promos],
                pa.string(),
            ),
            "start_date": _dates(days[[q["first"] for q in promos]]),
            "end_date": _dates(days[[q["last"] for q in promos]]),
            "discount_pct": _decimal(promo_disc, 4),
        }),
        "orders": pa.table({
            "order_id": order_ids,
            "order_date": _dates(days[orders["day"]]),
            "customer_id": [f"C{c + 1:05d}" for c in orders["customer"]],
            "region_id": [region_ids[r] for r in orders["region"]],
            "channel": np.where(orders["online"], "Online", "Store").tolist(),
        }),
        "order_lines": pa.table({
            "order_id": [order_ids[o] for o in orders["line_order"]],
            "line_no": pa.array(orders["line_no"], pa.int64()),
            "product_id": [prod["ids"][p] for p in orders["product"]],
            "quantity": pa.array(orders["qty"], pa.int64()),
            "unit_price": _decimal(unit_cents, 10),
            "discount_pct": _decimal(discount, 4),
            "line_total": _decimal(total_cents, 12),
            "promo_id": pa.array(
                [promo_ids[i] if i >= 0 else None for i in line_promo], pa.string()
            ),
        }),
        "expected_demand": pa.table({  # §6.2, one row per date, product, region
            "date": _dates(np.repeat(days, n_p * n_r)),
            "product_id": np.tile(np.repeat(prod["ids"], n_r), n_d).tolist(),
            "region_id": np.tile(region_ids, n_d * n_p).tolist(),
            "expected_units": expected.transpose(2, 0, 1).reshape(-1),
        }),
    }
    metadata = {
        "seed": seed,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "generator_version": __version__,
        # Extra field (spec §3.1 allows them): what produced these bytes. numpy's seeded
        # streams and pyarrow's Parquet writer are the version-sensitive parts.
        "library_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pyarrow": pa.__version__,
        },
        "row_counts": {name: table.num_rows for name, table in tables.items()},
        "parameters": {
            **PARAMS,
            "base_demand": {pid: float(b) for pid, b in zip(prod["ids"], prod["base"])},
        },
    }
    return tables, metadata


def write(tables: dict[str, pa.Table], metadata: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        pq.write_table(table, out / f"{name}.parquet")
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        tables, metadata = generate(args.seed, args.start, args.end)
    except GenerationError as exc:
        print(f"error: {exc}. Nothing was written.", file=sys.stderr)
        return 1
    write(tables, metadata, args.out)
    counts = ", ".join(f"{k}={v:,}" for k, v in metadata["row_counts"].items())
    print(f"Wrote {args.out} (seed {args.seed}): {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
