"""LLMPort: a conversation in, generated text out, one chunk at a time.

A single streaming method, decided on the first day rather than added later. The
JSON endpoint consumes the whole generator and joins it, so the non-streaming
path is the one that is tested and shipped, while adding server-sent events
later is a new endpoint rather than a signature change reaching down through the
service layer.

Implementations raise `ProviderError` subclasses from `domain/errors.py`. They
never raise the provider SDK's own exception types: translating them is the
adapter's job, which is what keeps the taxonomy in one place.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from app.domain.models import Message


class LLMPort(Protocol):
    def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Yield the answer in fragments, in order.

        `messages` is the full prompt context: the history window the service
        chose, oldest first. The system prompt is not part of it — the adapter
        owns how that is attached, because the shape differs per provider.
        """
        ...
