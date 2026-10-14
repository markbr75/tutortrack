"""The eval harness runs in CI against the fake provider (never the real API): every prompt
has cases, the fake satisfies them, and the checks catch bad answers."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tutortrack.ai.evals import Case, check, run_all, run_case
from tutortrack.ai.evals.cases import CASES
from tutortrack.ai.prompts import PROMPTS
from tutortrack.ai.providers.base import LLMResponse, Usage
from tutortrack.ai.providers.fake import FakeLLMProvider


def test_every_prompt_has_eval_cases():
    assert {case.prompt for case in CASES} == set(PROMPTS)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_eval_cases_pass_on_the_fake(case):
    outcome = run_case(case, FakeLLMProvider())
    assert outcome.passed, outcome.failures


def test_checks_catch_bad_answers():
    case = Case(
        name="x",
        prompt="inbox.classify",
        content="",
        expect={"equals": {"intent": "billing"}, "not_contains": ["guarantee"], "max_words": 3},
    )
    failures = check(case, "we guarantee it all", {"intent": "other", "x": "guarantee"}, [])
    assert len(failures) == 3


def test_a_wrong_scripted_answer_fails_its_case():
    provider = FakeLLMProvider()
    provider.script(
        "inbox.classify",
        LLMResponse('{"intent": "other", "confidence": 1, "reason": ""}', "end_turn", Usage(), "m"),
    )
    case = next(c for c in CASES if c.name == "classify billing")
    assert not run_case(case, provider).passed


def test_management_command(capsys):
    call_command("ai_evals")
    assert f"{len(CASES)}/{len(CASES)} passed (fake)" in capsys.readouterr().out
    with pytest.raises(CommandError, match="AI_EVALS_LIVE"):
        call_command("ai_evals", "--live")
    assert len(run_all(FakeLLMProvider(), "inbox.classify")) == 3
