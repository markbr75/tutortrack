"""Shared fixtures for E31. The world comes from E21's fixtures: tutor Nia teaches Arjun
Patel (a job and lessons), tutor Sam teaches nobody; an admin; two families."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tutortrack.ai import services
from tutortrack.ai.models import Feature
from tutortrack.ai.providers import get_provider, reset
from tutortrack.ai.providers.fake import FakeLLMProvider
from tutortrack.core.context import tenant_context
from tutortrack.learning.tests.conftest import at, lesson_for, world  # noqa: F401
from tutortrack.tenancy import settings_service


@pytest.fixture
def fake_llm() -> Iterator[FakeLLMProvider]:
    reset()
    provider = get_provider()
    assert isinstance(provider, FakeLLMProvider)
    provider.reset()
    yield provider
    provider.reset()


def enable(org: Any, *features: str, **values: Any) -> None:
    with tenant_context(org):
        for feature in features or Feature.values:
            services.update_feature(feature, enabled=True, **values)


def set_ai(org: Any, **values: Any) -> None:
    with tenant_context(org):
        settings_service.update_settings("ai", {f"ai.{k}": v for k, v in values.items()})


@pytest.fixture
def ai_on(org: Any, fake_llm: FakeLLMProvider) -> FakeLLMProvider:
    enable(org)
    return fake_llm


def sent_text(provider: FakeLLMProvider) -> str:
    """Everything that would have reached the model, as one string."""
    import json

    return "\n".join(r.system + json.dumps(r.messages, default=str) for r in provider.requests)
