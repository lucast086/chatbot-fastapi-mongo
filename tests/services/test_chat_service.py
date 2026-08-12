"""ChatService against doubles.

Each test names the verification criterion from docs/specs/conversations.md that
it covers, so a change to the spec has an obvious blast radius in the suite.
"""

from datetime import UTC, datetime

import pytest

from app.domain.errors import (
    MissingApiKeyError,
    NotFoundError,
    ProviderUnavailableError,
    RateLimitedError,
    ValidationError,
)
from app.domain.models import Conversation, MessageRole
from app.services.chat_service import ChatService
from tests.fakes import FakeConversationStore, FakeLLM


@pytest.fixture
def store() -> FakeConversationStore:
    store = FakeConversationStore()
    now = datetime.now(UTC)
    store.conversations["c1"] = Conversation(
        id="c1", title="New conversation", created_at=now, updated_at=now
    )
    return store


def _service(store: FakeConversationStore, llm: FakeLLM, history_limit: int = 20) -> ChatService:
    return ChatService(store=store, llm=llm, history_limit=history_limit, max_message_length=8000)


# --- a successful turn ------------------------------------------------------


async def test_a_turn_stores_exactly_two_messages_question_first(
    store: FakeConversationStore,
) -> None:
    service = _service(store, FakeLLM(reply="Hello there"))

    await service.send_message("c1", "hi")

    assert [(m.role, m.content) for m in store.messages] == [
        (MessageRole.USER, "hi"),
        (MessageRole.ASSISTANT, "Hello there"),
    ]


async def test_a_turn_returns_both_messages_and_the_conversation(
    store: FakeConversationStore,
) -> None:
    service = _service(store, FakeLLM(reply="Hello there"))

    user_message, assistant_message, conversation = await service.send_message("c1", "hi")

    assert user_message.content == "hi"
    assert assistant_message.content == "Hello there"
    assert conversation.id == "c1"


async def test_answering_moves_the_conversation_to_the_top(
    store: FakeConversationStore,
) -> None:
    before = store.conversations["c1"].updated_at
    service = _service(store, FakeLLM())

    _, _, conversation = await service.send_message("c1", "hi")

    assert conversation.updated_at > before


# --- titles -----------------------------------------------------------------


async def test_the_first_turn_titles_the_conversation_from_the_message(
    store: FakeConversationStore,
) -> None:
    service = _service(store, FakeLLM())

    await service.send_message("c1", "How do I make carbonara?")

    assert store.conversations["c1"].title == "How do I make carbonara?"


async def test_a_later_turn_does_not_overwrite_the_title(
    store: FakeConversationStore,
) -> None:
    service = _service(store, FakeLLM())
    await service.send_message("c1", "How do I make carbonara?")

    await service.send_message("c1", "and what wine goes with it?")

    assert store.conversations["c1"].title == "How do I make carbonara?"


# --- history window ---------------------------------------------------------


async def test_the_model_receives_at_most_the_configured_number_of_messages(
    store: FakeConversationStore,
) -> None:
    llm = FakeLLM()
    service = _service(store, llm, history_limit=4)
    for i in range(5):
        await service.send_message("c1", f"question {i}")

    # The last call sees the window, which includes the message just sent.
    last_context = llm.received[-1]
    assert len(last_context) <= 4


async def test_the_model_receives_history_oldest_first(
    store: FakeConversationStore,
) -> None:
    llm = FakeLLM()
    service = _service(store, llm, history_limit=20)
    await service.send_message("c1", "first")

    await service.send_message("c1", "second")

    contents = [m.content for m in llm.received[-1]]
    assert contents.index("first") < contents.index("second")


async def test_the_message_being_sent_is_the_last_thing_the_model_sees(
    store: FakeConversationStore,
) -> None:
    llm = FakeLLM()
    service = _service(store, llm)

    await service.send_message("c1", "the new question")

    assert llm.received[-1][-1].content == "the new question"


# --- failures persist nothing -----------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        MissingApiKeyError(),
        RateLimitedError(retry_after=30),
        ProviderUnavailableError("timeout"),
    ],
)
async def test_a_provider_failure_stores_nothing(
    store: FakeConversationStore, error: Exception
) -> None:
    service = _service(store, FakeLLM(error=error))  # type: ignore[arg-type]

    with pytest.raises(type(error)):
        await service.send_message("c1", "hi")

    assert store.messages == []
    assert store.conversations["c1"].title == "New conversation"


async def test_resending_after_a_failure_produces_exactly_one_turn(
    store: FakeConversationStore,
) -> None:
    """The reason no idempotency key is needed: a failure left nothing behind,
    so the retry is just the same request again."""
    failing = FakeLLM(error=RateLimitedError())
    with pytest.raises(RateLimitedError):
        await _service(store, failing).send_message("c1", "hi")

    await _service(store, FakeLLM(reply="ok")).send_message("c1", "hi")

    assert len(store.messages) == 2


async def test_an_empty_answer_does_not_produce_a_stored_turn(
    store: FakeConversationStore,
) -> None:
    service = _service(store, FakeLLM(reply=""))

    with pytest.raises(ProviderUnavailableError):
        await service.send_message("c1", "hi")

    assert store.messages == []


# --- input and lookup validation --------------------------------------------


@pytest.mark.parametrize("content", ["", "   ", "\n\t "])
async def test_an_empty_message_is_rejected_before_any_model_call(
    store: FakeConversationStore, content: str
) -> None:
    llm = FakeLLM()
    service = _service(store, llm)

    with pytest.raises(ValidationError):
        await service.send_message("c1", content)

    assert llm.received == []


async def test_a_too_long_message_is_rejected_with_the_limit_named(
    store: FakeConversationStore,
) -> None:
    llm = FakeLLM()
    service = _service(store, llm)

    with pytest.raises(ValidationError) as caught:
        await service.send_message("c1", "x" * 8001)

    assert "8000" in str(caught.value)
    assert llm.received == []


async def test_sending_to_an_unknown_conversation_is_not_found(
    store: FakeConversationStore,
) -> None:
    llm = FakeLLM()
    service = _service(store, llm)

    with pytest.raises(NotFoundError):
        await service.send_message("does-not-exist", "hi")

    assert llm.received == []
