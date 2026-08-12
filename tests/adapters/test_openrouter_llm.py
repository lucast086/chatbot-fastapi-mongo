"""OpenRouterLLM error translation.

What matters here is that every provider failure becomes the right domain error,
because that mapping is what the whole error taxonomy rests on. The SDK
exceptions are constructed directly rather than provoked over the network: these
tests must not need a key, a connection or quota.

The one test that does talk to the real provider is marked `live` and skipped
unless a key is present.
"""

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.adapters.openrouter.llm import OpenRouterLLM
from app.domain.errors import (
    InvalidCredentialsError,
    MissingApiKeyError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import Message, MessageRole


def _messages() -> list[Message]:
    return [
        Message(
            id="m1",
            conversation_id="c1",
            role=MessageRole.USER,
            content="hello",
            created_at=datetime.now(UTC),
        )
    ]


def _adapter(api_key: str = "sk-test") -> OpenRouterLLM:
    return OpenRouterLLM(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        models=["test/model"],
        system_prompt="You are helpful.",
        timeout_seconds=5.0,
        max_output_tokens=256,
    )


def _response(status_code: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


async def _consume(adapter: OpenRouterLLM) -> str:
    return "".join([chunk.text async for chunk in adapter.stream(_messages())])


async def test_no_api_key_raises_missing_api_key_without_calling_the_provider() -> None:
    with pytest.raises(MissingApiKeyError) as caught:
        await _consume(_adapter(api_key=""))

    assert caught.value.reason == "missing_api_key"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (
            openai.AuthenticationError("bad key", response=_response(401), body=None),
            InvalidCredentialsError,
        ),
        (
            openai.PermissionDeniedError("no access to model", response=_response(403), body=None),
            InvalidCredentialsError,
        ),
        (
            openai.RateLimitError("slow down", response=_response(429), body=None),
            RateLimitedError,
        ),
        (
            openai.APITimeoutError(
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            ),
            ProviderUnavailableError,
        ),
        (
            openai.APIStatusError("upstream is down", response=_response(503), body=None),
            ProviderUnavailableError,
        ),
    ],
)
async def test_provider_failures_become_the_right_domain_error(
    monkeypatch: pytest.MonkeyPatch, sdk_error: Exception, expected: type[Exception]
) -> None:
    adapter = _adapter()

    async def raise_it(**_kwargs: Any) -> None:
        raise sdk_error

    monkeypatch.setattr(adapter._client.chat.completions, "create", raise_it)

    with pytest.raises(expected):
        await _consume(adapter)


async def test_a_rate_limit_passes_the_providers_own_retry_after_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter()

    async def raise_it(**_kwargs: Any) -> None:
        raise openai.RateLimitError(
            "slow down", response=_response(429, {"retry-after": "42"}), body=None
        )

    monkeypatch.setattr(adapter._client.chat.completions, "create", raise_it)

    with pytest.raises(RateLimitedError) as caught:
        await _consume(adapter)

    assert caught.value.retry_after == 42
    assert caught.value.retryable is True


