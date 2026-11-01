"""
API setup checks: GET /health and the generated docs.

No spec acceptance criterion covers the API yet (only spec 001 exists), so these tests are
named after the endpoint rather than an AC ID. They don't run the generator.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dealpilot import __version__
from dealpilot.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_api_health_returns_ok(client: TestClient) -> None:
    """GET /health answers 200 with a small JSON status and the package version."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok", "version": __version__}


def test_api_docs_are_served(client: TestClient) -> None:
    """Swagger UI at /docs loads, and the OpenAPI schema lists /health."""
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert schema["info"]["version"] == __version__
