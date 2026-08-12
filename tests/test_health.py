"""Health endpoints.

These run without MongoDB and without an API key, which is the point: the two
degraded states the application is designed to survive are exactly what the
readiness probe has to report correctly.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # The context manager runs the lifespan, so this also covers "startup does
    # not crash when MongoDB is unreachable and no API key is set".
    with TestClient(app) as test_client:
        yield test_client


def test_health_live_does_not_depend_on_anything_external(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready_returns_503_when_mongo_is_unreachable(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["mongo"] == "unreachable"


def test_health_ready_reports_an_unconfigured_provider(client: TestClient) -> None:
    # No OPENROUTER_API_KEY in the test environment, so the provider must be
    # reported as unconfigured rather than silently assumed to be present.
    response = client.get("/health/ready")

    assert response.json()["checks"]["llm_provider"] == "not_configured"
