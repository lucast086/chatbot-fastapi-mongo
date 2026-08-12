"""Conversation endpoints, against a fake store.

The store is faked here because what is under test is the HTTP layer: status
codes, serialisation and the error envelope. The store's own behaviour is
covered against a real MongoDB in tests/adapters/.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_conversation_service
from app.main import app
from app.services.conversation_service import ConversationService
from tests.fakes import FakeConversationStore


@pytest.fixture
def store() -> FakeConversationStore:
    return FakeConversationStore()


@pytest.fixture
def client(store: FakeConversationStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_conversation_service] = lambda: ConversationService(store)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_creating_a_conversation_returns_201_and_a_default_title(client: TestClient) -> None:
    response = client.post("/api/v1/conversations", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "New conversation"
    assert body["id"]


def test_conversations_are_listed_most_recently_active_first(client: TestClient) -> None:
    first = client.post("/api/v1/conversations", json={"title": "First"}).json()
    second = client.post("/api/v1/conversations", json={"title": "Second"}).json()

    listed = client.get("/api/v1/conversations").json()

    assert [c["id"] for c in listed] == [second["id"], first["id"]]
    # The sidebar contract: no message preview, no message count.
    assert set(listed[0]) == {"id", "title", "created_at", "updated_at"}


def test_reading_a_conversation_returns_it_with_its_messages(client: TestClient) -> None:
    created = client.post("/api/v1/conversations", json={"title": "Empty"}).json()

    response = client.get(f"/api/v1/conversations/{created['id']}")

    assert response.status_code == 200
    assert response.json()["messages"] == []


def test_deleting_a_conversation_returns_204_and_it_is_gone(client: TestClient) -> None:
    created = client.post("/api/v1/conversations", json={}).json()

    assert client.delete(f"/api/v1/conversations/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/conversations/{created['id']}").status_code == 404


def test_an_unknown_conversation_returns_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/conversations/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["reason"] == "not_found"
    assert body["retryable"] is False
    assert body["docs_url"].endswith("#troubleshooting-not-found")
    # `detail` is FastAPI's default shape. Its absence is the point: every
    # error in this API has the same four fields.
    assert "detail" not in body


def test_deleting_an_unknown_conversation_returns_the_error_envelope(client: TestClient) -> None:
    response = client.delete("/api/v1/conversations/nope")

    assert response.status_code == 404
    assert response.json()["reason"] == "not_found"


def test_an_unknown_route_also_uses_the_error_envelope(client: TestClient) -> None:
    # Starlette would answer {"detail": "Not Found"} here without the override.
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert set(response.json()) == {"reason", "message", "retryable", "docs_url"}


def test_a_too_long_title_is_rejected_with_the_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/conversations", json={"title": "x" * 201})

    assert response.status_code == 422
    body = response.json()
    assert body["reason"] == "validation_error"
    assert "title" in body["message"]
