"""Public demo HTTP layer (spec 014; spec 002 amendment A2-H1; spec 007 amendment A7-H1).

Installed only in public mode. Order of checks on every request:
1. `/health` is exempt (it touches neither the store nor the data).
2. Exactly one well-formed `Fly-Client-IP`, otherwise 403 (no path around the proxy).
3. The shutdown deadline, before any store lookup (JA-FR-11).
4. `/v1`: rate limits and a valid server-side session, otherwise 401, 429 or 503.
Every response gets the security headers; `/v1` and `/access/*` get `Cache-Control:
no-store`. Any store error denies the request (503), never grants it.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from dealpilot.demo import store
from dealpilot.demo.clientkey import client_key, resolve
from dealpilot.demo.config import DemoConfig

log = logging.getLogger("dealpilot.demo")

COOKIE = "__Host-dealpilot-demo"
MAX_BODY = 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
UNAVAILABLE = "The demo is temporarily unavailable."
INVALID_LINK = "This link is not valid or has expired."


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": []}},
                        status_code=status)


def _is_v1(path: str) -> bool:
    return path == "/v1" or path.startswith("/v1/")


def _store_call(config: DemoConfig, fn, *args):
    conn = store.connect(config.store)
    try:
        return fn(conn, *args)
    finally:
        conn.close()


def _enable_event_log() -> None:
    """JA-SR-05: access events must reach the host log under uvicorn (root is WARNING)."""
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
        log.addHandler(handler)


def install(app: FastAPI, config: DemoConfig, clock=time.time) -> None:
    """Add the gate middleware, the access routes and the static frontend."""
    _enable_event_log()

    def now() -> int:
        return int(clock())

    @app.middleware("http")
    async def gate(request: Request, call_next):
        response = await _gate(request, call_next)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        path = request.url.path
        if _is_v1(path) or path.startswith("/access/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def _gate(request: Request, call_next):
        path = request.url.path
        if path == "/health":
            return await call_next(request)
        ip = resolve(request.headers, config.client_ip_header, config.xff_hops)
        if ip is None:
            return _error(403, "forbidden", "Request refused.")
        request.state.client_key = client_key(config.hash_key, ip)
        if not _is_v1(path):
            return await call_next(request)
        if now() >= config.end:
            return _error(401, "unauthorized", "The demo has ended.")
        try:
            label = await run_in_threadpool(
                _store_call, config, store.check_session, request.cookies.get(COOKIE),
                request.state.client_key, now(), config.end)
        except store.RateLimited:
            log.info("rate_limited path=%s", path)
            return _error(429, "rate_limited", "Too many requests, try again in a minute.")
        except (store.StoreError, sqlite3.Error):
            log.warning("store_unavailable path=%s", path)
            return _error(503, "service_unavailable", UNAVAILABLE)
        if label is None:
            log.info("unauthorized path=%s", path)
            return _error(401, "unauthorized", "Sign in with your invitation link.")
        return await call_next(request)

    def _csrf_ok(request: Request) -> bool:
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        return (content_type == "application/json"
                and request.headers.get("origin", "").rstrip("/") == config.origin)

    async def _body_too_large(request: Request) -> bool:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY):
            return True
        return len(await request.body()) > MAX_BODY

    async def _json_body(request: Request) -> dict | None:
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @app.post("/access/redeem", include_in_schema=False)
    async def redeem(request: Request) -> Response:
        if not _csrf_ok(request):
            return _error(403, "forbidden", "Request refused.")
        if await _body_too_large(request):
            return _error(413, "payload_too_large", "Request refused.")
        data = await _json_body(request)
        token = data.get("token") if data else None
        if now() >= config.end:
            return _error(401, "invalid_link", INVALID_LINK)
        if not isinstance(token, str) or not token or len(token) > 200:
            return _error(401, "invalid_link", INVALID_LINK)
        try:
            grant = await run_in_threadpool(_store_call, config, store.redeem, token,
                                            request.state.client_key, now(), config.end)
        except store.RateLimited:
            log.info("redeem_rate_limited")
            return _error(429, "rate_limited", "Too many requests, try again in a minute.")
        except (store.StoreError, sqlite3.Error):
            log.warning("store_unavailable path=/access/redeem")
            return _error(503, "service_unavailable", UNAVAILABLE)
        if grant is None:
            log.info("redeem_refused")
            return _error(401, "invalid_link", INVALID_LINK)
        log.info("redeem_ok label=%s", grant.label)
        response = Response(status_code=204)
        response.set_cookie(COOKIE, grant.session_id, max_age=grant.max_age, path="/",
                            secure=True, httponly=True, samesite="strict")
        return response

    @app.post("/access/logout", include_in_schema=False)
    async def logout(request: Request) -> Response:
        if not _csrf_ok(request):
            return _error(403, "forbidden", "Request refused.")
        try:
            await run_in_threadpool(_store_call, config, store.logout,
                                    request.cookies.get(COOKIE))
        except (store.StoreError, sqlite3.Error):
            return _error(503, "service_unavailable", UNAVAILABLE)
        log.info("logout")
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    static_root = config.static_dir.resolve()
    # Never served by the SPA fallback: the API, the access POST routes, the turned-off
    # docs (A2-H1) and any admin path (spec 014: no admin HTTP route).
    not_frontend = ("access/redeem", "access/logout", "docs", "redoc", "openapi.json",
                    "admin")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        first = path.split("/", 1)[0]
        if _is_v1("/" + path) or path.startswith(not_frontend[:2]) or first in not_frontend:
            raise StarletteHTTPException(status_code=404)
        candidate = (static_root / path).resolve() if path else static_root / "index.html"
        if path and static_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_root / "index.html")


def check_store_at_startup(config: DemoConfig, now: int | None = None) -> None:
    """Prepare and check the access store at start-up (fail closed).

    Strict mode (Fly.io, a persistent volume): the store must already exist; it is never
    created here. Ephemeral mode (DEALPILOT_DEMO_EPHEMERAL_STORE=1, Render free, no disk):
    a missing store is created explicitly with the same schema, pragmas and modes, then
    checked like any other. A store that exists but fails its checks is never replaced.
    With DEALPILOT_DEMO_INVITES set, the invitations are synced from that secret.
    """
    path = Path(config.store)
    moment = int(time.time()) if now is None else now
    if config.ephemeral and not path.exists():
        store.init(path, moment)
        log.warning("ephemeral access store created")
    store.check(path)
    if config.invites is not None:
        conn = store.connect(path)
        try:
            store.sync_invitations(conn, config.invites, moment)
        finally:
            conn.close()
        log.warning("invitations synced: %d", len(config.invites))
