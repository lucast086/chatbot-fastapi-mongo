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
from app.domain.ports import ConversationStorePort, LLMPort, TitleGeneratorPort
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db(request: Request) -> AsyncDatabase[dict[str, Any]]:
    db: AsyncDatabase[dict[str, Any]] = request.app.state.mongo_db
    return db


DbDep = Annotated[AsyncDatabase[dict[str, Any]], Depends(get_db)]


def get_conversation_store(db: DbDep) -> ConversationStorePort:
    return MongoConversationStore(db)


ConversationStoreDep = Annotated[ConversationStorePort, Depends(get_conversation_store)]


def get_conversation_service(store: ConversationStoreDep) -> ConversationService:
    return ConversationService(store)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


def get_llm(request: Request) -> LLMPort:
    llm: LLMPort = request.app.state.llm
    return llm


LLMDep = Annotated[LLMPort, Depends(get_llm)]


def get_title_generator(request: Request) -> TitleGeneratorPort:
    titles: TitleGeneratorPort = request.app.state.title_generator
    return titles


TitleGeneratorDep = Annotated[TitleGeneratorPort, Depends(get_title_generator)]


def get_chat_service(
    store: ConversationStoreDep,
    llm: LLMDep,
    titles: TitleGeneratorDep,
    settings: SettingsDep,
) -> ChatService:
    return ChatService(
        store=store,
        llm=llm,
        history_limit=settings.history_limit,
        max_message_length=settings.max_message_length,
        max_history_chars=settings.max_history_chars,
        titles=titles if settings.generate_titles else None,
        provider_configured=settings.provider_configured,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
