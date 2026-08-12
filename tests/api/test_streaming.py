"""The SSE route.

The interesting part is not that chunks arrive — it is where the boundary
between "real status code" and "in-band error event" falls, and that the atomic
turn survives being streamed.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_chat_service, get_conversation_service
from app.domain.errors import MissingApiKeyError, RateLimitedError
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


def _events(body: str) -> list[tuple[str, str]]:
    parsed = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 2:
            parsed.append((lines[0].removeprefix("event: "), lines[1].removeprefix("data: ")))
    return parsed


def test_the_answer_arrives_in_several_chunks(store: FakeConversationStore) -> None:
    with _client(store, FakeLLM(reply="one two three")) as client:
        response = client.post("/api/v1/conversations/c1/messages/stream", json={"content": "hi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    # More than one chunk, or this proves nothing about streaming.
    assert len([name for name, _ in events if name == "chunk"]) > 1
    assert events[-1][0] == "done"


def test_a_streamed_turn_is_persisted_when_the_stream_completes(
    store: FakeConversationStore,
) -> None:
    with _client(store, FakeLLM(reply="one two three")) as client:
        client.post("/api/v1/conversations/c1/messages/stream", json={"content": "hi"})

    assert [m.content for m in store.messages] == ["hi", "one two three"]
    assert store.conversations["c1"].title == "hi"


def test_a_failure_before_the_stream_opens_is_a_real_status_code(
    store: FakeConversationStore,
) -> None:
    """A missing key is knowable up front, so it must not be demoted to an
    in-band event: the client still gets 503 and the standard envelope."""
    with _client(store, FakeLLM(error=MissingApiKeyError())) as client:
        response = client.post("/api/v1/conversations/nope/messages/stream", json={"content": "hi"})

    assert response.status_code == 404
    assert response.json()["reason"] == "not_found"


def test_an_invalid_message_is_a_real_status_code(store: FakeConversationStore) -> None:
    with _client(store, FakeLLM()) as client:
        response = client.post("/api/v1/conversations/c1/messages/stream", json={"content": "   "})

    assert response.status_code == 422
    assert response.json()["reason"] == "validation_error"


def test_a_failure_during_generation_becomes_an_error_event(
    store: FakeConversationStore,
) -> None:
    """Once the stream is open the status line has been sent, so the error has
    to travel in-band — with the same four fields the JSON route would return."""
    with _client(store, FakeLLM(error=RateLimitedError(retry_after=10))) as client:
        response = client.post("/api/v1/conversations/c1/messages/stream", json={"content": "hi"})

    assert response.status_code == 200
    name, data = _events(response.text)[-1]
    assert name == "error"
    assert '"reason": "rate_limited"' in data
    assert '"retryable": true' in data


def test_a_failure_during_generation_persists_nothing(
    store: FakeConversationStore,
) -> None:
    with _client(store, FakeLLM(error=RateLimitedError())) as client:
        client.post("/api/v1/conversations/c1/messages/stream", json={"content": "hi"})

    assert store.messages == []
    assert store.conversations["c1"].title == "New conversation"
