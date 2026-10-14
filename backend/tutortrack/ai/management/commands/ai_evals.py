"""Run the prompt eval set: ``manage.py ai_evals`` (fake provider) or, with
``AI_EVALS_LIVE=1`` and ``ANTHROPIC_API_KEY`` set, ``manage.py ai_evals --live`` against the
real Claude API (costs tokens; never part of the test suite)."""

from __future__ import annotations

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Run the AI prompt eval cases and report which properties fail."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live", action="store_true", help="Call the real Claude API.")
        parser.add_argument("--prompt", default="", help="Only this prompt key.")

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.ai.evals import run_all
        from tutortrack.ai.providers.fake import FakeLLMProvider

        if options["live"]:
            if os.environ.get("AI_EVALS_LIVE") != "1":
                raise CommandError("Set AI_EVALS_LIVE=1 to run evals against the real API.")
            from django.conf import settings

            if not settings.AI.get("API_KEY"):
                raise CommandError("Set ANTHROPIC_API_KEY to run live evals.")
            from tutortrack.ai.providers.claude import AnthropicProvider

            provider: Any = AnthropicProvider()
        else:
            provider = FakeLLMProvider()
        outcomes = run_all(provider, options["prompt"])
        failed = 0
        for outcome in outcomes:
            mark = "PASS" if outcome.passed else "FAIL"
            self.stdout.write(f"{mark}  {outcome.case.prompt:<22} {outcome.case.name}")
            for failure in outcome.failures:
                self.stdout.write(f"      - {failure}")
            failed += not outcome.passed
        self.stdout.write(f"{len(outcomes) - failed}/{len(outcomes)} passed ({provider.name})")
        if failed:
            raise CommandError(f"{failed} eval case(s) failed")
