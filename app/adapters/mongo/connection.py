"""MongoDB connection and index setup.

Called once from the FastAPI lifespan, not from a request dependency: creating
indexes is a startup side effect. Doing it per request would be wasteful and
racy under concurrency.
"""

from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

_SERVER_SELECTION_TIMEOUT_MS = 3000


def create_client(mongo_uri: str) -> AsyncMongoClient[dict[str, Any]]:
    """Build the shared MongoDB client.

    Server selection is capped well below the driver's 30 second default so an
    unreachable database fails the readiness probe instead of hanging it.

    Args:
        mongo_uri: Connection string, credentials included if any.

    Returns:
        A client whose datetimes are timezone-aware.
    """
    return AsyncMongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
        tz_aware=True,
    )


async def ensure_indexes(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Create the indexes the queries rely on.

    Idempotent: `create_index` is a no-op when the index already exists, so this
    is safe to run on every startup.
    """
    await db.messages.create_index([("conversation_id", 1), ("created_at", 1)])
    await db.conversations.create_index([("updated_at", -1)])
