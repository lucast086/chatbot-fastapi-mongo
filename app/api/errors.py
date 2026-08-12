"""Domain errors translated into HTTP, in one place.

Every error response the API produces has the same four fields, including the
ones FastAPI would otherwise format its own way (`HTTPException` uses `detail`,
validation failures use a list of errors). One shape means the frontend has one
thing to parse and one field to branch on.

`docs_url` points at a README anchor named after the `reason`, so troubleshooting
lives in the document a reader already has open rather than in a separate page
nobody finds.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError, ProviderError

DOCS_BASE_URL = "https://github.com/lucast086/chatbot-fastapi-mongo#troubleshooting"

# A status code is an HTTP concept, so the mapping lives here rather than on the
# domain error. Timeouts and outages are 504 and 502 respectively upstream, but
# both surface as provider_unavailable; 504 is the more accurate of the two for
# the common case and the message carries the detail.
_STATUS_BY_REASON = {
    "not_found": 404,
    "validation_error": 422,
    "missing_api_key": 503,
    "invalid_credentials": 502,
    "rate_limited": 429,
    "provider_unavailable": 504,
    "internal_error": 500,
}


def error_body(reason: str, message: str, retryable: bool) -> dict[str, Any]:
    return {
        "reason": reason,
        "message": message,
        "retryable": retryable,
        "docs_url": f"{DOCS_BASE_URL}-{reason.replace('_', '-')}",
    }


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
        # Only meaningful when the provider told us how long to wait. Inventing
        # a value would be worse than omitting the header.
        if isinstance(exc, ProviderError) and exc.retry_after is not None:
            headers = {"Retry-After": str(exc.retry_after)}

        return error_response(
            reason=exc.reason,
            message=str(exc),
            retryable=exc.retryable,
            status_code=_STATUS_BY_REASON.get(exc.reason, 500),
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
        # Mostly 404s for unknown routes and 405s for the wrong verb. Without
        # this, those two would be the only responses in the API with a
        # different shape.
        reason = "not_found" if exc.status_code == 404 else "internal_error"
        return error_response(
            reason=reason,
            message=str(exc.detail),
            retryable=False,
            status_code=exc.status_code,
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
