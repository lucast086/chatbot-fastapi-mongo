"""Request and response models.

Separate from the domain dataclasses on purpose: these are the wire contract and
can change for presentation reasons without touching the domain, and the domain
can gain fields without leaking them into the API.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.models import Conversation, Message

# A defensive ceiling, not the configured limit. A Pydantic constraint is
# evaluated at class definition time, before any settings object exists, so this
# cannot read MAX_MESSAGE_LENGTH — which means raising that setting above this
# number would have no effect. The service owns the real limit and produces the
# better message; this only stops an absurdly large body from reaching it.
SCHEMA_CEILING = 100_000


class ConversationSummary(BaseModel):
    """What the sidebar shows. Deliberately not a message preview or a count."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationSummary":
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    # Which model produced this answer. Present because several are configured
    # and tried in order — without it a fallback would silently change the
    # answer's provenance. Always null on user messages.
    model: str | None = None
    # The provider stopped at the output cap, so this answer is cut off.
    truncated: bool = False

    @classmethod
    def from_domain(cls, message: Message) -> "MessageOut":
        return cls(
            id=message.id,
            role=message.role.value,
            content=message.content,
            created_at=message.created_at,
            model=message.model,
            truncated=message.truncated,
        )


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model: str | None
    messages: list[MessageOut]

    @classmethod
    def from_domain(
        cls, conversation: Conversation, messages: list[Message]
    ) -> "ConversationDetail":
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            model=conversation.model,
            messages=[MessageOut.from_domain(m) for m in messages],
        )


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=SCHEMA_CEILING)

    @field_validator("content")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        # min_length alone would accept "   ", which is an empty message with
        # extra steps.
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace only")
        return stripped


class SendMessageResponse(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    conversation: ConversationSummary


class ConfigResponse(BaseModel):
    """What the frontend needs on load to decide whether to show the banner."""

    provider_configured: bool
    # Plural: several are configured and tried in order, so the UI cannot claim
    # a single one will answer.
    models: list[str]
    streaming_enabled: bool
    docs_url: str
