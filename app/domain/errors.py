"""Domain errors.

Services raise these; they never raise `HTTPException`, which would leak an HTTP
concept into a layer that does not know HTTP exists. The translation to a status
code happens once, in `api/exception_handlers.py`.

Every error carries the three fields the API's error envelope needs — `reason`,
`message`, `retryable` — so the handler formats rather than decides. The mapping
from `reason` to a status code lives in the API layer, because a status code is
an HTTP concept.
"""


class DomainError(Exception):
    """Base class for every exception a service is allowed to raise."""

    reason: str = "internal_error"
    retryable: bool = False


class NotFoundError(DomainError):
    """A lookup by id found nothing.

    Parameterised by entity name rather than one subclass per entity: the
    handling is identical every time — 404 — so a subclass per entity would be
    empty boilerplate repeated for each new one.
    """

    reason = "not_found"

    def __init__(self, entity: str, entity_id: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} '{entity_id}' was not found.")


class ValidationError(DomainError):
    """Input the domain refuses, as opposed to input the schema refuses."""

    reason = "validation_error"


# ---------------------------------------------------------------------------
# Model provider
#
# Four distinct outcomes rather than one generic failure. The backend already
# knows which one happened, and two of the four are worth retrying while the
# other two are not — collapsing them would throw that away and leave the client
# guessing.
# ---------------------------------------------------------------------------
class ProviderError(DomainError):
    """Base class for anything that went wrong talking to the model provider."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class MissingApiKeyError(ProviderError):
    """No API key is configured. Expected on a fresh clone, not a bug."""

    reason = "missing_api_key"
    retryable = False

    def __init__(self) -> None:
        super().__init__(
            "No model provider API key is configured, so messages cannot be answered. "
            "Everything else works. See the README for how to obtain and set one."
        )


class InvalidCredentialsError(ProviderError):
    """The provider rejected the key. Retrying will not help."""

    reason = "invalid_credentials"
    retryable = False

    def __init__(self) -> None:
        super().__init__(
            "The model provider rejected the configured API key. "
            "Check that it is correct and still active."
        )


class RateLimitedError(ProviderError):
    """The provider is throttling us. Free-tier models do this routinely."""

    reason = "rate_limited"
    retryable = True

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__(
            "The model provider is rate limiting requests. Try again shortly.",
            retry_after=retry_after,
        )


class ProviderUnavailableError(ProviderError):
    """A timeout, a connection failure, or an error on the provider's side."""

    reason = "provider_unavailable"
    retryable = True

    def __init__(self, detail: str | None = None) -> None:
        message = "The model provider is unavailable right now. Try again in a moment."
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)
