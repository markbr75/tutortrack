"""The request pipeline every AI feature goes through (E31-T01).

``run(prompt, user=..., content=..., redactor=...)``:

1. the feature must be on for the organisation (plan entitlement ``ai_assistant`` and the
   tenant's opt-in), the person within their rate limit and the organisation within its
   monthly cap and AI credits;
2. the content is pseudonymised (``redaction``) and sent with the prompt's frozen system
   prompt; tool calls (command bar, copilot) run through a permission-checked ``ToolBox``
   and their results are pseudonymised too, all returned in one user message;
3. ``stop_reason`` is checked before reading content: ``refusal`` and ``max_tokens`` stop
   the request (a refused turn's tools never run);
4. the answer has its placeholders restored, the request is logged (hash of the redacted
   input, never the prompt) and its tokens metered and charged as AI credits, whatever
   the outcome once tokens were used.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import DomainError

from . import metering
from .exceptions import AIIncomplete, AIRefused
from .models import AIRequestLog, AIUsage
from .prompts import Prompt
from .providers import LLMRequest, LLMResponse, Usage, get_provider
from .redaction import Redactor, fingerprint

logger = structlog.get_logger(__name__)


class ToolBox(Protocol):
    def definitions(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        """Run a tool; returns (result, is_error). Must enforce permissions itself."""
        ...


@dataclass
class Result:
    text: str
    data: Any
    log: AIRequestLog
    rounds: int = 0
    tool_calls: list[str] = field(default_factory=list)


def _style_line(feature: str) -> str:
    from .selectors import style_for

    style = style_for(feature)
    spelling = "UK English" if style["language"] == "en-GB" else "US English"
    return f"Style: {style['tone']} tone, {spelling} spelling."


def _log(
    prompt: Prompt,
    *,
    feature: str,
    user: Any,
    model: str,
    status: str,
    usage: Usage,
    started: float,
    rounds: int,
    digest: str,
    response: LLMResponse | None,
    error_code: str = "",
) -> AIRequestLog:
    credits = metering.credits_for(model, usage)
    with transaction.atomic():
        log = AIRequestLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            feature=feature,
            prompt_key=prompt.key,
            prompt_version=prompt.version,
            provider=get_provider().name,
            model=(response.model if response else model)[:60],
            status=status,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            credits=credits,
            latency_ms=int((time.monotonic() - started) * 1000),
            tool_rounds=rounds,
            fallback_used=bool(response and response.fallback_used),
            redacted_input_hash=digest,
            provider_request_id=(response.request_id if response else "")[:100],
            error_code=error_code[:60],
        )
        if credits or status == AIRequestLog.Status.OK:
            row, _created = AIUsage.objects.select_for_update().get_or_create(
                period=metering.month_start(),
                user=log.user,
                feature=feature,
            )
            AIUsage.objects.filter(pk=row.pk).update(
                requests=F("requests") + 1,
                input_tokens=F("input_tokens") + usage.input_tokens,
                output_tokens=F("output_tokens") + usage.output_tokens,
                cache_read_tokens=F("cache_read_tokens") + usage.cache_read_tokens,
                cache_write_tokens=F("cache_write_tokens") + usage.cache_write_tokens,
                credits=F("credits") + credits,
            )
            metering.charge(credits, ref=f"ai:{log.pk}")
    logger.info(
        "ai.request",
        prompt=prompt.key,
        version=prompt.version,
        status=status,
        credits=credits,
        rounds=rounds,
        latency_ms=log.latency_ms,
    )
    return log


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise AIIncomplete() from exc


def run(
    prompt: Prompt,
    *,
    user: Any,
    content: str,
    redactor: Redactor,
    toolbox: ToolBox | None = None,
    schema: dict[str, Any] | None = None,
    feature: str | None = None,
    check: bool = True,
) -> Result:
    from .selectors import require_enabled

    feature = feature or prompt.feature
    if check:
        require_enabled(feature)
    metering.check_rate(user)
    metering.ensure_available()

    provider = get_provider()
    output_schema = schema if schema is not None else prompt.schema
    tools = toolbox.definitions() if toolbox else []
    first = f"{_style_line(feature)}\n\n{redactor.redact(content)}"
    messages: list[dict[str, Any]] = [{"role": "user", "content": first}]
    digest = fingerprint(prompt.system, messages, tools)
    usage = Usage()
    started = time.monotonic()
    rounds = 0
    called: list[str] = []
    response: LLMResponse | None = None
    max_rounds = int(settings.AI.get("MAX_TOOL_ROUNDS") or 6)

    def fail(status: str, code: str) -> None:
        _log(
            prompt,
            feature=feature,
            user=user,
            model=provider.model_for(prompt.tier),
            status=status,
            usage=usage,
            started=started,
            rounds=rounds,
            digest=digest,
            response=response,
            error_code=code,
        )

    try:
        while True:
            response = provider.complete(
                LLMRequest(
                    prompt=prompt.key,
                    tier=prompt.tier,
                    system=prompt.system,
                    messages=messages,
                    max_tokens=prompt.max_tokens,
                    effort=prompt.effort,
                    tools=tools,
                    output_schema=output_schema,
                )
            )
            usage.add(response.usage)
            if response.stop_reason == "refusal":
                fail(AIRequestLog.Status.REFUSED, response.refusal_category or "refusal")
                raise AIRefused(
                    _("The AI declined this request. Try rewording it, or write it yourself."),
                    category=response.refusal_category,
                )
            if response.stop_reason == "max_tokens":
                fail(AIRequestLog.Status.INCOMPLETE, "max_tokens")
                raise AIIncomplete()
            if response.stop_reason in ("tool_use", "pause_turn") and (
                response.tool_calls or response.stop_reason == "pause_turn"
            ):
                rounds += 1
                if rounds > max_rounds:
                    fail(AIRequestLog.Status.INCOMPLETE, "too_many_rounds")
                    raise AIIncomplete(_("That needed too many steps; try a narrower request."))
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason == "pause_turn":
                    continue
                results = []
                for tool_call in response.tool_calls:
                    called.append(tool_call.name)
                    output, is_error = (
                        toolbox.call(tool_call.name, redactor.restore_data(tool_call.input))
                        if toolbox
                        else ({"error": "No tools are available."}, True)
                    )
                    body = json.dumps(redactor.redact_data(output), sort_keys=True, default=str)
                    block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": body,
                    }
                    if is_error:
                        block["is_error"] = True
                    results.append(block)
                messages.append({"role": "user", "content": results})
                continue
            break
    except DomainError as exc:
        if not isinstance(exc, AIRefused | AIIncomplete):
            fail(AIRequestLog.Status.ERROR, exc.problem_type)
        raise

    if response is None:  # pragma: no cover - the loop always makes one call
        raise AIIncomplete()
    text = redactor.restore(response.text.strip())
    data = None
    if output_schema is not None:
        try:
            data = redactor.restore_data(_parse_json(response.text))
        except AIIncomplete:
            fail(AIRequestLog.Status.INCOMPLETE, "invalid_json")
            raise
    log = _log(
        prompt,
        feature=feature,
        user=user,
        model=provider.model_for(prompt.tier),
        status=AIRequestLog.Status.OK,
        usage=usage,
        started=started,
        rounds=rounds,
        digest=digest,
        response=response,
    )
    return Result(text=text, data=data, log=log, rounds=rounds, tool_calls=called)
