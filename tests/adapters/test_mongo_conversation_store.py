"""MongoConversationStore against a real MongoDB."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.mongo.conversation_store import MongoConversationStore
from app.domain.models import Conversation, Message, MessageRole


def _conversation(conversation_id: str, title: str = "Untitled", **kwargs: Any) -> Conversation:
    now = kwargs.pop("now", datetime.now(UTC))
    return Conversation(id=conversation_id, title=title, created_at=now, updated_at=now, **kwargs)


def _turn(conversation_id: str, question: str, answer: str) -> list[Message]:
    now = datetime.now(UTC)
    return [
        Message(
            id=f"{conversation_id}-u",
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=question,
            created_at=now,
        ),
        Message(
            id=f"{conversation_id}-a",
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            created_at=now + timedelta(milliseconds=1),
            model="test-model",
        ),
    ]


async def test_a_created_conversation_can_be_read_back(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)
    await store.create_conversation(_conversation("c1", title="Pasta recipes"))

    found = await store.get_conversation("c1")

    assert found is not None
    assert found.title == "Pasta recipes"
    # tz_aware=True on the client, so this must survive the round trip rather
    # than coming back naive and silently being treated as local time.
    assert found.created_at.tzinfo is not None


async def test_an_unknown_conversation_reads_as_none(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)

    assert await store.get_conversation("does-not-exist") is None


async def test_conversations_are_listed_most_recently_active_first(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)
    old = datetime.now(UTC) - timedelta(days=2)
    await store.create_conversation(_conversation("older", title="Older", now=old))
    await store.create_conversation(_conversation("newer", title="Newer"))

    # Replying to the older conversation has to move it to the top; that is the
    # whole reason updated_at exists.
    await store.add_turn(_turn("older", "still there?", "yes"))

    listed = await store.list_conversations(limit=10)

    assert [c.id for c in listed] == ["older", "newer"]


async def test_a_turn_is_stored_in_order_and_names_the_conversation(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)
    await store.create_conversation(_conversation("c1"))

    await store.add_turn(_turn("c1", "hello", "hi there"), title="hello")

    messages = await store.get_messages("c1")
    assert [(m.role, m.content) for m in messages] == [
        (MessageRole.USER, "hello"),
        (MessageRole.ASSISTANT, "hi there"),
    ]
    conversation = await store.get_conversation("c1")
    assert conversation is not None
    assert conversation.title == "hello"
    assert conversation.model == "test-model"


async def test_recent_messages_returns_the_tail_oldest_first(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)
    await store.create_conversation(_conversation("c1"))
    base = datetime.now(UTC)
    await store.add_turn(
        [
            Message(
                id=f"m{i}",
                conversation_id="c1",
                role=MessageRole.USER,
                content=str(i),
                created_at=base + timedelta(seconds=i),
            )
            for i in range(5)
        ]
    )

    recent = await store.get_recent_messages("c1", limit=3)

    # The three newest, but handed back oldest first so they can go straight
    # into a prompt without the caller re-sorting.
    assert [m.content for m in recent] == ["2", "3", "4"]


async def test_deleting_a_conversation_removes_its_messages(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)
    await store.create_conversation(_conversation("c1"))
    await store.add_turn(_turn("c1", "hello", "hi"))

    deleted = await store.delete_conversation("c1")

    assert deleted is True
    assert await store.get_conversation("c1") is None
    assert await store.get_messages("c1") == []


async def test_deleting_an_unknown_conversation_reports_that_it_was_not_there(
    mongo_db: AsyncDatabase[dict[str, Any]],
) -> None:
    store = MongoConversationStore(mongo_db)

    assert await store.delete_conversation("does-not-exist") is False
