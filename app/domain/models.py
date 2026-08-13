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
    # True when the provider stopped at the output cap rather than finishing.
    # Stored because a cut-off answer is otherwise indistinguishable from a
    # complete one, for the reader and for anyone debugging later.
    truncated: bool = False
    # Only ever set on assistant messages: which model produced this answer.
    # Useful when the configured model changes between sessions, which on a
    # rotating free tier it does.
    #
    # `finish_reason` and token `usage` were here too and are gone. A port
    # typed `AsyncIterator[str]` has nowhere to return them, so nothing ever
    # populated them and they were furniture — three fields promising an
    # explainability the code did not deliver. Carrying them properly means a
    # terminal metadata frame on the port; that is the honest next step, listed
    # in the README rather than faked here.
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
    # Set on the final chunk only. "length" means the provider stopped at the
    # output cap, so the answer is cut off mid-thought — indistinguishable from
    # a complete one without this.
    finish_reason: str | None = None


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model: str | None = None
