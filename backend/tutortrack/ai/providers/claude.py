"""Anthropic Claude through the official ``anthropic`` SDK (ADR 0029).

* Models from ``settings.AI``: ``claude-opus-5-5`` (default tier: drafting, copilot,
  command bar) and ``claude-haiku-5-5`` (fast tier: classification, extraction, summaries).
* Thinking is always adaptive (Opus 5.5 cannot disable it); cost and latency are set per
  prompt with ``output_config.effort``. No temperature, no budget_tokens, no prefill.
* Tools are ``strict`` with ``tool_choice`` auto (forced tool choice is a 400 on Opus 5.5);
  extraction uses structured outputs (``output_config.format``).
* The stable system prompt carries a ``cache_control`` breakpoint, which caches the tool
  list too (tools render before system).
* Opus requests opt into server-side refusal fallbacks (``fallbacks="default"`` behind
  the ``server-side-fallback-2026-07-01`` beta); Haiku has no server-side fallback.
* SDK exceptions become RFC 7807 problems (``tutortrack.ai.exceptions``). Nothing about
  the prompt is logged, only status codes and the provider request id.
"""

from __future__ import annotations

from typing import Any

import anthropic
import structlog
from django.conf import settings

from ..exceptions import AIProviderError, AIRateLimited, AIUnavailable
from .base import LLMRequest, LLMResponse, Tier, ToolCall, Usage

logger = structlog.get_logger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Blocks we never echo back in a tool loop: the fallback switch marker is an audit-only
# block (keeping or dropping it is allowed).
_SKIP_ECHO = {"fallback"}


def _retry_after(exc: anthropic.APIStatusError) -> int:
    try:
        return max(1, int(exc.response.headers.get("retry-after", "30")))
    except (TypeError, ValueError):
        return 30


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(
            api_key=settings.AI["API_KEY"] or None,
            timeout=float(settings.AI["TIMEOUT_SECONDS"]),
            max_retries=int(settings.AI["MAX_RETRIES"]),
        )

    def model_for(self, tier: Tier) -> str:
        return str(settings.AI["MODEL_FAST" if tier == "fast" else "MODEL_DEFAULT"])

    def _kwargs(self, request: LLMRequest) -> dict[str, Any]:
        output_config: dict[str, Any] = {"effort": request.effort}
        if request.output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.output_schema}
        kwargs: dict[str, Any] = {
            "model": self.model_for(request.tier),
            "max_tokens": request.max_tokens,
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": request.messages,
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if request.tools:
            kwargs["tools"] = [
                {**tool, "strict": True} for tool in sorted(request.tools, key=lambda t: t["name"])
            ]
            kwargs["tool_choice"] = {"type": "auto"}
        if request.tier == "default" and settings.AI.get("FALLBACKS", True):
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            message = self.client.beta.messages.create(**self._kwargs(request))
        except anthropic.RateLimitError as exc:
            logger.warning("ai.provider_rate_limited", prompt=request.prompt)
            raise AIRateLimited(retry_after=_retry_after(exc)) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            logger.warning("ai.provider_unreachable", prompt=request.prompt)
            raise AIUnavailable() from exc
        except anthropic.APIStatusError as exc:
            logger.warning(
                "ai.provider_error",
                prompt=request.prompt,
                status=exc.status_code,
                request_id=exc.request_id,
            )
            if exc.status_code >= 500:
                raise AIUnavailable() from exc
            raise AIProviderError() from exc
        return self._parse(message)

    @staticmethod
    def _parse(message: Any) -> LLMResponse:
        texts: list[str] = []
        calls: list[ToolCall] = []
        content: list[dict[str, Any]] = []
        for block in message.content:
            kind = getattr(block, "type", "")
            if kind == "text":
                texts.append(block.text)
            elif kind == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
            if kind not in _SKIP_ECHO:
                content.append(block.to_dict())
        usage = message.usage
        iterations = getattr(usage, "iterations", None) or []
        stop_details = getattr(message, "stop_details", None)
        return LLMResponse(
            text="".join(texts),
            stop_reason=str(message.stop_reason or ""),
            usage=Usage(
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                cache_read_tokens=int(usage.cache_read_input_tokens or 0),
                cache_write_tokens=int(usage.cache_creation_input_tokens or 0),
            ),
            model=str(message.model),
            tool_calls=calls,
            content=content,
            request_id=str(getattr(message, "_request_id", "") or ""),
            fallback_used=any(getattr(i, "type", "") == "fallback_message" for i in iterations),
            refusal_category=getattr(stop_details, "category", None) if stop_details else None,
        )
