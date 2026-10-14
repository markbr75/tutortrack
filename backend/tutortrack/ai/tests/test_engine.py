"""E31-T01: provider abstraction, settings, redaction, request logging, metering against
AI credits, rate limits, refusal and error handling, and the Anthropic request shape."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from django.test import override_settings

from tutortrack.ai import engine, metering, prompts, providers
from tutortrack.ai.exceptions import (
    AICreditsExhausted,
    AIIncomplete,
    AIProviderError,
    AIRateLimited,
    AIRefused,
    AIUnavailable,
)
from tutortrack.ai.models import AIRequestLog, AIUsage
from tutortrack.ai.providers import LLMRequest, LLMResponse, ToolCall, Usage
from tutortrack.ai.providers.claude import FALLBACK_BETA, AnthropicProvider
from tutortrack.ai.redaction import Redactor
from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import FeatureDisabled, UpgradeRequired
from tutortrack.identity.tests.factories import UserFactory

from .conftest import enable, set_ai

pytestmark = pytest.mark.django_db


# --- redaction ----------------------------------------------------------------------------------


def test_redactor_pseudonymises_people_and_contact_details_and_restores_them():
    redactor = Redactor()
    full = redactor.person("Arjun Patel", kind="STUDENT")
    assert full == "[STUDENT_1]"
    text = (
        "Arjun Patel did well. arjun liked fractions; Mrs Patel can call 07700 900123 or "
        "email priya@example.com. Next lesson 2026-10-21 at 16:00, fee 45.00."
    )
    redacted = redactor.redact(text)
    assert "Arjun" not in redacted
    assert "arjun" not in redacted
    assert "Patel" not in redacted
    assert "07700" not in redacted
    assert "priya@example.com" not in redacted
    assert "[STUDENT_1_FIRST] liked" in redacted
    assert "[EMAIL_1]" in redacted
    assert "Mrs [STUDENT_1_LAST]" in redacted
    assert "2026-10-21" in redacted
    assert "45.00" in redacted
    assert redactor.restore(redacted) == text.replace("arjun liked", "Arjun liked")
    assert redactor.restore("Well done [STUDENT_1_FIRST]!") == "Well done Arjun!"
    assert redactor.restore_data({"a": ["[STUDENT_1]"]}) == {"a": ["Arjun Patel"]}


def test_provider_selection():
    assert providers.provider_name() == "fake"  # tests never reach the real API
    with override_settings(AI={**_ai(), "PROVIDER": "", "API_KEY": "sk-test"}):
        assert providers.provider_name() == "anthropic"
    with override_settings(AI={**_ai(), "PROVIDER": "", "API_KEY": ""}):
        assert providers.provider_name() == "fake"


def _ai() -> dict[str, Any]:
    from django.conf import settings

    return dict(settings.AI)


# --- the pipeline -------------------------------------------------------------------------------


def _run(org: Any, user: Any, **kwargs: Any) -> engine.Result:
    redactor = kwargs.pop("redactor", Redactor())
    with tenant_context(org):
        return engine.run(
            prompts.INBOX_REPLY,
            user=user,
            content=kwargs.pop("content", "Hi from Priya Patel"),
            redactor=redactor,
            **kwargs,
        )


def test_features_are_off_until_the_organisation_opts_in(org, fake_llm):
    user = UserFactory()
    with pytest.raises(FeatureDisabled):
        _run(org, user)
    enable(org, "inbox")
    assert _run(org, user).text


def test_the_plan_must_include_the_ai_assistant(org, fake_llm):
    enable(org, "inbox")

    class NoAI:
        def has(self, key, organisation_id):
            return key != "ai_assistant"

        def limit(self, key, organisation_id):
            return None

        def required_plan(self, key, needed=None):
            return "agency"

    previous = entitlements._resolver
    entitlements.set_resolver(NoAI())
    try:
        with pytest.raises(UpgradeRequired):
            _run(org, UserFactory())
    finally:
        entitlements.set_resolver(previous)


def test_requests_are_redacted_logged_and_metered_without_storing_prompts(org, fake_llm):
    enable(org, "inbox")
    user = UserFactory()
    redactor = Redactor()
    redactor.person("Priya Patel", kind="CONTACT")
    result = _run(org, user, redactor=redactor, content="Message from Priya Patel")
    sent = fake_llm.requests[0]
    assert "Priya" not in str(sent.messages)
    assert "[CONTACT_1]" in str(sent.messages)
    assert "Style: friendly tone, UK English spelling." in sent.messages[0]["content"]
    assert result.text.startswith("Hi Priya Patel,")  # placeholder restored on the way back
    with tenant_context(org):
        log = AIRequestLog.objects.get()
        usage = AIUsage.objects.get()
    assert log.status == "ok"
    assert log.prompt_key == "inbox.reply"
    assert log.prompt_version == 1
    assert log.provider == "fake"
    assert log.model == "claude-opus-5-5"
    assert len(log.redacted_input_hash) == 64
    assert log.input_tokens > 0
    assert log.credits >= 1
    assert log.cache_write_tokens > 0
    assert (usage.requests, usage.credits, usage.user_id) == (1, log.credits, user.pk)
    with tenant_context(org):
        stored = " ".join(str(v) for v in AIRequestLog.objects.values().first().values())
    assert "Priya" not in stored
    # A second identical request reads the cached system prompt.
    _run(org, user, redactor=redactor, content="Message from Priya Patel")
    with tenant_context(org):
        assert AIRequestLog.objects.order_by("-created_at").first().cache_read_tokens > 0
        assert AIUsage.objects.get().requests == 2


def test_tone_and_spelling_follow_the_feature_then_the_organisation(org, fake_llm):
    enable(org, "inbox")
    set_ai(org, tone="formal", spelling="en-US")
    _run(org, UserFactory())
    assert (
        "Style: formal tone, US English spelling." in fake_llm.requests[-1].messages[0]["content"]
    )
    enable(org, "inbox", tone="friendly", language="en-GB")
    _run(org, UserFactory())
    assert "friendly tone, UK English" in fake_llm.requests[-1].messages[0]["content"]


def test_credits_are_consumed_and_exhaustion_blocks_with_a_clear_error(org, fake_llm):
    from tutortrack.subscriptions import credits
    from tutortrack.subscriptions.tests.test_subscriptions import subscribe

    subscribe(org, "agency")
    enable(org, "inbox")
    user = UserFactory()
    with tenant_context(org):
        assert credits.account("ai").allowance == 2000
    result = _run(org, user)
    with tenant_context(org):
        account = credits.account("ai")
        assert account.used_this_period == result.log.credits
        assert credits.ledger("ai")[0].ref == f"ai:{result.log.pk}"
        account.included_balance = 0
        account.save()
    with pytest.raises(AICreditsExhausted) as exc:
        _run(org, user)
    assert exc.value.status_code == 402
    assert len(fake_llm.requests) == 1  # blocked before calling the model


def test_monthly_cap(org, fake_llm):
    enable(org, "inbox")
    user = UserFactory()
    first = _run(org, user)
    set_ai(org, monthly_credit_cap=first.log.credits)
    with pytest.raises(AICreditsExhausted):
        _run(org, user)


def test_per_user_rate_limit(org, fake_llm):
    enable(org, "inbox")
    user = UserFactory()
    with override_settings(AI={**_ai(), "USER_REQUESTS_PER_MINUTE": 2}):
        _run(org, user)
        _run(org, user)
        with pytest.raises(AIRateLimited) as exc:
            _run(org, user)
    assert exc.value.extra["retry_after"] > 0


def test_refusals_and_truncation_stop_the_request_and_are_logged(org, fake_llm):
    enable(org, "inbox")
    fake_llm.script(
        "inbox.reply",
        LLMResponse("", "refusal", Usage(10, 0), "m", refusal_category="cyber"),
        LLMResponse("Hi", "max_tokens", Usage(10, 4000), "m"),
    )
    with pytest.raises(AIRefused) as refused:
        _run(org, UserFactory())
    assert refused.value.extra == {"category": "cyber"}
    with pytest.raises(AIIncomplete):
        _run(org, UserFactory())
    with tenant_context(org):
        statuses = set(AIRequestLog.objects.values_list("status", flat=True))
    assert statuses == {"refused", "incomplete"}


class _Tools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def definitions(self) -> list[dict[str, Any]]:
        return [{"name": "lookup", "description": "x", "input_schema": prompts.obj({})}]

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        self.calls.append((name, arguments))
        if arguments.get("fail"):
            return {"error": "No such thing."}, True
        return {"found": "Priya Patel"}, False


def test_tool_loop_returns_all_results_in_one_message_and_never_runs_refused_tools(org, fake_llm):
    enable(org, "inbox")
    tools = _Tools()
    two_calls = LLMResponse(
        "",
        "tool_use",
        Usage(5, 5),
        "m",
        tool_calls=[ToolCall("t1", "lookup", {}), ToolCall("t2", "lookup", {"fail": True})],
        content=[{"type": "tool_use", "id": "t1"}, {"type": "tool_use", "id": "t2"}],
    )
    fake_llm.script("inbox.reply", two_calls, LLMResponse("Done", "end_turn", Usage(5, 5), "m"))
    redactor = Redactor()
    redactor.person("Priya Patel", kind="CONTACT")
    result = _run(org, UserFactory(), toolbox=tools, redactor=redactor)
    assert result.text == "Done"
    assert result.rounds == 1
    results = fake_llm.requests[1].messages[-1]
    assert results["role"] == "user"
    assert len(results["content"]) == 2
    assert [b["tool_use_id"] for b in results["content"]] == ["t1", "t2"]
    assert results["content"][1]["is_error"] is True
    assert "[CONTACT_1]" in results["content"][0]["content"]  # tool output redacted
    # A refused turn's tool calls are never executed.
    refused = LLMResponse(
        "", "refusal", Usage(1, 1), "m", tool_calls=[ToolCall("t3", "lookup", {})]
    )
    fake_llm.script("inbox.reply", refused)
    tools.calls.clear()
    with pytest.raises(AIRefused):
        _run(org, UserFactory(), toolbox=tools)
    assert tools.calls == []


# --- Anthropic provider -------------------------------------------------------------------------


def _request(tier: str = "default", **kwargs: Any) -> LLMRequest:
    return LLMRequest(
        prompt="x",
        tier=tier,  # type: ignore[arg-type]
        system="SYSTEM",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1000,
        effort="low",
        **kwargs,
    )


@override_settings(AI={**__import__("django.conf").conf.settings.AI, "API_KEY": "sk-test"})
def test_anthropic_request_shape():
    provider = AnthropicProvider()
    opus = provider._kwargs(
        _request(tools=[{"name": "b"}, {"name": "a"}], output_schema={"type": "object"})
    )
    assert opus["model"] == "claude-opus-5-5"
    assert opus["thinking"] == {"type": "adaptive"}
    assert opus["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert opus["system"] == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    assert [t["name"] for t in opus["tools"]] == ["a", "b"]
    assert opus["tools"][0]["strict"]
    assert opus["tool_choice"] == {"type": "auto"}
    assert opus["betas"] == [FALLBACK_BETA]
    assert opus["fallbacks"] == "default"
    assert "temperature" not in opus
    assert "budget_tokens" not in str(opus)
    haiku = provider._kwargs(_request("fast"))
    assert haiku["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in haiku
    assert "betas" not in haiku
    assert "tools" not in haiku


def _block(**values: Any) -> Any:
    return SimpleNamespace(**values, to_dict=lambda: dict(values))


def test_anthropic_response_parsing():
    message = SimpleNamespace(
        content=[
            _block(type="fallback"),
            _block(type="thinking", thinking=""),
            _block(type="text", text="Hello"),
            _block(type="tool_use", id="toolu_1", name="lookup", input={"q": 1}),
        ],
        stop_reason="tool_use",
        stop_details=None,
        model="claude-opus-4-8",
        _request_id="req_1",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=20,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=40,
            iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")],
        ),
    )
    parsed = AnthropicProvider._parse(message)
    assert parsed.text == "Hello"
    assert parsed.tool_calls == [ToolCall("toolu_1", "lookup", {"q": 1})]
    assert [b["type"] for b in parsed.content] == ["thinking", "text", "tool_use"]
    assert parsed.fallback_used
    assert parsed.request_id == "req_1"
    assert (parsed.usage.cache_read_tokens, parsed.usage.cache_write_tokens) == (30, 40)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("rate", AIRateLimited),
        ("connection", AIUnavailable),
        ("server", AIUnavailable),
        ("bad", AIProviderError),
    ],
)
@override_settings(AI={**__import__("django.conf").conf.settings.AI, "API_KEY": "sk-test"})
def test_sdk_errors_map_to_problems(monkeypatch, error, expected):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def raise_(**_kwargs: Any) -> Any:
        if error == "rate":
            response = httpx2.Response(429, request=request, headers={"retry-after": "12"})
            raise anthropic.RateLimitError("slow down", response=response, body=None)
        if error == "connection":
            raise anthropic.APIConnectionError(request=request)
        status = 529 if error == "server" else 400
        raise anthropic.APIStatusError(
            "nope", response=httpx2.Response(status, request=request), body=None
        )

    provider = AnthropicProvider()
    monkeypatch.setattr(provider.client.beta.messages, "create", raise_)
    with pytest.raises(expected) as exc:
        provider.complete(_request())
    if error == "rate":
        assert exc.value.extra["retry_after"] == 12


def test_credit_conversion():
    assert metering.credits_for("claude-haiku-5-5", Usage(1000, 200)) == 1
    opus = metering.credits_for("claude-opus-5-5", Usage(2000, 2500))
    assert opus == 12  # (2000*4 + 2500*20) / 1e6 = $0.058 -> 11.6 -> 12
    cached = metering.credits_for("claude-opus-5-5", Usage(0, 2500, cache_read_tokens=2000))
    assert cached < opus
    assert metering.credits_for("claude-opus-5-5", Usage()) == 0
