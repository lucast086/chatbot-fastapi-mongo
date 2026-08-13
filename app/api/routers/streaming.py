"""The streaming variant of sending a message.

A separate route rather than content negotiation on `Accept`: OpenAPI cannot
express two media types for one operation without lying about it in the docs,
and the README's curl example would need an extra header for the ordinary case.
The JSON route stays the tested, documented one.

The hard constraint here is that the HTTP status is sent the moment the stream
opens. So everything that can be known beforehand — a missing key, an unknown
conversation, an invalid message — is checked *before* opening it and still
comes back as a real status code with the usual envelope. Only a failure that
happens mid-generation becomes an SSE `error` event, carrying the same four
fields so the frontend handles both paths with one piece of code.
"""

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.errors import (
    PROVIDER_REASONS,
    error_body,
    error_response,
    openapi_responses,
    status_for,
)
from app.api.schemas import SendMessageRequest
from app.core.dependencies import ChatServiceDep
from app.domain.errors import DomainError
from app.domain.models import Chunk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _event(name: str, payload: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@router.post(
    "/{conversation_id}/messages/stream",
    response_model=None,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "chunk / done / error events",
        },
        **openapi_responses("not_found", "validation_error", *PROVIDER_REASONS),
    },
)
async def stream_message(
    conversation_id: str,
    body: SendMessageRequest,
    service: ChatServiceDep,
) -> StreamingResponse | JSONResponse:
    content = body.content

    try:
        prepared = await service.prepare_turn(conversation_id, content)
    except DomainError as exc:
        return error_response(
            reason=exc.reason,
            message=str(exc),
            retryable=exc.retryable,
            status_code=status_for(exc.reason),
        )

    async def events() -> AsyncIterator[str]:
        collected: list[Chunk] = []
        try:
            async for chunk in service.stream_turn(prepared):
                collected.append(chunk)
                yield _event("chunk", {"content": chunk.text})
            _, assistant_message, conversation = await service.finish_turn(prepared, collected)
        except DomainError as exc:
            retry_after = getattr(exc, "retry_after", None)
            yield _event("error", error_body(exc.reason, str(exc), exc.retryable, retry_after))
            return
        except Exception:
            logger.exception("Unhandled error while streaming a turn")
            yield _event(
                "error",
                error_body("internal_error", "Something went wrong on our side.", False),
            )
            return
        yield _event(
            "done",
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "user_message_id": prepared.user_message.id,
                "assistant_message_id": assistant_message.id,
                "model": assistant_message.model,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
