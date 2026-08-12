"""Test doubles.

`FakeConversationStore` keeps service tests away from a database when the
database is not what is under test. `FakeLLM` is the only double for the model
provider anywhere in this project, and it is never wired at runtime — in a
chatbot, generation is the product, so a runtime fake would make the app look
like it works while hiding whether the real integration does.
"""

from collections.abc import AsyncIterator

from app.domain.errors import ProviderError
from app.domain.models import Chunk, Conversation, Message


class FakeConversationStore:
    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.messages: list[Message] = []

    async def create_conversation(self, conversation: Conversation) -> None:
        self.conversations[conversation.id] = conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_conversations(self, limit: int) -> list[Conversation]:
        ordered = sorted(self.conversations.values(), key=lambda c: c.updated_at, reverse=True)
        return ordered[:limit]

    async def delete_conversation(self, conversation_id: str) -> bool:
        existed = self.conversations.pop(conversation_id, None) is not None
        self.messages = [m for m in self.messages if m.conversation_id != conversation_id]
        return existed

    async def add_turn(self, messages: list[Message], title: str | None = None) -> None:
        if not messages:
            return
        self.messages.extend(messages)
        conversation = self.conversations[messages[0].conversation_id]
        last = messages[-1]
        self.conversations[conversation.id] = Conversation(
            id=conversation.id,
            title=title if title is not None else conversation.title,
            created_at=conversation.created_at,
            updated_at=messages[-1].created_at,
            model=last.model or conversation.model,
        )

    async def rename_conversation(self, conversation_id: str, title: str) -> None:
        current = self.conversations[conversation_id]
        self.conversations[conversation_id] = Conversation(
            id=current.id,
            title=title,
            created_at=current.created_at,
            updated_at=current.updated_at,
            model=current.model,
        )

    async def get_recent_messages(self, conversation_id: str, limit: int) -> list[Message]:
        # `[-0:]` is `[0:]`, the whole list. The fake used to reproduce the real
        # store's limit(0) bug exactly, which is why no test caught it: a double
        # written against the implementation instead of the contract agrees with
        # it even when both are wrong.
        if limit <= 0:
            return []
        return self._for(conversation_id)[-limit:]

    async def get_messages(self, conversation_id: str) -> list[Message]:
        return self._for(conversation_id)

    def _for(self, conversation_id: str) -> list[Message]:
        return [m for m in self.messages if m.conversation_id == conversation_id]


class FakeLLM:
    """Deterministic, offline, free.

    Answers with a fixed reply, or raises whichever `ProviderError` a test needs
    in order to exercise a branch of the error taxonomy.
    """

    def __init__(
        self,
        reply: str = "A fake answer.",
        error: ProviderError | None = None,
        model: str = "fake/model",
    ) -> None:
        self._reply = reply
        self._error = error
        self._model = model
        self.received: list[list[Message]] = []

    async def stream(self, messages: list[Message]) -> AsyncIterator[Chunk]:
        self.received.append(messages)
        if self._error is not None:
            raise self._error
        # Several chunks, not one: the JSON path joins them, and yielding a
        # single chunk would let a broken join pass unnoticed.
        for word in self._reply.split(" "):
            yield Chunk(text=word + " ", model=self._model)


class FakeTitleGenerator:
    """Returns a fixed title, or None to stand in for a provider that failed."""

    def __init__(self, title: str | None = "A generated title") -> None:
        self._title = title
        self.calls = 0

    async def suggest_title(self, question: str, answer: str) -> str | None:
        self.calls += 1
        return self._title
