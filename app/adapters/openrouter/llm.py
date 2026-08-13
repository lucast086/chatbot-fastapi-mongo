"""OpenRouterLLM: the LLMPort backed by OpenRouter.

OpenRouter exposes an OpenAI-compatible API, so this uses the OpenAI SDK pointed
at a different base URL rather than hand-rolled HTTP.

This adapter is the only place that knows the provider SDK's exception types.
Everything it can raise is translated into a `ProviderError` subclass here, which
is what keeps the error taxonomy in one place instead of spread across the
service and the router.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.domain.errors import (
    InvalidCredentialsError,
    MissingApiKeyError,
    ModelUnavailableError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import Chunk, Message, MessageRole

logger = logging.getLogger(__name__)

_RECOVERABLE_BY_ANOTHER_MODEL = (
    RateLimitedError,
    ModelUnavailableError,
    ProviderUnavailableError,
)


class OpenRouterLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        models: list[str],
        system_prompt: str,
        timeout_seconds: float,
        max_output_tokens: int,
        first_token_timeout_seconds: float = 20.0,
    ) -> None:
        """Build the client.

        SDK-level retries are disabled: retrying is the caller's decision, based
        on the `retryable` flag each error carries, and silent retries would
        multiply free-tier quota consumption behind its back.

        Args:
            models: Tried in order. Free models are rate limited per model, so a
                later one usually answers when an earlier one refuses.
            first_token_timeout_seconds: How long to wait for a model's first
                token before abandoning it for the next.
        """
        self._models = models
        self._system_prompt = system_prompt
        self._max_output_tokens = max_output_tokens
        self._first_token_timeout = first_token_timeout_seconds
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._configured = bool(api_key)

    async def aclose(self) -> None:
        """Release the shared HTTP connection pool."""
        await self._client.close()

    async def stream(self, messages: list[Message]) -> AsyncIterator[Chunk]:
        if not self._configured:
            raise MissingApiKeyError()

        last_error: ProviderError | None = None
        for index, model in enumerate(self._models):
            started = False
            try:
                async for chunk in self._stream_one(model, messages):
                    started = True
                    yield chunk
                return
            except _RECOVERABLE_BY_ANOTHER_MODEL as exc:
                if started:
                    raise
                last_error = exc
                remaining = len(self._models) - index - 1
                logger.warning(
                    "Model %s failed (%s). %s",
                    model,
                    exc.reason,
                    f"Trying the next of {remaining} remaining."
                    if remaining
                    else "No models left.",
                )

        if last_error is None:
            raise ProviderUnavailableError("no models are configured")
        raise last_error

    async def _stream_one(self, model: str, messages: list[Message]) -> AsyncIterator[Chunk]:
        """One model, no fallback.

        Raises before yielding anything when the model refuses the request,
        which is what lets the caller move on to the next one. Once a chunk has
        been yielded there is no going back — bytes are already on the wire —
        so a mid-stream failure propagates and becomes a failed turn.
        """
        saw_reasoning_only = False
        finish_reason: str | None = None
        started_at = time.monotonic()

        payload: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": self._system_prompt}
        ]
        for message in messages:
            if message.role is MessageRole.USER:
                payload.append({"role": "user", "content": message.content})
            else:
                payload.append({"role": "assistant", "content": message.content})

        try:
            async with await self._client.chat.completions.create(
                model=model,
                messages=payload,
                stream=True,
                max_tokens=self._max_output_tokens,
            ) as response:
                stream = response.__aiter__()
                first = True
                while True:
                    try:
                        if first:
                            chunk = await asyncio.wait_for(
                                anext(stream), timeout=self._first_token_timeout
                            )
                        else:
                            chunk = await anext(stream)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise ProviderUnavailableError(
                            f"{model} produced no output within {self._first_token_timeout:.0f}s"
                        ) from exc

                    if not chunk.choices:
                        continue
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                    delta = chunk.choices[0].delta
                    if delta.content:
                        if first:
                            logger.info(
                                "Model %s answered in %.1fs to first token",
                                model,
                                time.monotonic() - started_at,
                            )
                        first = False
                        yield Chunk(text=delta.content, model=model)
                    elif _reasoning_of(delta):
                        saw_reasoning_only = True
            if not first:
                yield Chunk(text="", model=model, finish_reason=finish_reason)

            if saw_reasoning_only and first:
                raise ModelUnavailableError(model, "it emitted only reasoning tokens and no answer")
        except openai.AuthenticationError as exc:
            raise InvalidCredentialsError() from exc
        except openai.PermissionDeniedError as exc:
            raise InvalidCredentialsError() from exc
        except openai.RateLimitError as exc:
            raise RateLimitedError(retry_after=_retry_after_from(exc)) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderUnavailableError("the request timed out") from exc
        except openai.APIStatusError as exc:
            logger.warning("Model provider returned %s: %s", exc.status_code, exc.message)
            if exc.status_code == 404:
                raise ModelUnavailableError(model, _provider_detail(exc)) from exc
            raise ProviderUnavailableError(f"the provider returned {exc.status_code}") from exc


def _reasoning_of(delta: object) -> str | None:
    """Reasoning tokens, under either of the two names providers use."""
    value = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
    return value if isinstance(value, str) else None


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

    def __init__(
        self, api_key: str, base_url: str, models: list[str], timeout_seconds: float
    ) -> None:
        self._models = models
        self._configured = bool(api_key)
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
            timeout=min(timeout_seconds, 15.0),
            max_retries=0,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def _first_model_that_answers(self, question: str, answer: str) -> Any:
        """Try each model in turn, returning the first response or None."""
        for model in self._models:
            try:
                return await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self._PROMPT},
                        {"role": "user", "content": f"User: {question}\n\nAssistant: {answer}"},
                    ],
                    max_tokens=24,
                )
            except Exception:
                continue
        return None

    async def suggest_title(self, question: str, answer: str) -> str | None:
        if not self._configured:
            return None
        try:
            response = await self._first_model_that_answers(question, answer)
        except Exception:
            logger.info("Could not generate a title; keeping the derived one.")
            return None

        if response is None:
            return None
        choices = response.choices
        if not choices or not choices[0].message.content:
            return None
        title = choices[0].message.content.strip().strip('"').strip()
        return title or None
