"""The send-message endpoint, including how each provider failure surfaces.

The service-level behaviour is covered in tests/services/. What is verified here
is the HTTP contract: status codes, the error envelope, and the Retry-After
header — the things a frontend actually branches on.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_chat_service, get_conversation_service
from app.domain.errors import (
    InvalidCredentialsError,
    MissingApiKeyError,
    ModelUnavailableError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import Conversation
from app.main import app
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from tests.fakes import FakeConversationStore, FakeLLM


@pytest.fixture
def store() -> FakeConversationStore:
    store = FakeConversationStore()
    now = datetime.now(UTC)
    store.conversations["c1"] = Conversation(
        id="c1", title="New conversation", created_at=now, updated_at=now
    )
    return store


def _client(store: FakeConversationStore, llm: FakeLLM) -> TestClient:
    app.dependency_overrides[get_conversation_service] = lambda: ConversationService(store)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        store=store, llm=llm, history_limit=20, max_message_length=8000
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_sending_a_message_returns_the_turn_and_the_conversation(
    store: FakeConversationStore,
) -> None:
    with _client(store, FakeLLM(reply="Hello there")) as client:
        response = client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})

    assert response.status_code == 201
    body = response.json()
    assert body["user_message"]["content"] == "hi"
    assert body["assistant_message"]["content"] == "Hello there"
    assert body["conversation"]["title"] == "hi"


def test_the_turn_is_readable_afterwards(store: FakeConversationStore) -> None:
    with _client(store, FakeLLM(reply="Hello there")) as client:
        client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})
        detail = client.get("/api/v1/conversations/c1").json()

    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_reason", "expected_retryable"),
    [
        (MissingApiKeyError(), 503, "missing_api_key", False),
        (InvalidCredentialsError(), 502, "invalid_credentials", False),
        (RateLimitedError(retry_after=30), 429, "rate_limited", True),
        (ProviderUnavailableError("timeout"), 504, "provider_unavailable", True),
        (ModelUnavailableError("some/model"), 502, "model_unavailable", False),
    ],
)
def test_each_provider_failure_has_its_own_status_and_reason(
    store: FakeConversationStore,
    error: ProviderError,
    expected_status: int,
    expected_reason: str,
    expected_retryable: bool,
) -> None:
    with _client(store, FakeLLM(error=error)) as client:
        response = client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})

    assert response.status_code == expected_status
    body = response.json()
    assert body["reason"] == expected_reason
    assert body["retryable"] is expected_retryable
    assert body["docs_url"].startswith("https://")
    # No stack trace, no framework internals — a sentence a person can act on.
    assert body["message"] and not body["message"].startswith("Traceback")


def test_a_rate_limit_sets_retry_after(store: FakeConversationStore) -> None:
    with _client(store, FakeLLM(error=RateLimitedError(retry_after=30))) as client:
        response = client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})

    assert response.headers["Retry-After"] == "30"


def test_no_retry_after_header_when_the_provider_did_not_send_one(
    store: FakeConversationStore,
) -> None:
    with _client(store, FakeLLM(error=RateLimitedError())) as client:
        response = client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})

    assert "Retry-After" not in response.headers


def test_a_failed_turn_leaves_the_conversation_untouched(
    store: FakeConversationStore,
) -> None:
    with _client(store, FakeLLM(error=RateLimitedError())) as client:
        client.post("/api/v1/conversations/c1/messages", json={"content": "hi"})
        detail = client.get("/api/v1/conversations/c1").json()

    assert detail["messages"] == []
    assert detail["title"] == "New conversation"


@pytest.mark.parametrize("content", ["", "   "])
def test_an_empty_message_is_rejected_by_the_schema(
    store: FakeConversationStore, content: str
) -> None:
    with _client(store, FakeLLM()) as client:
        response = client.post("/api/v1/conversations/c1/messages", json={"content": content})

    assert response.status_code == 422
    assert response.json()["reason"] == "validation_error"


def test_sending_to_an_unknown_conversation_is_404(store: FakeConversationStore) -> None:
    with _client(store, FakeLLM()) as client:
        response = client.post("/api/v1/conversations/nope/messages", json={"content": "hi"})

    assert response.status_code == 404
    assert response.json()["reason"] == "not_found"
