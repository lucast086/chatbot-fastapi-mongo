"""Domain errors translated into HTTP, in one place.

Every error response the API produces has the same four fields, including the
ones FastAPI would otherwise format its own way (`HTTPException` uses `detail`,
validation failures use a list of errors). One shape means the frontend has one
thing to parse and one field to branch on.

`docs_url` points at a README anchor named after the `reason`, so troubleshooting
lives in the document a reader already has open rather than in a separate page
nobody finds.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError, ProviderError

logger = logging.getLogger(__name__)

DOCS_BASE_URL = "https://github.com/lucast086/chatbot-fastapi-mongo#troubleshooting"

_STATUS_BY_REASON = {
    "not_found": 404,
    "validation_error": 422,
    "missing_api_key": 503,
    "invalid_credentials": 502,
    "model_unavailable": 502,
    "rate_limited": 429,
    "provider_unavailable": 504,
    "client_error": 400,
    "internal_error": 500,
}


def openapi_responses(*reasons: str) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` for the given error reasons.

    Applied per route so the documented contract matches what the handlers
    return, including the status codes the taxonomy exists to distinguish.
    """
    from app.api.schemas import ErrorResponse

    seen: dict[int | str, dict[str, Any]] = {}
    for reason in reasons:
        status = status_for(reason)
        existing = seen.get(status)
        if existing:
            existing["description"] += f" / {reason}"
            continue
        seen[status] = {"model": ErrorResponse, "description": reason}
    return seen


PROVIDER_REASONS = (
    "missing_api_key",
    "invalid_credentials",
    "rate_limited",
    "model_unavailable",
    "provider_unavailable",
)


def status_for(reason: str) -> int:
    """The HTTP status a domain reason maps to."""
    return _STATUS_BY_REASON.get(reason, 500)


def error_body(
    reason: str, message: str, retryable: bool, retry_after: int | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reason": reason,
        "message": message,
        "retryable": retryable,
        "docs_url": f"{DOCS_BASE_URL}-{reason.replace('_', '-')}",
    }
    if retry_after is not None:
        body["retry_after"] = retry_after
    return body


def error_response(
    reason: str,
    message: str,
    retryable: bool,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(reason, message, retryable),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        headers: dict[str, str] | None = None
        if isinstance(exc, ProviderError) and exc.retry_after is not None:
            headers = {"Retry-After": str(exc.retry_after)}

        return error_response(
            reason=exc.reason,
            message=str(exc),
            retryable=exc.retryable,
            status_code=status_for(exc.reason),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            reason="validation_error",
            message=_first_validation_message(exc),
            retryable=False,
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            reason = "not_found"
        elif exc.status_code < 500:
            reason = "client_error"
        else:
            reason = "internal_error"
        return error_response(
            reason=reason,
            message=str(exc.detail),
            retryable=False,
            status_code=exc.status_code,
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error while serving a request")
        return error_response(
            reason="internal_error",
            message="Something went wrong on our side.",
            retryable=False,
            status_code=500,
        )


def _first_validation_message(exc: RequestValidationError) -> str:
    """One readable sentence instead of Pydantic's nested error list.

    The full list is precise and unreadable in a toast notification. The first
    error is what the user has to fix first anyway.
    """
    errors = exc.errors()
    if not errors:
        return "The request body is invalid."
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "is invalid")
    return f"{location}: {message}" if location else message
