"""The turn lifecycle. Implements docs/specs/conversations.md.

The order of operations here is the design, not an accident: validate, load
history, call the model, and only then write. A failure anywhere before the
write leaves the conversation exactly as it was, which is what makes a retry
safe without an idempotency key.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from app.domain.models import Conversation, Message, MessageRole
from app.domain.ports import ConversationStorePort, LLMPort
from app.services.conversation_service import DEFAULT_TITLE, derive_title


class ChatService:
    def __init__(
        self,
        store: ConversationStorePort,
        llm: LLMPort,
        history_limit: int,
        max_message_length: int,
    ) -> None:
        self._store = store
        self._llm = llm
        self._history_limit = history_limit
        self._max_message_length = max_message_length

    async def send_message(
        self, conversation_id: str, content: str
    ) -> tuple[Message, Message, Conversation]:
        prepared = await self.prepare_turn(conversation_id, content)
        answer = "".join([chunk async for chunk in self.stream_turn(prepared)])
        return await self.finish_turn(prepared, answer)

    async def prepare_turn(self, conversation_id: str, content: str) -> "PreparedTurn":
        """Everything that can fail before the model is called.

        Split out so the streaming route can run these checks while a real HTTP
        status code is still possible — once a stream opens, the status line has
        already been sent.
        """
        text = self._validate(content)

        conversation = await self._store.get_conversation(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation", conversation_id)

        # The window includes the message being sent, so the model always sees
        # it last. Reading history before appending keeps the store the single
        # source of ordering.
        history = await self._store.get_recent_messages(
            conversation_id, limit=max(self._history_limit - 1, 0)
        )

        user_message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=text,
            created_at=datetime.now(UTC),
        )
        return PreparedTurn(
            conversation=conversation,
            history=history,
            user_message=user_message,
        )

    async def stream_turn(self, prepared: "PreparedTurn") -> AsyncIterator[str]:
        """Yield the answer as it arrives. Nothing is persisted here."""
        async for chunk in self._llm.stream([*prepared.history, prepared.user_message]):
            yield chunk

    async def finish_turn(
        self, prepared: "PreparedTurn", answer: str
    ) -> tuple[Message, Message, Conversation]:
        """Persist the completed turn. The only place that writes.

        Called after the answer is fully known, which is what makes a failed
        generation leave nothing behind.
        """
        text = answer.strip()
        if not text:
            # Storing an empty assistant message would look like a successful
            # turn that answered nothing, which is worse than a clear failure
            # the user can retry.
            raise ProviderUnavailableError("the provider returned an empty answer")

        assistant_message = Message(
            id=str(uuid.uuid4()),
            conversation_id=prepared.user_message.conversation_id,
            # A millisecond later so ordering by created_at is deterministic
            # even when both writes land inside the same clock tick.
            created_at=prepared.user_message.created_at + timedelta(milliseconds=1),
            role=MessageRole.ASSISTANT,
            content=text,
        )

        # Only name a conversation that has not been named. A later turn must
        # not rewrite a title the user is already navigating by.
        title = None
        if prepared.conversation.title == DEFAULT_TITLE and not prepared.history:
            title = derive_title(prepared.user_message.content)

        await self._store.add_turn([prepared.user_message, assistant_message], title=title)

        updated = await self._store.get_conversation(prepared.conversation.id)
        return prepared.user_message, assistant_message, updated or prepared.conversation

    def _validate(self, content: str) -> str:
        text = content.strip()
        if not text:
            raise ValidationError("A message cannot be empty.")
        if len(text) > self._max_message_length:
            raise ValidationError(
                f"A message cannot be longer than {self._max_message_length} characters "
                f"(this one is {len(text)})."
            )
        return text


@dataclass(frozen=True)
class PreparedTurn:
    """A validated turn that has not been generated or persisted yet.

    Exists so the streaming route can complete its pre-flight checks and then
    hand the rest of the work off, without either route duplicating the other's
    logic.
    """

    conversation: Conversation
    history: list[Message]
    user_message: Message
