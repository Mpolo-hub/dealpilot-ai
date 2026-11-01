"""FastAPI application.

Run locally from `backend/`:
    .venv\\Scripts\\python.exe -m uvicorn dealpilot.api.main:app --host 127.0.0.1 --port 8000
Interactive docs are served at /docs.
"""
from __future__ import annotations

from fastapi import FastAPI

from dealpilot import __version__
from dealpilot.api import v1
from dealpilot.api.errors import install_error_handlers

app = FastAPI(title="DealPilot AI", version=__version__)
install_error_handlers(app)  # shared error format on /v1 only (spec 002 D13)
app.include_router(v1.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check: the API process is up. Does not touch data."""
    return {"status": "ok", "version": __version__}
