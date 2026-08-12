"""Health endpoints.

Each test states the environment it is testing instead of inheriting whatever
happens to be running. An earlier version of this file asserted "MongoDB is
unreachable" and "no API key is configured" without arranging either, so it
passed only while nothing was running locally and started failing the moment the
stack came up. Tests that pass for the wrong reason are worse than missing ones.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.dependencies import get_db
from app.main import app


class _UnreachableDb:
    async def command(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("no server available")


class _ReachableDb:
    async def command(self, *_args: Any, **_kwargs: Any) -> dict[str, float]:
        return {"ok": 1.0}


def _settings(**overrides: Any) -> Settings:
    # _env_file=None so a developer's local .env cannot change the outcome.
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _configure(db: Any, api_key: str) -> None:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: _settings(openrouter_api_key=api_key)


def test_health_live_does_not_depend_on_anything_external(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_ready_is_503_when_mongo_is_unreachable(client: TestClient) -> None:
    _configure(_UnreachableDb(), api_key="sk-present")

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"mongo": "unreachable", "llm_provider": "ok"},
    }


def test_ready_is_200_and_degraded_when_only_the_api_key_is_missing(client: TestClient) -> None:
    # The decision this test exists to protect: a missing key must not fail
    # readiness, or `depends_on: service_healthy` never passes and Docker
    # restarts a healthy container in a loop.
    _configure(_ReachableDb(), api_key="")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "checks": {"mongo": "ok", "llm_provider": "not_configured"},
    }


def test_ready_is_ok_when_everything_is_configured(client: TestClient) -> None:
    _configure(_ReachableDb(), api_key="sk-present")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"mongo": "ok", "llm_provider": "ok"},
    }


def test_whitespace_only_api_key_counts_as_not_configured() -> None:
    assert _settings(openrouter_api_key="   ").provider_configured is False
    assert _settings(openrouter_api_key="sk-x").provider_configured is True
