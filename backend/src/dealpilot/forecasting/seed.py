"""Decision seed (spec 003 section 5.4, D22).

Values are validated, never normalized: a field that breaks its pattern refuses the run.
No real decision seed is chosen under spec 003; this only derives and checks one.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from dealpilot.forecasting.split import ForecastingError

PREFIX = "dealpilot-decision-seed/v1"
# 42, 7 and 1 to 10. Future exclusions are added with a date and a reason; none removed.
BASE_EXCLUDED = frozenset({42, 7, *range(1, 11)})
MAX_N = 10_000
_PATTERNS = {
    "spec": re.compile(r"[0-9]{3}"),
    "name": re.compile(r"[a-z][a-z0-9_]*"),
    "version": re.compile(r"[0-9]+(\.[0-9]+)*"),
    "config": re.compile(r"[0-9a-f]{64}"),
    "decision": re.compile(r"[1-9][0-9]*"),
    "n": re.compile(r"[1-9][0-9]*"),
}


@dataclass(frozen=True)
class SeedInputs:
    spec: str
    name: str
    version: str
    config_sha256: str  # candidate_config_sha256
    decision: str
    n: str = "1"


def _check(inputs: SeedInputs) -> None:
    values = {"spec": inputs.spec, "name": inputs.name, "version": inputs.version,
              "config": inputs.config_sha256, "decision": inputs.decision, "n": inputs.n}
    for field, value in values.items():
        if not isinstance(value, str) or not value.isascii() \
                or not _PATTERNS[field].fullmatch(value):
            raise ForecastingError(f"decision seed field {field} breaks its pattern")


def derivation_text(inputs: SeedInputs) -> str:
    _check(inputs)
    return (f"{PREFIX}|spec={inputs.spec}|candidate={inputs.name}@{inputs.version}"
            f"|config={inputs.config_sha256}|decision={inputs.decision}|n={inputs.n}")


def seed_from_text(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big") \
        & 0x7FFFFFFF


@dataclass(frozen=True)
class DerivedSeed:
    inputs: SeedInputs  # with the final n
    seed: int


def derive_seed(inputs: SeedInputs, excluded: frozenset[int] = frozenset()) -> DerivedSeed:
    """Derive the seed; an excluded seed raises `n` by 1, and nothing else changes `n`."""
    blocked = BASE_EXCLUDED | excluded
    current = inputs
    for _ in range(MAX_N):
        seed = seed_from_text(derivation_text(current))
        if seed not in blocked:
            return DerivedSeed(current, seed)
        current = SeedInputs(current.spec, current.name, current.version,
                             current.config_sha256, current.decision, str(int(current.n) + 1))
    raise ForecastingError("no usable decision seed found")


def check_recorded_seed(inputs: SeedInputs, metadata_seed, excluded: frozenset[int] = frozenset()
                        ) -> dict:
    """Derive again from the recorded inputs (with their final `n`) and compare.

    The recorded `n` must already be final: an excluded seed at that `n` refuses the run.
    Returns the `run.json` `decision_seed` record; raises when the run must be refused.
    """
    seed = seed_from_text(derivation_text(inputs))
    if seed in BASE_EXCLUDED | excluded:
        raise ForecastingError("the recorded decision seed is excluded")
    matches = isinstance(metadata_seed, int) and not isinstance(metadata_seed, bool) \
        and metadata_seed == seed
    record = {"spec": inputs.spec, "candidate_name": inputs.name,
              "candidate_version": inputs.version,
              "candidate_config_sha256": inputs.config_sha256,
              "decision": inputs.decision, "n": inputs.n, "derived_seed": seed,
              "metadata_seed": metadata_seed, "match": matches}
    if not matches:
        raise ForecastingError("metadata.json seed differs from the derived decision seed")
    return record
