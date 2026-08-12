"""MongoDB connection and index setup.

Called once from the FastAPI lifespan, not from a request dependency: creating
indexes is a startup side effect. Doing it per request would be wasteful and
racy under concurrency.
"""

from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

# Short on purpose. The default is 30 seconds, which would make the readiness
# probe hang instead of reporting that MongoDB is unreachable.
_SERVER_SELECTION_TIMEOUT_MS = 3000


def create_client(mongo_uri: str) -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
        tz_aware=True,
    )


async def ensure_indexes(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Idempotent: `create_index` is a no-op when the index already exists."""
    # Serves both reads of a conversation's messages: the full history in
    # ascending order, and the most recent N for the prompt window. One index
    # covers both directions, so a second one would earn nothing.
    await db.messages.create_index([("conversation_id", 1), ("created_at", 1)])
    # The sidebar: most recently active conversation first.
    await db.conversations.create_index([("updated_at", -1)])
