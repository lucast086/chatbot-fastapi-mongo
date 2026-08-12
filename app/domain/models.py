"""Domain entities.

Plain Python: no Pydantic, no `bson.ObjectId`, no provider SDK types. MongoDB's
identifiers become `str` at the adapter boundary, so nothing above
`adapters/mongo/` needs to know that type exists.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime
    # Only ever set on assistant messages. Cheap to store and it makes a turn
    # explainable after the fact: which model answered, why it stopped.
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model: str | None = None
