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
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.errors import error_body, error_response, status_for
from app.core.dependencies import ChatServiceDep
from app.domain.errors import DomainError

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _event(name: str, payload: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


# response_model=None because this route answers with either a stream or a JSON
# error, and FastAPI cannot build one response model from that union.
@router.post("/{conversation_id}/messages/stream", response_model=None)
async def stream_message(
    conversation_id: str,
    body: dict[str, str],
    service: ChatServiceDep,
) -> StreamingResponse | JSONResponse:
    content = (body.get("content") or "").strip()

    # Pre-flight. Everything checkable without calling the model is checked
    # here, while a real status code is still possible.
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
        collected: list[str] = []
        try:
            async for chunk in service.stream_turn(prepared):
                collected.append(chunk)
                yield _event("chunk", {"content": chunk})
            # Persisted only once the stream has completed, which is what keeps
            # the atomic-turn guarantee: a generation that fails part-way leaves
            # nothing behind, exactly as on the JSON route. The cost is that a
            # client disconnecting mid-stream loses that turn.
            _, assistant_message, conversation = await service.finish_turn(
                prepared, "".join(collected)
            )
        except DomainError as exc:
            # The status line is long gone, so the error travels in-band with
            # the same shape the JSON route would have returned.
            yield _event("error", error_body(exc.reason, str(exc), exc.retryable))
            return
        yield _event(
            "done",
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "user_message_id": prepared.user_message.id,
                "assistant_message_id": assistant_message.id,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells nginx not to buffer even if the config ever changes; without
            # it a buffered proxy delivers the whole stream at the end, which is
            # indistinguishable from not streaming at all.
            "X-Accel-Buffering": "no",
        },
    )
