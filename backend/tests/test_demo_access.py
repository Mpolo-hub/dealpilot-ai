"""
Spec 014 (Hackathon judge access) acceptance criteria AC-S1-*: AUTH, STORE, RL, API, HDR,
DEP, ERR and OPS. Public demo mode only; local mode is covered by the spec 002 suite.

Data: the session seed-42 run from conftest (`generated_dir`). The clock is injected.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dealpilot.analytics import dataset
from dealpilot.api.main import create_app
from dealpilot.demo import admin, store
from dealpilot.demo.clientkey import client_ip, client_key
from dealpilot.demo.config import DemoConfigError

ORIGIN = "https://demo.example.test"
START = 1_790_000_000                      # an arbitrary fixed "now"
END_ISO = "2026-12-04T23:59:59+01:00"      # P-8
END = 1_796_425_199                        # = 2026-12-04T22:59:59Z
JUDGE_IP = "203.0.113.7"
HASH_KEY_VALUE = "k" * 40


class Clock:
    def __init__(self, t: int = START) -> None:
        self.t = t

    def __call__(self) -> float:
        return float(self.t)


@pytest.fixture
def env(tmp_path: Path, generated_dir: Path, monkeypatch) -> dict:
    monkeypatch.setenv(dataset.ENV_VAR, str(generated_dir))
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>demo</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    db = tmp_path / "access" / "access.sqlite"
    store.init(db, START)
    return {"DEALPILOT_DEMO_MODE": "public", "DEALPILOT_DEMO_STORE": str(db),
            "DEALPILOT_DEMO_END": END_ISO, "DEALPILOT_DEMO_HASH_KEY": HASH_KEY_VALUE,
            "DEALPILOT_DEMO_ORIGIN": ORIGIN, "DEALPILOT_DEMO_STATIC_DIR": str(static),
            dataset.ENV_VAR: str(generated_dir)}


def make_client(env: dict, clock: Clock, ip: str = JUDGE_IP) -> TestClient:
    app = create_app(env, clock=clock)
    return TestClient(app, base_url="https://testserver", headers={"Fly-Client-IP": ip})


def invite(env: dict, label: str, now: int = START, life: int = 7 * 24 * 3600) -> str:
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        return store.create_invitation(conn, label, now, life, END)[1]
    finally:
        conn.close()


def redeem(client: TestClient, token: str, **headers):
    hdrs = {"Origin": ORIGIN, "Content-Type": "application/json"} | headers
    return client.post("/access/redeem", json={"token": token}, headers=hdrs)


def signed_in(env: dict, clock: Clock, label: str = "judge-01") -> TestClient:
    client = make_client(env, clock)
    assert redeem(client, invite(env, label, clock.t)).status_code == 204
    return client


def with_conn(env: dict, fn, *args):
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        return fn(conn, *args)
    finally:
        conn.close()


# --------------------------------------------------------------------------- AUTH

def test_ac_s1_auth_01_redeem_sets_secure_cookie(env) -> None:
    client = make_client(env, Clock())
    r = redeem(client, invite(env, "judge-01"))
    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-dealpilot-demo=")
    for part in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
        assert part.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    assert client.get("/v1/metadata").status_code == 200


@pytest.mark.parametrize("case", ["unknown", "revoked", "expired", "after_end"])
def test_ac_s1_auth_02_refusals_are_generic(env, case) -> None:
    clock = Clock()
    client = make_client(env, clock)
    token = invite(env, "judge-01", life=3600)
    if case == "unknown":
        token = "x" * 43
    elif case == "revoked":
        with_conn(env, store.revoke, "judge-01", START)
    elif case == "expired":
        clock.t = START + 3600
    else:
        clock.t = END
    r = redeem(client, token)
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "invalid_link",
                                 "message": "This link is not valid or has expired.",
                                 "details": []}
    assert "set-cookie" not in r.headers


def test_ac_s1_auth_03_invitations_are_reusable_until_expiry(env) -> None:
    clock = Clock()
    token = invite(env, "judge-01", life=3600)
    assert redeem(make_client(env, clock), token).status_code == 204
    assert redeem(make_client(env, clock, "198.51.100.9"), token).status_code == 204
    clock.t = START + 3600
    assert redeem(make_client(env, clock), token).status_code == 401


def test_ac_s1_auth_04_idle_and_absolute_expiry(env) -> None:
    clock = Clock()
    client = signed_in(env, clock)
    clock.t = START + 59 * 60
    assert client.get("/v1/metadata").status_code == 200       # refreshes last_seen
    clock.t += 3600                                            # idle 60 minutes (P-2)
    assert client.get("/v1/metadata").status_code == 401
    clock2 = Clock()
    client2 = signed_in(env, clock2, "judge-02")
    for step in range(1, 10):                                  # active every 50 minutes
        clock2.t = START + step * 3000
        assert client2.get("/v1/metadata").status_code == 200
    clock2.t = START + 8 * 3600                                 # absolute 8 hours (P-3)
    assert client2.get("/v1/metadata").status_code == 401


def test_ac_s1_auth_05_logout_kills_copied_cookie(env) -> None:
    clock = Clock()
    client = signed_in(env, clock)
    copied = client.cookies.get("__Host-dealpilot-demo")
    r = client.post("/access/logout", json={}, headers={"Origin": ORIGIN})
    assert r.status_code == 204
    other = make_client(env, clock, "198.51.100.9")
    other.cookies.set("__Host-dealpilot-demo", copied)
    assert other.get("/v1/metadata").status_code == 401


def test_ac_s1_auth_06_revocation_is_immediate(env) -> None:
    clock = Clock()
    client = signed_in(env, clock)
    assert client.get("/v1/metadata").status_code == 200
    assert with_conn(env, store.revoke, "judge-01", START) == 1
    assert client.get("/v1/metadata").status_code == 401        # no restart


def test_ac_s1_auth_07_revoke_all(env) -> None:
    clock = Clock()
    a, b = signed_in(env, clock, "judge-01"), signed_in(env, clock, "judge-02")
    with_conn(env, store.revoke_all, START)
    assert a.get("/v1/metadata").status_code == 401
    assert b.get("/v1/metadata").status_code == 401


@pytest.mark.parametrize("change", ["no_store", "store_in_data", "bad_end", "no_offset",
                                    "short_key", "no_origin"])
def test_ac_s1_auth_08_bad_config_refuses_to_start(env, generated_dir, change) -> None:
    bad = dict(env)
    if change == "no_store":
        bad["DEALPILOT_DEMO_STORE"] = str(Path(env["DEALPILOT_DEMO_STORE"]).with_name("none.db"))
    elif change == "store_in_data":
        bad["DEALPILOT_DEMO_STORE"] = str(generated_dir / "access.sqlite")
    elif change == "bad_end":
        bad["DEALPILOT_DEMO_END"] = "soon"
    elif change == "no_offset":
        bad["DEALPILOT_DEMO_END"] = "2026-12-04T23:59:59"
    elif change == "short_key":
        bad["DEALPILOT_DEMO_HASH_KEY"] = "short"
    else:
        del bad["DEALPILOT_DEMO_ORIGIN"]
    with pytest.raises((DemoConfigError, store.StoreError)):
        create_app(bad, clock=Clock())


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"},
                                     {"Content-Type": "text/plain"}, {"Origin": ""}])
def test_ac_s1_auth_09_csrf_checks(env, headers) -> None:
    client = make_client(env, Clock())
    r = redeem(client, invite(env, "judge-01"), **headers)
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_ac_s1_auth_10_large_body_is_refused(env) -> None:
    client = make_client(env, Clock())
    r = client.post("/access/redeem", content='{"token": "' + "a" * 2000 + '"}',
                    headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_ac_s1_auth_11_no_secret_in_logs_or_bodies(env, caplog) -> None:
    caplog.set_level(logging.INFO, logger="dealpilot.demo")
    clock = Clock()
    client = make_client(env, clock)
    token = invite(env, "judge-01")
    r = redeem(client, token)
    session = client.cookies.get("__Host-dealpilot-demo")
    bodies = [r.text, client.get("/v1/metadata").text, client.get("/v1/nope").text]
    for secret in (token, session, HASH_KEY_VALUE, JUDGE_IP):
        assert secret not in caplog.text
        assert not any(secret in b for b in bodies)
    assert "redeem_ok label=judge-01" in caplog.text


def test_ac_s1_auth_12_and_14_store_holds_hashes_only(env) -> None:
    clock = Clock()
    client = make_client(env, clock)
    token = invite(env, "judge-01")
    redeem(client, token)
    session = client.cookies.get("__Host-dealpilot-demo")
    client.get("/v1/metadata")
    raw = b"".join(p.read_bytes() for p in Path(env["DEALPILOT_DEMO_STORE"]).parent.iterdir())
    for value in (token, session, JUDGE_IP):
        assert value.encode() not in raw
    assert store.digest(token).encode() in raw
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/invitations").status_code == 404


def test_ac_s1_auth_13_state_survives_restart(env) -> None:
    clock = Clock()
    client = signed_in(env, clock)
    cookie = client.cookies.get("__Host-dealpilot-demo")
    restarted = make_client(env, clock)                    # a new app on the same store
    restarted.cookies.set("__Host-dealpilot-demo", cookie)
    assert restarted.get("/v1/metadata").status_code == 200
    restarted.post("/access/logout", json={}, headers={"Origin": ORIGIN})
    again = make_client(env, clock)
    again.cookies.set("__Host-dealpilot-demo", cookie)
    assert again.get("/v1/metadata").status_code == 401


def test_ac_s1_auth_15_cookie_is_opaque_random(env) -> None:
    client = signed_in(env, Clock())
    value = client.cookies.get("__Host-dealpilot-demo")
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", value)


# --------------------------------------------------------------------------- STORE

def test_ac_s1_store_01_missing_store_is_not_created(env) -> None:
    db = Path(env["DEALPILOT_DEMO_STORE"])
    for p in db.parent.iterdir():
        p.unlink()
    with pytest.raises(store.StoreError):
        create_app(env, clock=Clock())
    assert not db.exists()


def test_ac_s1_store_02_corrupted_store_refuses_to_start(env) -> None:
    db = Path(env["DEALPILOT_DEMO_STORE"])
    for p in db.parent.iterdir():
        p.unlink()
    db.write_bytes(b"not a database" * 100)
    with pytest.raises(store.StoreError):
        create_app(env, clock=Clock())


def test_ac_s1_store_03_store_error_denies_with_503(env, monkeypatch) -> None:
    client = signed_in(env, Clock())

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")
    monkeypatch.setattr(store, "check_session", broken)
    r = client.get("/v1/metadata")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "service_unavailable"
    assert "seed" not in r.text


def test_ac_s1_store_04_concurrent_redemptions(env) -> None:
    token = invite(env, "judge-01")
    results = []

    def go(i: int) -> None:
        c = make_client(env, Clock(), f"198.51.100.{i}")
        results.append(redeem(c, token).status_code)
    threads = [threading.Thread(target=go, args=(i,)) for i in range(1, 9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [204] * 8
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 8
    finally:
        conn.close()


def test_ac_s1_store_05_revoke_deletes_sessions_in_one_transaction(env) -> None:
    clock = Clock()
    clients = [signed_in(env, clock, "judge-01")]
    with_conn(env, store.revoke, "judge-01", START)
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        conn.close()
    assert clients[0].get("/v1/metadata").status_code == 401


def test_ac_s1_store_06_pragmas_and_modes(env) -> None:
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2      # FULL (P-5)
    finally:
        conn.close()
    if sys.platform != "win32":
        db = Path(env["DEALPILOT_DEMO_STORE"])
        assert db.stat().st_mode & 0o777 == 0o600
        assert db.parent.stat().st_mode & 0o777 == 0o700


def test_ac_s1_store_07_separation_from_analytics() -> None:
    src = Path(store.__file__).resolve().parents[1]
    for path in (src / "analytics").glob("*.py"):
        assert "sqlite" not in path.read_text(encoding="utf-8").lower(), path.name
    for path in (src / "demo").glob("*.py"):
        assert "import duckdb" not in path.read_text(encoding="utf-8"), path.name


def test_ac_s1_store_12_cleanup(env) -> None:
    clock = Clock()
    signed_in(env, clock)
    clock.t = START + 9 * 3600
    redeem(make_client(env, clock, "198.51.100.3"), "x" * 43)       # triggers cleanup
    conn = store.connect(Path(env["DEALPILOT_DEMO_STORE"]))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        old = conn.execute("SELECT COUNT(*) FROM rate_counters WHERE window_start < ?",
                           (START,)).fetchone()[0]
        assert old == 0
        assert conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 1
    finally:
        conn.close()


def test_ac_s1_store_13_fresh_init_refuses_old_links_and_cookies(env) -> None:
    clock = Clock()
    token = invite(env, "judge-01")
    client = make_client(env, clock)
    redeem(client, token)
    db = Path(env["DEALPILOT_DEMO_STORE"])
    for p in db.parent.iterdir():
        p.unlink()
    store.init(db, START)                                   # never restore (P-7)
    fresh = make_client(env, clock)
    fresh.cookies.set("__Host-dealpilot-demo", client.cookies.get("__Host-dealpilot-demo"))
    assert fresh.get("/v1/metadata").status_code == 401
    assert redeem(fresh, token).status_code == 401
    assert redeem(fresh, invite(env, "judge-01")).status_code == 204


def test_ac_s1_store_14_no_restore_command() -> None:
    doc = admin.__doc__ or ""
    assert "never restored" in doc
    with pytest.raises(SystemExit):
        admin.main(["restore"], env={"DEALPILOT_DEMO_STORE": "x"})


# --------------------------------------------------------------------------- RL

def test_ac_s1_rl_01_persistent_limits(env) -> None:
    clock = Clock()
    client = make_client(env, clock)
    codes = [redeem(client, "x" * 43).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    restarted = make_client(env, clock)                     # counters survive a restart
    assert redeem(restarted, "x" * 43).status_code == 429
    clock.t = START + 120
    assert redeem(restarted, "x" * 43).status_code == 401   # new window
    judge = signed_in(env, clock, "judge-01")
    codes = [judge.get("/health").status_code for _ in range(3)]
    assert codes == [200] * 3
    statuses = [judge.get("/v1/metadata").status_code for _ in range(121)]
    assert statuses[:120] == [200] * 120 and statuses[120] == 429   # per invitation


def test_ac_s1_rl_02_forged_forwarded_for_is_ignored(env) -> None:
    clock = Clock()
    client = make_client(env, clock)
    codes = [redeem(client, "x" * 43, **{"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(6)]
    assert codes[-1] == 429


def test_ac_s1_rl_03_no_raw_ip_and_key_dependence(env) -> None:
    clock = Clock()
    client = make_client(env, clock)
    redeem(client, "x" * 43)
    raw = b"".join(p.read_bytes() for p in Path(env["DEALPILOT_DEMO_STORE"]).parent.iterdir())
    assert JUDGE_IP.encode() not in raw and HASH_KEY_VALUE.encode() not in raw
    assert client_key(b"a" * 32, JUDGE_IP) != client_key(b"b" * 32, JUDGE_IP)


def test_ac_s1_rl_04_ipv6_slash_64() -> None:
    a = client_ip(["2001:db8:1:2::1"])
    b = client_ip(["2001:db8:1:2:ffff::9"])
    c = client_ip(["2001:db8:1:3::1"])
    assert a == b != c


# --------------------------------------------------------------------------- API, HDR, DEP

def test_ac_s1_api_01_no_session_is_401(env) -> None:
    client = make_client(env, Clock())
    for path in ("/v1/metadata", "/v1/dimensions", "/v1/sales/metrics"):
        r = client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"
        assert "seed" not in r.text


def test_ac_s1_api_01_forecasts_need_a_session(env) -> None:
    """/v1/forecasts (served since 2026-11-04) is protected like every /v1 route."""
    client = make_client(env, Clock())
    r = client.get("/v1/forecasts?level=total")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert "points" not in r.text
    judge = signed_in(env, Clock())
    assert judge.get("/v1/forecasts?level=total").status_code == 200


def test_ac_s1_api_02_docs_are_off(env) -> None:
    client = make_client(env, Clock())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_ac_s1_api_04_contracts_unchanged_with_session(env) -> None:
    client = signed_in(env, Clock())
    assert client.get("/v1/metadata").json()["seed"] == 42
    r = client.get("/v1/sales/metrics", params={"bogus": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_parameter"


def test_ac_s1_hdr_01_02_security_headers(env) -> None:
    client = signed_in(env, Clock())
    for path in ("/", "/v1/metadata", "/health"):
        h = client.get(path).headers
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "default-src 'self'" in h["content-security-policy"]
        assert h["strict-transport-security"].startswith("max-age=")
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
    assert client.get("/v1/metadata").headers["cache-control"] == "no-store"
    r = client.post("/access/logout", json={}, headers={"Origin": ORIGIN})
    assert r.headers["cache-control"] == "no-store"


def test_ac_s1_dep_02_spa_fallback_and_v1_404(env) -> None:
    client = signed_in(env, Clock())
    assert "<title>demo</title>" in client.get("/analysis").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "<title>demo</title>" in client.get("/../../etc/passwd").text
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("value", [None, "not-an-ip", "203.0.113.7, 10.0.0.1"])
def test_ac_s1_dep_04_requests_around_the_proxy_are_refused(env, value) -> None:
    app = create_app(env, clock=Clock())
    client = TestClient(app, base_url="https://testserver")
    headers = {} if value is None else {"Fly-Client-IP": value}
    for path in ("/v1/metadata", "/", "/access"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.get("/health").status_code == 200


def test_ac_s1_err_02_public_data_unavailable_message(env, tmp_path, monkeypatch) -> None:
    client = signed_in(env, Clock())
    monkeypatch.setenv(dataset.ENV_VAR, str(tmp_path / "missing"))
    r = client.get("/v1/metadata")
    assert r.status_code == 503
    assert r.json()["error"] == {"code": "data_unavailable",
                                 "message": "The demo data is temporarily unavailable.",
                                 "details": []}


# --------------------------------------------------------------------------- OPS

def test_ac_s1_ops_02_05_deadline_on_every_request(env) -> None:
    clock = Clock(END - 1)
    client = signed_in(env, clock)
    assert client.get("/v1/metadata").status_code == 200
    clock.t = END
    assert client.get("/v1/metadata").status_code == 401
    assert redeem(client, "x" * 43).status_code == 401
    db = Path(env["DEALPILOT_DEMO_STORE"])
    for p in db.parent.iterdir():
        p.unlink()                                          # unreadable store: still 401
    assert client.get("/v1/metadata").status_code == 401
    with pytest.raises(ValueError):
        store.create_invitation(sqlite3.connect(":memory:"), "judge-09", END, 60, END)


def test_ac_s1_ops_04_health_without_session(env) -> None:
    app = create_app(env, clock=Clock())
    r = TestClient(app, base_url="https://testserver").get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ac_s1_auth_11_events_reach_the_log_without_pytest_levels(env) -> None:
    """JA-SR-05: the demo logger is enabled at INFO by itself (not only under caplog)."""
    logging.getLogger("dealpilot.demo").setLevel(logging.NOTSET)
    make_client(env, Clock())
    logger = logging.getLogger("dealpilot.demo")
    assert logger.isEnabledFor(logging.INFO)
    assert logger.handlers


def test_admin_cli_create_list_revoke(env, capsys) -> None:
    cli_env = {k: env[k] for k in ("DEALPILOT_DEMO_STORE", "DEALPILOT_DEMO_END",
                                    "DEALPILOT_DEMO_ORIGIN")}
    assert admin.main(["create", "--label", "judge-07"], env=cli_env) == 0
    out = capsys.readouterr().out
    assert f"{ORIGIN}/access#" in out
    assert admin.main(["list"], env=cli_env) == 0
    assert "judge-07" in capsys.readouterr().out
    assert admin.main(["revoke", "judge-07"], env=cli_env) == 0
    assert admin.main(["init"], env=cli_env) == 1             # never overwrites


# --------------------------------------------------------------------------- Render free mode
# Decision S1-D17 / S1-D09 amended 2026-11-03: Render free web service, no persistent disk.

CODE_A = "a" * 20 + "B" * 20          # 40 URL-safe characters
CODE_B = "c" * 20 + "D" * 20
ISSUED = "2026-11-04T09:00:00+01:00"
ISSUED_TS = 1_793_779_200              # = 2026-11-04T08:00:00Z


def render_env(env: dict, invites: str | None = None) -> dict:
    out = dict(env)
    out["DEALPILOT_DEMO_EPHEMERAL_STORE"] = "1"
    out["DEALPILOT_DEMO_CLIENT_IP_HEADER"] = "CF-Connecting-IP"
    db = Path(env["DEALPILOT_DEMO_STORE"])
    for p in db.parent.iterdir():
        p.unlink()
    if invites is not None:
        out["DEALPILOT_DEMO_INVITES"] = invites
    return out


def render_client(env: dict, clock: Clock, ip: str = JUDGE_IP) -> TestClient:
    app = create_app(env, clock=clock)
    return TestClient(app, base_url="https://testserver", headers={"CF-Connecting-IP": ip})


def test_render_ephemeral_store_is_created_and_checked(env) -> None:
    renv = render_env(env)
    db = Path(renv["DEALPILOT_DEMO_STORE"])
    create_app(renv, clock=Clock())
    assert db.is_file()
    conn = store.connect(db)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        conn.close()
    if sys.platform != "win32":
        assert db.stat().st_mode & 0o777 == 0o600


def test_render_ephemeral_mode_never_replaces_a_damaged_store(env) -> None:
    renv = render_env(env)
    Path(renv["DEALPILOT_DEMO_STORE"]).write_bytes(b"garbage" * 100)
    with pytest.raises(store.StoreError):
        create_app(renv, clock=Clock())


def test_strict_mode_still_refuses_to_create(env) -> None:
    strict = render_env(env)
    del strict["DEALPILOT_DEMO_EPHEMERAL_STORE"]
    with pytest.raises(store.StoreError):
        create_app(strict, clock=Clock())
    assert not Path(strict["DEALPILOT_DEMO_STORE"]).exists()


def test_render_invites_bootstrap_hash_only_and_p1_expiry(env, caplog) -> None:
    caplog.set_level(logging.INFO, logger="dealpilot.demo")
    renv = render_env(env, f"judge-01|{CODE_A}|{ISSUED}\njudge-02|{CODE_B}|{ISSUED}")
    clock = Clock(ISSUED_TS + 60)
    client = render_client(renv, clock)
    assert redeem(client, CODE_A).status_code == 204
    assert client.get("/v1/metadata").status_code == 200
    raw = b"".join(p.read_bytes() for p in Path(renv["DEALPILOT_DEMO_STORE"]).parent.iterdir())
    assert CODE_A.encode() not in raw and store.digest(CODE_A).encode() in raw
    assert CODE_A not in caplog.text and CODE_B not in caplog.text
    clock.t = ISSUED_TS + 7 * 24 * 3600                       # P-1: 7 days after issue
    assert redeem(render_client(renv, clock, "198.51.100.4"), CODE_B).status_code == 401


def test_render_invite_removed_from_secret_is_revoked_on_redeploy(env) -> None:
    renv = render_env(env, f"judge-01|{CODE_A}|{ISSUED};judge-02|{CODE_B}|{ISSUED}")
    clock = Clock(ISSUED_TS + 60)
    client = render_client(renv, clock)
    redeem(client, CODE_A)
    cookie = client.cookies.get("__Host-dealpilot-demo")
    redeployed = dict(renv, DEALPILOT_DEMO_INVITES=f"judge-02|{CODE_B}|{ISSUED}")
    del redeployed["DEALPILOT_DEMO_EPHEMERAL_STORE"]          # same store, not recreated
    again = render_client(redeployed, clock)
    again.cookies.set("__Host-dealpilot-demo", cookie)
    assert again.get("/v1/metadata").status_code == 401       # session of a removed label
    assert redeem(again, CODE_A).status_code == 401
    assert redeem(again, CODE_B).status_code == 204


def test_render_invite_expiry_capped_by_shutdown(env) -> None:
    late = "2026-12-01T09:00:00+01:00"
    renv = render_env(env, f"judge-01|{CODE_A}|{late}")
    clock = Clock(END - 1)
    assert redeem(render_client(renv, clock), CODE_A).status_code == 204
    clock.t = END
    assert redeem(render_client(renv, clock, "198.51.100.5"), CODE_A).status_code == 401


@pytest.mark.parametrize("bad", ["judge-01|short|" + ISSUED, "Judge 1|" + CODE_A + "|" + ISSUED,
                                 "judge-01|" + CODE_A, "judge-01|" + CODE_A + "|2026-11-04",
                                 f"judge-01|{CODE_A}|{ISSUED};judge-01|{CODE_B}|{ISSUED}",
                                 f"judge-01|{CODE_A}|{ISSUED};judge-02|{CODE_A}|{ISSUED}"])
def test_render_bad_invites_fail_closed_without_leaking_codes(env, bad) -> None:
    renv = render_env(env, bad)
    with pytest.raises(DemoConfigError) as err:
        create_app(renv, clock=Clock())
    assert CODE_A not in str(err.value) and CODE_B not in str(err.value)


def test_render_client_ip_header_and_403(env) -> None:
    renv = render_env(env)
    app = create_app(renv, clock=Clock())
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/v1/metadata", headers={"Fly-Client-IP": JUDGE_IP}).status_code == 403
    assert client.get("/v1/metadata", headers={"CF-Connecting-IP": JUDGE_IP}).status_code == 401
    assert client.get("/health").status_code == 200


def test_forwarded_for_mode_trusts_only_the_right_end(env) -> None:
    xenv = render_env(env)
    xenv["DEALPILOT_DEMO_CLIENT_IP_HEADER"] = "X-Forwarded-For"
    xenv["DEALPILOT_DEMO_XFF_HOPS"] = "1"
    app = create_app(xenv, clock=Clock())
    client = TestClient(app, base_url="https://testserver")
    codes = [client.post("/access/redeem", json={"token": "x" * 43},
                         headers={"Origin": ORIGIN, "Content-Type": "application/json",
                                  "X-Forwarded-For": f"10.9.9.{i}, {JUDGE_IP}"}).status_code
             for i in range(6)]
    assert codes == [401] * 5 + [429]                          # forged left entries ignored
    assert client.get("/v1/metadata").status_code == 403       # header missing


def test_forwarded_for_hops() -> None:
    from dealpilot.demo.clientkey import from_forwarded_for
    assert from_forwarded_for(["1.1.1.1, 2.2.2.2, 3.3.3.3"], 2) == "2.2.2.2"
    assert from_forwarded_for(["3.3.3.3"], 2) is None


# --------------------------------------------------------------------------- HIGH-1 (review)

def test_ac_s1_auth_10_chunked_body_is_capped_without_buffering(env) -> None:
    """A chunked body with no Content-Length is refused at the first chunk past 1 KB.

    Driven at the ASGI level so the server, not the test client, decides how much it
    reads: 64 chunks of 64 KiB are offered; the app must stop after the first one.
    """
    import anyio

    app = create_app(env, clock=Clock())
    pulled = {"n": 0}
    sent: list[dict] = []
    headers = [(b"host", b"testserver"), (b"origin", ORIGIN.encode()),
               (b"content-type", b"application/json"), (b"transfer-encoding", b"chunked"),
               (b"fly-client-ip", JUDGE_IP.encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "https", "path": "/access/redeem",
             "raw_path": b"/access/redeem", "query_string": b"", "root_path": "",
             "headers": headers, "client": ("127.0.0.1", 1), "server": ("testserver", 443)}

    async def receive():
        pulled["n"] += 1
        if pulled["n"] > 64:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"x" * 65536, "more_body": pulled["n"] < 64}

    async def send(message):
        sent.append(message)

    anyio.run(app, scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert pulled["n"] <= 2                       # stopped at the first oversized chunk


def test_ac_s1_rl_01_redeem_ip_limit_checked_before_the_body(env, monkeypatch) -> None:
    """Once the per-IP redeem limit is reached, the body is not read at all."""
    clock = Clock()
    client = make_client(env, clock)
    for _ in range(5):
        assert redeem(client, "x" * 43).status_code == 401
    from starlette.requests import Request

    def must_not_read(self):
        raise AssertionError("body read despite the rate limit")
    monkeypatch.setattr(Request, "stream", must_not_read)
    r = client.post("/access/redeem", content=b"{}" * 2000,
                    headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 429
