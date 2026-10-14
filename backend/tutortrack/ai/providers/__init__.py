"""The LLM provider in use: Anthropic Claude when configured, otherwise the fake.

``AI["PROVIDER"]`` = ``anthropic`` | ``fake``; empty picks anthropic when
``ANTHROPIC_API_KEY`` is set. Tests always get the fake (``config/settings/test.py``).
"""

from __future__ import annotations

from django.conf import settings

from .base import LLMProvider, LLMRequest, LLMResponse, ToolCall, Usage

__all__ = [
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "ToolCall",
    "Usage",
    "get_provider",
    "provider_name",
]

_cached: LLMProvider | None = None


def provider_name() -> str:
    configured = str(settings.AI.get("PROVIDER") or "").lower()
    if configured in ("anthropic", "fake"):
        return configured
    return "anthropic" if settings.AI.get("API_KEY") else "fake"


def get_provider() -> LLMProvider:
    global _cached
    name = provider_name()
    if _cached is not None and _cached.name == name:
        return _cached
    if name == "anthropic":
        from .claude import AnthropicProvider

        _cached = AnthropicProvider()
    else:
        from .fake import FakeLLMProvider

        _cached = FakeLLMProvider()
    return _cached


def reset() -> None:
    """Forget the cached provider (tests, settings changes)."""
    global _cached
    _cached = None
