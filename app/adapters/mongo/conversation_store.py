"""MongoConversationStore: the ConversationStorePort backed by two collections.

Messages live in their own collection rather than in an array inside the
conversation document. A chat has no natural length limit, and a growing array
runs into the 16MB document cap while making every write rewrite the whole
document. See docs/decisions.md.
"""

from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.domain.models import Conversation, Message, MessageRole


class MongoConversationStore:
    def __init__(self, db: AsyncDatabase[dict[str, Any]]) -> None:
        self._conversations = db.conversations
        self._messages = db.messages

    async def create_conversation(self, conversation: Conversation) -> None:
        await self._conversations.insert_one(_conversation_to_mongo(conversation))

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        raw = await self._conversations.find_one({"_id": conversation_id})
        return _conversation_from_mongo(raw) if raw is not None else None

    async def list_conversations(self, limit: int) -> list[Conversation]:
        cursor = self._conversations.find().sort("updated_at", -1).limit(limit)
        return [_conversation_from_mongo(raw) for raw in await cursor.to_list()]

    async def delete_conversation(self, conversation_id: str) -> bool:
        result = await self._conversations.delete_one({"_id": conversation_id})
        # Messages go regardless of whether the conversation document was there,
        # so a partially deleted conversation cannot leave messages behind
        # forever.
        await self._messages.delete_many({"conversation_id": conversation_id})
        return result.deleted_count > 0

    async def add_turn(self, messages: list[Message], title: str | None = None) -> None:
        if not messages:
            return

        # One command, so the pair cannot be split by a crash between two
        # separate inserts. This is not a transaction — MongoDB runs standalone
        # here — but it removes the window that mattered.
        await self._messages.insert_many([_message_to_mongo(m) for m in messages])

        update: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if title is not None:
            update["title"] = title
        last = messages[-1]
        if last.model is not None:
            update["model"] = last.model

        # Outside the guarantee above on purpose. If this fails, the worst case
        # is one row briefly out of order in the sidebar; the conversation
        # itself reads correctly because it is loaded from `messages`.
        await self._conversations.update_one({"_id": messages[0].conversation_id}, {"$set": update})

    async def get_recent_messages(self, conversation_id: str, limit: int) -> list[Message]:
        cursor = (
            self._messages.find({"conversation_id": conversation_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        raw_messages = await cursor.to_list()
        return [_message_from_mongo(raw) for raw in reversed(raw_messages)]

    async def get_messages(self, conversation_id: str) -> list[Message]:
        cursor = self._messages.find({"conversation_id": conversation_id}).sort("created_at", 1)
        return [_message_from_mongo(raw) for raw in await cursor.to_list()]


def _conversation_to_mongo(conversation: Conversation) -> dict[str, Any]:
    return {
        "_id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "model": conversation.model,
    }


def _conversation_from_mongo(raw: dict[str, Any]) -> Conversation:
    return Conversation(
        id=raw["_id"],
        title=raw["title"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        model=raw.get("model"),
    )


def _message_to_mongo(message: Message) -> dict[str, Any]:
    return {
        "_id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role.value,
        "content": message.content,
        "created_at": message.created_at,
        "model": message.model,
        "finish_reason": message.finish_reason,
        "usage": message.usage,
    }


def _message_from_mongo(raw: dict[str, Any]) -> Message:
    return Message(
        id=raw["_id"],
        conversation_id=raw["conversation_id"],
        role=MessageRole(raw["role"]),
        content=raw["content"],
        created_at=raw["created_at"],
        model=raw.get("model"),
        finish_reason=raw.get("finish_reason"),
        usage=raw.get("usage") or {},
    )
