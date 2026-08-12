"""The turn lifecycle. Implements docs/specs/conversations.md.

The order of operations here is the design, not an accident: validate, load
history, call the model, and only then write. A failure anywhere before the
write leaves the conversation exactly as it was, which is what makes a retry
safe without an idempotency key.
"""

import uuid
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

        now = datetime.now(UTC)
        user_message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=text,
            created_at=now,
        )

        answer = await self._generate([*history, user_message])

        assistant_message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            # A millisecond later so ordering by created_at is deterministic
            # even when both writes land inside the same clock tick.
            created_at=now + timedelta(milliseconds=1),
            role=MessageRole.ASSISTANT,
            content=answer,
        )

        # Only name a conversation that has not been named. A later turn must
        # not rewrite a title the user is already navigating by.
        title = None
        if conversation.title == DEFAULT_TITLE and not history:
            title = derive_title(text)

        await self._store.add_turn([user_message, assistant_message], title=title)

        updated = await self._store.get_conversation(conversation_id)
        return user_message, assistant_message, updated or conversation

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

    async def _generate(self, context: list[Message]) -> str:
        chunks = [chunk async for chunk in self._llm.stream(context)]
        answer = "".join(chunks).strip()
        if not answer:
            # Storing an empty assistant message would look like a successful
            # turn that answered nothing, which is worse than a clear failure
            # the user can retry.
            raise ProviderUnavailableError("the provider returned an empty answer")
        return answer
