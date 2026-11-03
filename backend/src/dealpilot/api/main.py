"""FastAPI application.

Run locally from `backend/`:
    .venv\\Scripts\\python.exe -m uvicorn dealpilot.api.main:app --host 127.0.0.1 --port 8000
Interactive docs are served at /docs.

Public hackathon demo (spec 014, spec 002 amendment A2-H1): with DEALPILOT_DEMO_MODE=public
the app requires a judge session on every /v1 path, turns off /docs, /redoc and
/openapi.json, sends security headers and serves the built frontend. It refuses to start
(fail closed) if the demo configuration or the access store is missing or invalid.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI

from dealpilot import __version__
from dealpilot.api import v1
from dealpilot.api.errors import install_error_handlers
from dealpilot.demo import config as demo_config


def create_app(env: Mapping[str, str] = os.environ, clock=None) -> FastAPI:
    """Build the app. `clock` (seconds since the epoch) is for tests of the demo mode."""
    public = demo_config.public_mode(env)
    cfg = demo_config.load_config(env) if public else None
    if cfg is not None:
        from dealpilot.demo import web
        web.check_store_at_startup(cfg, None if clock is None else int(clock()))
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if public else {}
    app = FastAPI(title="DealPilot AI", version=__version__, **docs)
    install_error_handlers(app, public=public)  # shared error format on /v1 (spec 002 D13)
    app.include_router(v1.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check: the API process is up. Does not touch data."""
        return {"status": "ok", "version": __version__}

    if cfg is not None:
        from dealpilot.demo import web
        if clock is None:
            web.install(app, cfg)
        else:
            web.install(app, cfg, clock=clock)
    return app


app = create_app()
