"""The turn lifecycle. Implements docs/specs/conversations.md.

The order of operations here is the design, not an accident: validate, load
history, call the model, and only then write. A failure anywhere before the
write leaves the conversation exactly as it was, which is what makes a retry
safe without an idempotency key.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.errors import (
    MissingApiKeyError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from app.domain.models import Chunk, Conversation, Message, MessageRole
from app.domain.ports import ConversationStorePort, LLMPort, TitleGeneratorPort
from app.services.conversation_service import DEFAULT_TITLE, derive_title

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        store: ConversationStorePort,
        llm: LLMPort,
        history_limit: int,
        max_message_length: int,
        max_history_chars: int = 24_000,
        titles: TitleGeneratorPort | None = None,
        provider_configured: bool = True,
    ) -> None:
        self._store = store
        self._llm = llm
        # Known before any I/O, so the streaming route can report it as a real
        # status code. The adapter keeps its own guard as defence in depth.
        self._provider_configured = provider_configured
        self._history_limit = history_limit
        self._max_message_length = max_message_length
        self._max_history_chars = max_history_chars
        # Optional: without it, conversations keep the title derived from their
        # first message, which is already good enough to navigate by.
        self._titles = titles

    async def send_message(
        self, conversation_id: str, content: str
    ) -> tuple[Message, Message, Conversation]:
        prepared = await self.prepare_turn(conversation_id, content)
        chunks = [chunk async for chunk in self.stream_turn(prepared)]
        return await self.finish_turn(prepared, chunks)

    async def prepare_turn(self, conversation_id: str, content: str) -> "PreparedTurn":
        """Everything that can fail before the model is called.

        Split out so the streaming route can run these checks while a real HTTP
        status code is still possible — once a stream opens, the status line has
        already been sent.
        """
        # First, because it needs no I/O and because the streaming route can
        # only return a status code for what is known before the stream opens.
        if not self._provider_configured:
            raise MissingApiKeyError()

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
            history=self._within_budget(history, len(text)),
            user_message=user_message,
        )

    def _within_budget(self, history: list[Message], reserved: int) -> list[Message]:
        """Drop the oldest messages until the prompt fits the character budget.

        The message count alone does not bound prompt size, so a long
        conversation can exceed a model's context window — which arrives as a
        provider error rather than a degradation. Trimming from the oldest end
        keeps the most recent exchange, which is the part that matters.
        """
        budget = self._max_history_chars - reserved
        kept: list[Message] = []
        for message in reversed(history):
            budget -= len(message.content)
            if budget < 0:
                break
            kept.append(message)
        if len(kept) < len(history):
            logger.info(
                "History trimmed to %d of %d messages to fit the character budget.",
                len(kept),
                len(history),
            )
        return list(reversed(kept))

    async def stream_turn(self, prepared: "PreparedTurn") -> AsyncIterator[Chunk]:
        """Yield the answer as it arrives. Nothing is persisted here."""
        async for chunk in self._llm.stream([*prepared.history, prepared.user_message]):
            yield chunk

    async def finish_turn(
        self, prepared: "PreparedTurn", chunks: list[Chunk]
    ) -> tuple[Message, Message, Conversation]:
        """Persist the completed turn. The only place that writes.

        Called after the answer is fully known, which is what makes a failed
        generation leave nothing behind.
        """
        text = "".join(c.text for c in chunks).strip()
        if not text:
            # Storing an empty assistant message would look like a successful
            # turn that answered nothing, which is worse than a clear failure
            # the user can retry.
            raise ProviderUnavailableError("the provider returned an empty answer")

        assistant_message = Message(
            id=str(uuid.uuid4()),
            conversation_id=prepared.user_message.conversation_id,
            # When the answer actually arrived, with a floor of one
            # millisecond after the question so ordering stays deterministic —
            # BSON truncates to milliseconds, so anything closer would collide.
            # Stamping question+1ms unconditionally made every answer claim to
            # have arrived instantly, which threw away the only latency signal
            # a stored transcript has.
            created_at=max(
                datetime.now(UTC),
                prepared.user_message.created_at + timedelta(milliseconds=1),
            ),
            role=MessageRole.ASSISTANT,
            content=text,
            # Whichever model actually answered — with more than one
            # configured, that is not necessarily the first.
            model=chunks[-1].model,
            truncated=chunks[-1].finish_reason == "length",
        )

        # Only name a conversation that has not been named. A later turn must
        # not rewrite a title the user is already navigating by.
        title = None
        if prepared.conversation.title == DEFAULT_TITLE and not prepared.history:
            title = derive_title(prepared.user_message.content)

        if assistant_message.truncated:
            logger.warning(
                "Model %s hit the output cap; the stored answer is cut off.",
                assistant_message.model,
            )

        await self._store.add_turn([prepared.user_message, assistant_message], title=title)

        # After the turn is safely stored, never before. A better title is a
        # nicety; the turn is the product, and one must not be able to cost the
        # other. Only for the turn that named the conversation.
        if title is not None and self._titles is not None:
            suggested = await self._titles.suggest_title(prepared.user_message.content, text)
            if suggested:
                await self._store.rename_conversation(
                    prepared.conversation.id, derive_title(suggested)
                )

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
