"""Conversation endpoints.

Thin: parse, delegate, serialise. Errors are raised by the service as domain
errors and formatted once by the handlers in `api/errors.py`, so there is no
`HTTPException` in this file.
"""

from fastapi import APIRouter, Query, status

from app.api.schemas import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
)
from app.core.dependencies import ConversationServiceDep

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: CreateConversationRequest,
    service: ConversationServiceDep,
) -> ConversationSummary:
    conversation = await service.create(title=body.title)
    return ConversationSummary.from_domain(conversation)


@router.get("")
async def list_conversations(
    service: ConversationServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConversationSummary]:
    """The sidebar: most recently active first.

    A plain `limit` rather than cursor pagination. At the scale this is built
    for, the cursor would be machinery nobody exercises.
    """
    conversations = await service.list_recent(limit)
    return [ConversationSummary.from_domain(c) for c in conversations]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    service: ConversationServiceDep,
) -> ConversationDetail:
    conversation, messages = await service.get(conversation_id)
    return ConversationDetail.from_domain(conversation, messages)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    service: ConversationServiceDep,
) -> None:
    await service.delete(conversation_id)
