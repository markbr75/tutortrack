"""Provider-neutral request/response types (the ``LLMProvider`` interface, E31 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Tier = Literal["default", "fast"]
Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


@dataclass
class LLMRequest:
    """One model call. ``system`` must be stable per prompt version (it is cached);
    per-request context goes in ``messages``. ``prompt`` names the prompt for logs and
    for the fake provider."""

    prompt: str
    tier: Tier
    system: str
    messages: list[dict[str, Any]]
    max_tokens: int
    effort: Effort
    tools: list[dict[str, Any]] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    text: str
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal | pause_turn | ...
    usage: Usage
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant turn as content blocks, replayed unchanged in a tool loop (thinking
    # blocks included, as the API requires).
    content: list[dict[str, Any]] = field(default_factory=list)
    request_id: str = ""
    fallback_used: bool = False
    refusal_category: str | None = None


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def model_for(self, tier: Tier) -> str: ...
