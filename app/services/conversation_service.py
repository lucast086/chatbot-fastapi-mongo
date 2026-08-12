"""Conversation lifecycle: create, read, list, delete.

Knows ports, never implementations. It also owns id and timestamp generation, so
those happen in one place rather than in each adapter.
"""

import uuid
from datetime import UTC, datetime

from app.domain.errors import NotFoundError
from app.domain.models import Conversation, Message
from app.domain.ports import ConversationStorePort

DEFAULT_TITLE = "New conversation"
# Long enough to tell two conversations apart in a sidebar, short enough not to
# wrap. The title is the only thing distinguishing them, so it has to be useful.
TITLE_MAX_LENGTH = 60


class ConversationService:
    def __init__(self, store: ConversationStorePort) -> None:
        self._store = store

    async def create(self, title: str | None = None) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(
            id=str(uuid.uuid4()),
            title=title or DEFAULT_TITLE,
            created_at=now,
            updated_at=now,
        )
        await self._store.create_conversation(conversation)
        return conversation

    # Not named `list`: a method by that name shadows the builtin inside the
    # class body, so every `list[...]` annotation below it fails to resolve.
    async def list_recent(self, limit: int) -> list[Conversation]:
        return await self._store.list_conversations(limit)

    async def get(self, conversation_id: str) -> tuple[Conversation, list[Message]]:
        conversation = await self._require(conversation_id)
        messages = await self._store.get_messages(conversation_id)
        return conversation, messages

    async def delete(self, conversation_id: str) -> None:
        if not await self._store.delete_conversation(conversation_id):
            raise NotFoundError("Conversation", conversation_id)

    async def _require(self, conversation_id: str) -> Conversation:
        conversation = await self._store.get_conversation(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation", conversation_id)
        return conversation


def derive_title(first_message: str) -> str:
    """Name a conversation after its opening message.

    Not model-generated: this runs on data already in hand, costs nothing and
    cannot fail, which matters because the title is the only thing identifying a
    conversation in the sidebar. A model-generated title improves on it but must
    not be what the list depends on.
    """
    collapsed = " ".join(first_message.split())
    if len(collapsed) <= TITLE_MAX_LENGTH:
        return collapsed or DEFAULT_TITLE
    # Cut on a word boundary when there is one reasonably close to the limit,
    # rather than mid-word.
    truncated = collapsed[:TITLE_MAX_LENGTH]
    last_space = truncated.rfind(" ")
    if last_space > TITLE_MAX_LENGTH // 2:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"
