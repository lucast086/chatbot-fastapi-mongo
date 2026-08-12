"""Shared fixtures.

MongoDB is real here rather than faked. It is deterministic, free and offline in
a container, so faking it would buy nothing while hiding exactly the bugs an
adapter can have: wrong query syntax, an index that is not used, dates that come
back in an unexpected type.

Integration tests are skipped rather than failed when MongoDB is not running, so
`uv run pytest` still works on a machine with nothing started. `scripts/test.sh`
brings the container up first.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.mongo.connection import ensure_indexes

TEST_MONGO_URI = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017")
TEST_DB_NAME = "chatbot_test"


@pytest.fixture
async def mongo_db() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        TEST_MONGO_URI, serverSelectionTimeoutMS=2000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception:
        await client.close()
        pytest.skip("MongoDB is not reachable; start it with scripts/test.sh")

    db = client[TEST_DB_NAME]
    # A dedicated database, wiped before and after, so a run never depends on
    # what a previous run left behind.
    await _drop_collections(db)
    await ensure_indexes(db)
    try:
        yield db
    finally:
        await _drop_collections(db)
        await client.close()


async def _drop_collections(db: AsyncDatabase[dict[str, Any]]) -> None:
    await db.conversations.delete_many({})
    await db.messages.delete_many({})