async def test_a_retired_model_is_reported_as_a_configuration_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for a real failure the live test found.

    The default model shipped in this repository had already stopped being free.
    OpenRouter answers 404, which was being folded into `provider_unavailable`
    and therefore told the caller to retry — advice that can never work. It has
    to be non-retryable, and it has to name the model.
    """
    adapter = _adapter()

    async def raise_it(**_kwargs: Any) -> None:
        raise openai.APIStatusError(
            "not found",
            response=_response(404),
            body={
                "error": {
                    "message": "This model is unavailable for free. "
                    "The paid version is available now - use this slug instead: some/model"
                }
            },
        )

    monkeypatch.setattr(adapter._client.chat.completions, "create", raise_it)

    with pytest.raises(ModelUnavailableError) as caught:
        await _consume(adapter)

    assert caught.value.retryable is False
    assert "test/model" in str(caught.value)
    # The provider names the replacement slug; passing it through is the most
    # useful thing we can put in front of whoever has to fix the configuration.
    assert "use this slug instead" in str(caught.value)


async def test_an_unparseable_retry_after_is_omitted_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter()

    async def raise_it(**_kwargs: Any) -> None:
        # The header also allows an HTTP date, which we do not parse.
        raise openai.RateLimitError(
            "slow down",
            response=_response(429, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            body=None,
        )

    monkeypatch.setattr(adapter._client.chat.completions, "create", raise_it)

    with pytest.raises(RateLimitedError) as caught:
        await _consume(adapter)

    assert caught.value.retry_after is None


@pytest.mark.live
@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="needs a real OPENROUTER_API_KEY",
)
async def test_live_the_configured_model_actually_answers() -> None:
    """The only test that proves the integration works end to end.

    Everything above verifies our own translation logic against constructed SDK
    errors, which cannot catch a wrong request shape, a response parsed
    incorrectly, or a model name that has been retired. Excluded from CI on
    purpose: the suite must not depend on a network, a key or free-tier quota.
    """
    adapter = OpenRouterLLM(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        models=os.getenv("OPENROUTER_MODELS", "google/gemma-4-31b-it:free").split(","),
        system_prompt="Answer with a single word.",
        timeout_seconds=60.0,
        max_output_tokens=64,
    )

    answer = "".join(
        [
            chunk.text
            async for chunk in adapter.stream(
                [
                    Message(
                        id="m1",
                        conversation_id="c1",
                        role=MessageRole.USER,
                        content="Reply with exactly the word: pong",
                        created_at=datetime.now(UTC),
                    )
                ]
            )
        ]
    )

    assert answer.strip(), "the provider returned an empty answer"


# ---------------------------------------------------------------------------
# Falling back between models
#
# `:free` models are rate limited per model, so when the first says 429 the
# next is usually free to answer. What these pin down is the boundary: which
# failures move on, which do not, and that a fallback never hides which model
# actually replied.
# ---------------------------------------------------------------------------


def _multi(*models: str) -> OpenRouterLLM:
    return OpenRouterLLM(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        models=list(models),
        system_prompt="You are helpful.",
        timeout_seconds=5.0,
        max_output_tokens=256,
    )


class _ScriptedProvider:
    """Answers per model: an exception to raise, or text to stream back."""

    def __init__(self, script: dict[str, object]) -> None:
        self._script = script
        self.calls: list[str] = []

    async def create(self, *, model: str, **_kwargs: Any) -> Any:
        self.calls.append(model)
        outcome = self._script[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeStream(str(outcome))


class _FakeStream:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def __aiter__(self) -> Any:
        for word in self._text.split(" "):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=word + " "))]
            )


def _script(adapter: OpenRouterLLM, script: dict[str, object]) -> _ScriptedProvider:
    provider = _ScriptedProvider(script)
    adapter._client.chat.completions.create = provider.create  # type: ignore[method-assign]
    return provider


async def test_a_rate_limited_model_falls_back_to_the_next() -> None:
    adapter = _multi("first/model", "second/model")
    provider = _script(
        adapter,
        {
            "first/model": openai.RateLimitError("slow down", response=_response(429), body=None),
            "second/model": "an answer",
        },
    )

    chunks = [c async for c in adapter.stream(_messages())]

    assert "".join(c.text for c in chunks).strip() == "an answer"
    # The chunk names the model that actually replied, not the configured first.
    assert {c.model for c in chunks} == {"second/model"}
    assert provider.calls == ["first/model", "second/model"]


async def test_a_retired_model_is_skipped() -> None:
    """A hardcoded list rots as free models are retired. Treating the 404 as a
    reason to move on is what stops that rot from breaking the app."""
    adapter = _multi("retired/model", "live/model")
    provider = _script(
        adapter,
        {
            "retired/model": openai.APIStatusError("not found", response=_response(404), body=None),
            "live/model": "still here",
        },
    )

    chunks = [c async for c in adapter.stream(_messages())]

    assert "".join(c.text for c in chunks).strip() == "still here"
    assert provider.calls == ["retired/model", "live/model"]


async def test_all_models_failing_reports_the_last_error() -> None:
    adapter = _multi("a/one", "b/two", "c/three")
    provider = _script(
        adapter,
        {
            m: openai.RateLimitError("slow down", response=_response(429), body=None)
            for m in ("a/one", "b/two", "c/three")
        },
    )

    with pytest.raises(RateLimitedError):
        await _consume(adapter)

    assert provider.calls == ["a/one", "b/two", "c/three"]


async def test_invalid_credentials_does_not_try_the_other_models() -> None:
    """The guard against the fallback degenerating into "retry everything". It
    is the same key for every model, so the rest can only fail the same way."""
    adapter = _multi("a/one", "b/two", "c/three")
    provider = _script(
        adapter,
        {"a/one": openai.AuthenticationError("bad key", response=_response(401), body=None)},
    )

    with pytest.raises(InvalidCredentialsError):
        await _consume(adapter)

    assert provider.calls == ["a/one"]


async def test_no_fallback_once_the_stream_has_started() -> None:
    """Bytes already on the wire cannot be rewound, so a mid-stream failure is
    a failed turn rather than a reason to start over on another model."""

    class _FailsMidStream(_FakeStream):
        async def __aiter__(self) -> Any:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="par"))])
            raise openai.RateLimitError("slow down", response=_response(429), body=None)

    adapter = _multi("first/model", "second/model")
    provider = _ScriptedProvider({})

    async def create(*, model: str, **_kwargs: Any) -> Any:
        provider.calls.append(model)
        return _FailsMidStream("")

    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    with pytest.raises(RateLimitedError):
        await _consume(adapter)

    assert provider.calls == ["first/model"]


async def test_a_model_that_goes_quiet_is_abandoned_and_the_next_is_tried() -> None:
    """A model that accepts the request and then produces nothing would hold the
    UI on "Thinking…" for the whole request timeout, which reads as a frozen
    app. Nothing has been yielded yet, so abandoning it is free."""

    class _NeverYields(_FakeStream):
        async def __aiter__(self) -> Any:
            await asyncio.sleep(10)
            yield SimpleNamespace(choices=[])

    adapter = OpenRouterLLM(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        models=["silent/model", "talkative/model"],
        system_prompt="You are helpful.",
        timeout_seconds=60.0,
        max_output_tokens=256,
        first_token_timeout_seconds=0.05,
    )
    calls: list[str] = []

    async def create(*, model: str, **_kwargs: Any) -> Any:
        calls.append(model)
        return _NeverYields("") if model == "silent/model" else _FakeStream("here I am")

    adapter._client.chat.completions.create = create  # type: ignore[method-assign]

    chunks = [c async for c in adapter.stream(_messages())]

    assert "".join(c.text for c in chunks).strip() == "here I am"
    assert calls == ["silent/model", "talkative/model"]
