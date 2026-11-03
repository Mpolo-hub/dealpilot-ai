"""Public demo configuration (spec 014 JA-FR-02), read only from the process environment.

Fail closed: any missing or invalid value raises DemoConfigError, and the app refuses to
start in public mode.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dealpilot.analytics.dataset import ENV_VAR as DATA_DIR_VAR
from dealpilot.analytics.dataset import find_project_root, resolve_data_dir

MODE_VAR = "DEALPILOT_DEMO_MODE"
STORE_VAR = "DEALPILOT_DEMO_STORE"
END_VAR = "DEALPILOT_DEMO_END"
KEY_VAR = "DEALPILOT_DEMO_HASH_KEY"
ORIGIN_VAR = "DEALPILOT_DEMO_ORIGIN"
STATIC_VAR = "DEALPILOT_DEMO_STATIC_DIR"
CLIENT_IP_VAR = "DEALPILOT_DEMO_CLIENT_IP_HEADER"
XFF_HOPS_VAR = "DEALPILOT_DEMO_XFF_HOPS"
EPHEMERAL_VAR = "DEALPILOT_DEMO_EPHEMERAL_STORE"
INVITES_VAR = "DEALPILOT_DEMO_INVITES"

DEFAULT_CLIENT_IP_HEADER = "Fly-Client-IP"
FORWARDED_FOR = "x-forwarded-for"
MIN_KEY_BYTES = 32
MIN_CODE_CHARS = 32
CODE = re.compile(r"^[A-Za-z0-9_-]+$")
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
INVITATION_LIFE_SECONDS = 7 * 24 * 3600    # P-1
IDLE_SECONDS = 60 * 60                      # P-2
ABSOLUTE_SECONDS = 8 * 3600                 # P-3


class DemoConfigError(Exception):
    """The public demo configuration is missing or invalid (never contains secret values)."""


@dataclass(frozen=True)
class Invite:
    """One bootstrap invitation from DEALPILOT_DEMO_INVITES. The code is never printed."""
    label: str
    code: str = field(repr=False)
    not_after: int


@dataclass(frozen=True)
class DemoConfig:
    store: Path
    end: int            # demo_end as UTC epoch seconds (P-8)
    hash_key: bytes = field(repr=False)
    origin: str
    static_dir: Path
    client_ip_header: str = DEFAULT_CLIENT_IP_HEADER.lower()
    xff_hops: int = 1
    ephemeral: bool = False
    invites: tuple[Invite, ...] | None = field(default=None, repr=False)


def public_mode(env: Mapping[str, str] = os.environ) -> bool:
    return env.get(MODE_VAR, "") == "public"


def parse_invites(raw: str, end: int) -> tuple[Invite, ...]:
    """`label|code|issued` entries separated by `;` or new lines.

    `issued` is an ISO 8601 time with offset. The invitation is valid until issued + 7 days
    (P-1), never past the demo end (P-8). Errors never include a code.
    """
    invites: list[Invite] = []
    for n, entry in enumerate(e.strip() for e in raw.replace("\n", ";").split(";")):
        if not entry:
            continue
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) != 3:
            raise DemoConfigError(f"{INVITES_VAR} entry {n + 1}: expected label|code|issued")
        label, code, issued = parts
        if not LABEL.fullmatch(label):
            raise DemoConfigError(f"{INVITES_VAR} entry {n + 1}: invalid label")
        if len(code) < MIN_CODE_CHARS or not CODE.fullmatch(code):
            raise DemoConfigError(f"{INVITES_VAR} entry {n + 1} ({label}): the code must be "
                                  f"at least {MIN_CODE_CHARS} URL-safe characters")
        try:
            start = parse_deadline(issued)
        except DemoConfigError:
            raise DemoConfigError(f"{INVITES_VAR} entry {n + 1} ({label}): issued must be "
                                  "an ISO 8601 time with offset") from None
        invites.append(Invite(label, code, min(start + INVITATION_LIFE_SECONDS, end)))
    if len({i.label for i in invites}) != len(invites):
        raise DemoConfigError(f"{INVITES_VAR}: duplicate label")
    if len({i.code for i in invites}) != len(invites):
        raise DemoConfigError(f"{INVITES_VAR}: duplicate code")
    return tuple(invites)


def parse_deadline(raw: str) -> int:
    """ISO 8601 time with an explicit offset, for example 2026-12-04T23:59:59+01:00."""
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise DemoConfigError(f"{END_VAR} is not an ISO 8601 time") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise DemoConfigError(f"{END_VAR} must include a UTC offset")
    return int(value.timestamp())


def load_config(env: Mapping[str, str] = os.environ) -> DemoConfig:
    missing = [name for name in (STORE_VAR, END_VAR, KEY_VAR, ORIGIN_VAR) if not env.get(name)]
    if missing:
        raise DemoConfigError(f"missing: {', '.join(missing)}")
    key = env[KEY_VAR].encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise DemoConfigError(f"{KEY_VAR} must be at least {MIN_KEY_BYTES} bytes")
    origin = env[ORIGIN_VAR].rstrip("/")
    if not origin.startswith("https://") and not origin.startswith("http://127.0.0.1"):
        raise DemoConfigError(f"{ORIGIN_VAR} must be an https origin")
    root = find_project_root()
    store = Path(env[STORE_VAR])
    if not store.is_absolute():
        raise DemoConfigError(f"{STORE_VAR} must be an absolute path")
    data_dir = resolve_data_dir(env.get(DATA_DIR_VAR) or None, root).resolve()
    resolved = store.resolve()
    if resolved == data_dir or data_dir in resolved.parents:
        raise DemoConfigError(f"{STORE_VAR} must be outside the data folder")
    static = Path(env.get(STATIC_VAR) or (root / "frontend" / "dist" if root else "frontend/dist"))
    if not (static / "index.html").is_file():
        raise DemoConfigError(f"{STATIC_VAR}: index.html not found")
    end = parse_deadline(env[END_VAR])
    header = (env.get(CLIENT_IP_VAR) or DEFAULT_CLIENT_IP_HEADER).strip().lower()
    if not re.fullmatch(r"[a-z0-9-]+", header):
        raise DemoConfigError(f"{CLIENT_IP_VAR} must be a header name")
    hops_raw = env.get(XFF_HOPS_VAR) or "1"
    if not hops_raw.isdigit() or not 1 <= int(hops_raw) <= 5:
        raise DemoConfigError(f"{XFF_HOPS_VAR} must be 1 to 5")
    ephemeral = env.get(EPHEMERAL_VAR, "") == "1"
    invites = parse_invites(env[INVITES_VAR], end) if env.get(INVITES_VAR) else None
    return DemoConfig(store=store, end=end, hash_key=key, origin=origin, static_dir=static,
                      client_ip_header=header, xff_hops=int(hops_raw), ephemeral=ephemeral,
                      invites=invites)
