"""Domain entities.

Plain Python: no Pydantic, no `bson.ObjectId`, no provider SDK types. MongoDB's
identifiers become `str` at the adapter boundary, so nothing above
`adapters/mongo/` needs to know that type exists.
"""

from dataclasses import dataclass
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
    truncated: bool = False
    model: str | None = None


@dataclass(frozen=True)
class Chunk:
    """One fragment of a generated answer, and which model produced it.

    The model travels on the chunk rather than being asked of the adapter
    afterwards, because the adapter is a single process-wide instance shared by
    every request — instance state would be a race between concurrent turns.
    It also means the stored answer records the model that actually replied,
    which matters once more than one can.
    """

    text: str
    model: str
    finish_reason: str | None = None


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model: str | None = None
