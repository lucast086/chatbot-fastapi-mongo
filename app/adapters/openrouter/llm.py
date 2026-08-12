"""OpenRouterLLM: the LLMPort backed by OpenRouter.

OpenRouter exposes an OpenAI-compatible API, so this uses the OpenAI SDK pointed
at a different base URL rather than hand-rolled HTTP.

This adapter is the only place that knows the provider SDK's exception types.
Everything it can raise is translated into a `ProviderError` subclass here, which
is what keeps the error taxonomy in one place instead of spread across the
service and the router.
"""

import logging
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.domain.errors import (
    InvalidCredentialsError,
    MissingApiKeyError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import Message, MessageRole

logger = logging.getLogger(__name__)


class OpenRouterLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        system_prompt: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt
        # The SDK refuses to construct with an empty key, and there is nothing
        # to construct it for: the service checks `MissingApiKeyError` before
        # reaching this adapter. The placeholder keeps the object creatable so
        # dependency wiring does not have to branch.
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # Retries are the caller's decision, based on `retryable`.
        )
        self._configured = bool(api_key)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        if not self._configured:
            raise MissingApiKeyError()

        # Built role by role rather than from `m.role.value`, which is a plain
        # str: the SDK types each role as a Literal. Suppressing that mismatch
        # instead would also defeat overload resolution on `stream`, turning the
        # return type into a union that needs a second suppression. Two silenced
        # errors to avoid four explicit lines is a bad trade.
        payload: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": self._system_prompt}
        ]
        for message in messages:
            if message.role is MessageRole.USER:
                payload.append({"role": "user", "content": message.content})
            else:
                payload.append({"role": "assistant", "content": message.content})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=payload,
                stream=True,
            )
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except openai.AuthenticationError as exc:
            raise InvalidCredentialsError() from exc
        except openai.PermissionDeniedError as exc:
            # A valid key without access to this model. Same remedy as a bad
            # key from the caller's point of view: fix the configuration.
            raise InvalidCredentialsError() from exc
        except openai.RateLimitError as exc:
            raise RateLimitedError(retry_after=_retry_after_from(exc)) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderUnavailableError("the request timed out") from exc
        except openai.APIStatusError as exc:
            logger.warning("Model provider returned %s: %s", exc.status_code, exc.message)
            # 404 means the model name is wrong or has stopped being free.
            # Kept separate from the 5xx case because waiting cannot fix it,
            # and this was found by the live test rather than reasoned about:
            # the default model shipped in this repo had already been retired.
            if exc.status_code == 404:
                raise ModelUnavailableError(self._model, _provider_detail(exc)) from exc
            raise ProviderUnavailableError(f"the provider returned {exc.status_code}") from exc


def _retry_after_from(exc: openai.RateLimitError) -> int | None:
    """Pass the provider's own backoff through when it sent one.

    Inventing a number would be worse than omitting the header: the client would
    treat a guess as authoritative.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        # The header also allows an HTTP date. Parsing that for a value we can
        # do without is not worth the code.
        return None


def _provider_detail(exc: openai.APIStatusError) -> str | None:
    """The provider's own explanation, when the body carries one.

    OpenRouter's 404 for a retired model names the replacement slug, which is
    the single most useful thing to put in front of whoever has to fix it.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
    return None


class OpenRouterTitleGenerator:
    """Names a conversation from its first exchange.

    A separate class from OpenRouterLLM rather than another method on it: the
    chat port is what the turn depends on, and this is a nicety that must never
    be able to fail a turn. Keeping them apart makes that hard to get wrong.
    """

    _PROMPT = (
        "Summarise this exchange as a conversation title of at most six words. "
        "Reply with the title only: no quotes, no punctuation at the end, no preamble."
    )

    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        self._model = model
        self._configured = bool(api_key)
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
            # Much shorter than the chat timeout: nobody waits on a title, and a
            # slow one should be abandoned rather than delay the response.
            timeout=min(timeout_seconds, 15.0),
            max_retries=0,
        )

    async def suggest_title(self, question: str, answer: str) -> str | None:
        if not self._configured:
            return None
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._PROMPT},
                    {"role": "user", "content": f"User: {question}\n\nAssistant: {answer}"},
                ],
                max_tokens=24,
            )
        except Exception:
            # Every failure is swallowed on purpose. The turn has already been
            # answered and stored; the fallback title is already in place. There
            # is nothing here worth surfacing to the user.
            logger.info("Could not generate a title; keeping the derived one.")
            return None

        choices = response.choices
        if not choices or not choices[0].message.content:
            return None
        title = choices[0].message.content.strip().strip('"').strip()
        return title or None
