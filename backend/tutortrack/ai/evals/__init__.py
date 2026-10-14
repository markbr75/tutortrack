"""Prompt eval harness (E31-T01): golden inputs with expected *properties* per prompt.

Cases (``cases.py``) hold the already-pseudonymised user message a feature would build,
optional canned tool results, and checks on the output (JSON fields, required or banned
phrases, placeholders kept, tools called with given arguments, length). They run:

* in CI against ``FakeLLMProvider`` (``tests/test_evals.py``), so every prompt change runs
  its eval set and the harness itself stays honest;
* against the real API only when asked: ``AI_EVALS_LIVE=1 ANTHROPIC_API_KEY=...
  manage.py ai_evals --live``. The test suite never calls the real API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..prompts import PROMPTS, Prompt
from ..providers.base import LLMProvider, LLMRequest, LLMResponse

MAX_ROUNDS = 6


@dataclass
class Case:
    name: str
    prompt: str
    content: str
    schema: dict[str, Any] | None = None
    tools: str = ""  # "command" | "copilot": the real tool definitions
    tool_results: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    case: Case
    passed: bool
    failures: list[str]
    text: str
    data: Any
    calls: list[tuple[str, dict[str, Any]]]


def _definitions(kind: str) -> list[dict[str, Any]]:
    from ..redaction import Redactor
    from ..tools import CommandToolBox, CopilotToolBox

    if kind == "command":
        return CommandToolBox(None, Redactor()).definitions()
    if kind == "copilot":
        return CopilotToolBox(None, Redactor()).definitions()
    return []


def _get(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, list):
            return [_get(item, part) for item in data]
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _flat(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def check(case: Case, text: str, data: Any, calls: list[tuple[str, dict[str, Any]]]) -> list[str]:
    expect = case.expect
    failures: list[str] = []
    output = text if data is None else _flat(data)
    lower = output.lower()
    for key in expect.get("json_keys", []):
        if not isinstance(data, dict) or key not in data:
            failures.append(f"missing JSON key {key}")
    for phrase in expect.get("contains", []):
        if phrase.lower() not in lower:
            failures.append(f"missing {phrase!r}")
    any_of = expect.get("contains_any", [])
    if any_of and not any(p.lower() in lower for p in any_of):
        failures.append(f"none of {any_of!r}")
    for phrase in expect.get("not_contains", []):
        if phrase.lower() in lower:
            failures.append(f"must not contain {phrase!r}")
    for path, wanted in expect.get("equals", {}).items():
        got = _get(data, path)
        if str(got).lower() != str(wanted).lower():
            failures.append(f"{path} is {got!r}, expected {wanted!r}")
    for path, options in expect.get("one_of", {}).items():
        if _get(data, path) not in options:
            failures.append(f"{path} is {_get(data, path)!r}, expected one of {options!r}")
    for path, wanted in expect.get("list_contains", {}).items():
        got = [str(v).lower() for v in (_get(data, path) or [])]
        if str(wanted).lower() not in got:
            failures.append(f"{path} {got!r} lacks {wanted!r}")
    for path in expect.get("non_empty", []):
        if not _get(data, path):
            failures.append(f"{path} is empty")
    if "max_words" in expect and len(re.findall(r"\S+", text)) > expect["max_words"]:
        failures.append(f"more than {expect['max_words']} words")
    called = [name for name, _args in calls]
    for name in expect.get("tools_called", []):
        if name not in called:
            failures.append(f"tool {name} not called (called {called})")
    for spec, wanted in expect.get("tool_args", {}).items():
        tool, _, arg = spec.partition(".")
        values = [args.get(arg) for name, args in calls if name == tool]
        if not any(_matches(v, wanted) for v in values):
            failures.append(f"{spec} was {values!r}, expected {wanted!r}")
    return failures


def _matches(value: Any, wanted: Any) -> bool:
    if isinstance(wanted, str) and wanted.startswith("*"):
        return str(value).endswith(wanted[1:])
    return str(value).lower() == str(wanted).lower()


def run_case(case: Case, provider: LLMProvider) -> Outcome:
    prompt: Prompt = PROMPTS[case.prompt]
    tools = _definitions(case.tools)
    messages: list[dict[str, Any]] = [{"role": "user", "content": case.content}]
    calls: list[tuple[str, dict[str, Any]]] = []
    response: LLMResponse | None = None
    for _round in range(MAX_ROUNDS):
        response = provider.complete(
            LLMRequest(
                prompt=prompt.key,
                tier=prompt.tier,
                system=prompt.system,
                messages=messages,
                max_tokens=prompt.max_tokens,
                effort=prompt.effort,
                tools=tools,
                output_schema=case.schema if case.schema is not None else prompt.schema,
            )
        )
        if response.stop_reason != "tool_use" or not response.tool_calls:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tool_call in response.tool_calls:
            calls.append((tool_call.name, tool_call.input))
            output = case.tool_results.get(tool_call.name, {"error": "Not available in this eval."})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": json.dumps(output, sort_keys=True),
                    **({"is_error": True} if "error" in output else {}),
                }
            )
        messages.append({"role": "user", "content": results})
    if response is None:
        raise RuntimeError("no response")
    data = None
    failures: list[str] = []
    if response.stop_reason != "end_turn":
        failures.append(f"stop_reason {response.stop_reason}")
    if (case.schema or prompt.schema) is not None and response.stop_reason == "end_turn":
        try:
            data = json.loads(response.text)
        except ValueError:
            failures.append("invalid JSON")
    failures += check(case, response.text, data, calls)
    return Outcome(case, not failures, failures, response.text, data, calls)


def run_all(provider: LLMProvider, only: str = "") -> list[Outcome]:
    from .cases import CASES

    return [run_case(c, provider) for c in CASES if not only or c.prompt == only]
