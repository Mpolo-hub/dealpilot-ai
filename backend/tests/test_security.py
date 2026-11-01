"""
Security regression tests. No acceptance-criterion IDs: these pin down security
properties the specs already require, so a later change can't silently undo them.

- spec 002 3.5 / 7: SQL only from fixed fragments + bound values; generic 500 body on /v1
- spec 002 2: local, read-only API; no CORS (no cross-origin reads from browsers)
- AGENTS.md rules: no secrets, no generated data in git; generator source stays visible
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dealpilot.analytics import dataset
from dealpilot.api import v1
from dealpilot.api.main import app

ROOT = dataset.find_project_root()


@pytest.fixture
def client(generated_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    return TestClient(app)


def _hashes(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


def _git(*args: str) -> str:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git is required for repository security checks")
    result = subprocess.run([git, "-C", str(ROOT), *args], capture_output=True, text=True,
                            check=False)
    return result.stdout


# --------------------------------------------------------------------------- API

@pytest.mark.parametrize(("query", "code"), [
    ("product_id=P001' OR '1'='1", "invalid_filter"),
    ("category=Home; DROP TABLE orders", "invalid_filter"),
    ("region_id=R01')--", "invalid_filter"),
    ("product_id=../../secrets", "invalid_filter"),
    ("group_by=date; DROP TABLE orders", "unsupported_dimension"),
    ("group_by=region_id", "unsupported_dimension"),  # a column name is not a dimension
    ("group_by=date&interval=day'--", "invalid_parameter"),
    ("start=2023-01-01' OR 1=1--", "invalid_date"),
])
def test_security_injection_payloads_are_rejected(client: TestClient, generated_dir: Path,
                                                  query: str, code: str) -> None:
    """SQL-like and path-like inputs never reach SQL as text and never change data."""
    before = _hashes(generated_dir)
    r = client.get("/v1/sales/metrics", params=[tuple(p.split("=", 1)) for p in query.split("&")])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code
    assert _hashes(generated_dir) == before


def test_security_unexpected_error_is_generic(generated_dir: Path, monkeypatch) -> None:
    """A crash inside /v1 returns the generic internal_error body: no message, no path."""
    planted = r"internal detail at C:\Users\someone\private\file.parquet"

    def boom(*args, **kwargs):
        raise RuntimeError(planted)

    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    monkeypatch.setattr(v1, "sales_metrics", boom)
    r = TestClient(app, raise_server_exceptions=False).get("/v1/sales/metrics")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error",
                                  "message": "An unexpected error occurred.", "details": []}}
    for leaked in ("internal detail", "someone", "private", "RuntimeError", "Traceback"):
        assert leaked not in r.text


def test_security_no_cors(client: TestClient) -> None:
    """No CORS headers: a web page on another origin can't read API responses."""
    r = client.get("/v1/metadata", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers
    r = client.options("/v1/metadata", headers={"Origin": "https://attacker.example",
                                                "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_security_repeated_values_are_bounded(client: TestClient) -> None:
    """2,000 copies of one filter value cost one value, not 2,000 SQL parameters."""
    r = client.get("/v1/sales/metrics",
                   params=[("product_id", "P001")] * 2000 + [("group_by", "product")])
    assert r.status_code == 200
    assert r.json()["filters"]["product_id"] == ["P001"]
    assert r.json()["row_count"] == 1


# --------------------------------------------------------------------------- repository

@pytest.mark.parametrize(("path", "ignored"), [
    ("data/raw/orders.parquet", True),
    ("data/raw/metadata.json", True),
    ("backend/data/raw/orders.parquet", True),  # generator run from backend/
    (".env", True),
    (".env.local", True),
    ("backend/.venv/pyvenv.cfg", True),
    ("server.key", True),
    ("cert.p12", True),
    ("cert.pfx", True),
    ("release.keystore", True),
    ("credentials.json", True),
    ("backend/config/credentials-prod.json", True),
    ("service-account.json", True),
    ("deploy/gcp/service-account-prod.json", True),
    (".env.example", False),
    ("backend/src/dealpilot/data/generate.py", False),  # once hidden by the data/ rule
    ("backend/src/dealpilot/data/__init__.py", False),
])
def test_security_gitignore_rules(path: str, ignored: bool) -> None:
    """Generated data, secrets and venvs stay out of git; generator source stays in."""
    matched = _git("check-ignore", "--no-index", path).strip()
    assert bool(matched) == ignored, f"{path}: ignored={bool(matched)}, expected {ignored}"


SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),
    "API key assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
}


def test_security_no_secrets_in_repository_files() -> None:
    """No credential-shaped strings in any file git can see (tracked or untracked)."""
    files = [f for f in _git("ls-files", "--cached", "--others", "--exclude-standard",
                             "-z").split("\0") if f]
    assert files, "git listed no files"
    found = []
    for name in files:
        data = (ROOT / name).read_bytes()
        if b"\0" in data[:4096]:  # binary (the design PNGs)
            continue
        text = data.decode("utf-8", errors="replace")
        found += [f"{name}: {label}" for label, pattern in SECRET_PATTERNS.items()
                  if pattern.search(text)]
    assert not found, found
