"""A full turn through the real store.

The service tests use a fake store, which proves the service's logic but cannot
catch a mismatch between what the service expects of the port and what the
MongoDB adapter actually does — a field that does not round-trip, an ordering
assumption that only holds in the fake, a title update that never lands. This
runs the same flow against a real database.

The model is still a double. It is the one dependency that is faked everywhere:
a test suite must not need a network, a key or free-tier quota.
"""

from typing import Any

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.mongo.conversation_store import MongoConversationStore
from app.domain.errors import RateLimitedError
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from tests.fakes import FakeLLM


def _services(
    db: AsyncDatabase[dict[str, Any]], llm: FakeLLM
) -> tuple[ConversationService, ChatService]:
    store = MongoConversationStore(db)
    return (
        ConversationService(store),
        ChatService(store=store, llm=llm, history_limit=4, max_message_length=8000),
    )


async def test_a_turn_survives_a_round_trip_through_mongodb(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    conversations, chat = _services(mongo_db, FakeLLM(reply="Guanciale, not bacon."))
    conversation = await conversations.create()

    await chat.send_message(conversation.id, "How do I make carbonara?")

    stored, messages = await conversations.get(conversation.id)
    assert [m.content for m in messages] == [
        "How do I make carbonara?",
        "Guanciale, not bacon.",
    ]
    # The title was written by the same update that bumped updated_at, so this
    # also confirms that second write actually lands.
    assert stored.title == "How do I make carbonara?"
    assert stored.updated_at > stored.created_at


async def test_history_reaches_the_model_in_order_across_several_turns(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    llm = FakeLLM(reply="ok")
    conversations, chat = _services(mongo_db, llm)
    conversation = await conversations.create()

    await chat.send_message(conversation.id, "first")
    await chat.send_message(conversation.id, "second")
    await chat.send_message(conversation.id, "third")

    context = [m.content for m in llm.received[-1]]
    # history_limit is 4, so the window is the three most recent stored
    # messages plus the one being sent, oldest first. Asserting the exact list
    # rather than "is it sorted": the answers all have the same text, and an
    # order-preservation check over duplicates silently proves nothing.
    assert context == ["ok", "second", "ok", "third"]


async def test_a_failed_turn_leaves_nothing_in_the_database(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    conversations, chat = _services(mongo_db, FakeLLM(error=RateLimitedError()))
    conversation = await conversations.create()

    with pytest.raises(RateLimitedError):
        await chat.send_message(conversation.id, "hi")

    stored, messages = await conversations.get(conversation.id)
    assert messages == []
    assert stored.title == "New conversation"


async def test_resending_after_a_failure_leaves_exactly_one_turn(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    """No idempotency key is needed because the failure wrote nothing. This is
    that claim tested against the real database rather than a fake."""
    conversations, failing = _services(mongo_db, FakeLLM(error=RateLimitedError()))
    conversation = await conversations.create()
    with pytest.raises(RateLimitedError):
        await failing.send_message(conversation.id, "hi")

    _, working = _services(mongo_db, FakeLLM(reply="hello"))
    await working.send_message(conversation.id, "hi")

    _, messages = await conversations.get(conversation.id)
    assert len(messages) == 2


async def test_answering_moves_a_conversation_back_to_the_top_of_the_list(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    conversations, chat = _services(mongo_db, FakeLLM(reply="still here"))
    older = await conversations.create(title="Older")
    await conversations.create(title="Newer")

    await chat.send_message(older.id, "are you there?")

    listed = await conversations.list_recent(limit=10)
    assert listed[0].title == "Older"
