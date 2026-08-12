"""The wiring layer: the only module that imports both `domain/ports` and
`adapters/`, and decides which concrete adapter backs each port.

Everything here is a FastAPI dependency. Services and the domain never see
`Depends` — that is what keeps them usable (and testable) outside a web request.
"""

from typing import Annotated, Any

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.mongo.conversation_store import MongoConversationStore
from app.adapters.openrouter.llm import OpenRouterLLM, OpenRouterTitleGenerator
from app.core.config import Settings, get_settings
from app.domain.ports import ConversationStorePort, LLMPort, TitleGeneratorPort
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService

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


def get_conversation_service(store: ConversationStoreDep) -> ConversationService:
    return ConversationService(store)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


def get_llm(settings: SettingsDep) -> LLMPort:
    # There is no fake branch here. In a chatbot the generation is the product,
    # so a runtime fake would make the app look like it works while hiding
    # whether the real integration does. The double lives in tests only.
    return OpenRouterLLM(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        system_prompt=settings.system_prompt,
        timeout_seconds=settings.request_timeout_seconds,
    )


LLMDep = Annotated[LLMPort, Depends(get_llm)]


def get_title_generator(settings: SettingsDep) -> TitleGeneratorPort:
    return OpenRouterTitleGenerator(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_seconds=settings.request_timeout_seconds,
    )


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
        titles=titles if settings.generate_titles else None,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
