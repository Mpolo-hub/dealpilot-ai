"""Client identity for rate limits (spec 014 P-4 conditions 1, 2, 3 and 6).

The client IP is read only from ONE configured header (DEALPILOT_DEMO_CLIENT_IP_HEADER,
default `Fly-Client-IP`; `CF-Connecting-IP` on Render, which Cloudflare overwrites), or from
a fixed position counted from the right of `X-Forwarded-For`. It is normalized (IPv6 to its
/64) and turned into an HMAC with a host-secret key. The raw IP is never stored or logged.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress

CLIENT_IP_HEADER = "fly-client-ip"


def client_ip(header_values: list[str]) -> str | None:
    """The normalized client address, or None when the header is missing, repeated or bad."""
    if len(header_values) != 1:
        return None
    raw = header_values[0].strip()
    if "," in raw:
        return None
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
    return str(address)


def from_forwarded_for(header_values: list[str], hops: int) -> str | None:
    """The entry `hops` places from the RIGHT of X-Forwarded-For.

    Proxies append to the list, so the leftmost entries are whatever the caller sent and
    can be forged. Only the entries appended by proxies you control can be trusted; `hops`
    says how many such proxies sit in front of the app (1 = trust only the last entry).
    """
    entries = [e.strip() for v in header_values for e in v.split(",") if e.strip()]
    if len(entries) < hops:
        return None
    return client_ip([entries[-hops]])


def resolve(headers, header_name: str, hops: int) -> str | None:
    """Client address from the configured header (lowercase name), or None (403)."""
    values = headers.getlist(header_name)
    if header_name == "x-forwarded-for":
        return from_forwarded_for(values, hops)
    return client_ip(values)


def client_key(key: bytes, normalized_ip: str) -> str:
    return hmac.new(key, normalized_ip.encode("ascii"), hashlib.sha256).hexdigest()
