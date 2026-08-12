"""The wiring layer: the only module that imports both `domain/ports` and
`adapters/`, and decides which concrete adapter backs each port.

Everything here is a FastAPI dependency. Services and the domain never see
`Depends` — that is what keeps them usable (and testable) outside a web request.
"""

from typing import Annotated, Any

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.mongo.conversation_store import MongoConversationStore
from app.core.config import Settings, get_settings
from app.domain.ports import ConversationStorePort

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db(request: Request) -> AsyncDatabase[dict[str, Any]]:
    # Created once in the lifespan, not per request: a connection pool is meant
    # to be shared for the lifetime of the process.
    db: AsyncDatabase[dict[str, Any]] = request.app.state.mongo_db
    return db


DbDep = Annotated[AsyncDatabase[dict[str, Any]], Depends(get_db)]


def get_conversation_store(db: DbDep) -> ConversationStorePort:
    return MongoConversationStore(db)


ConversationStoreDep = Annotated[ConversationStorePort, Depends(get_conversation_store)]
