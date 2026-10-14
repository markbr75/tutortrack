"""Cross-tenant isolation for every E31 list/detail endpoint (CLAUDE.md rule 1)."""

from __future__ import annotations

from typing import Any

from tutortrack.ai.models import AIAssist, AIProposal, AIRequestLog, ThreadInsight
from tutortrack.comms.tests.factories import ThreadFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import UserFactory

_owner: dict[str, Any] = {}


def _log(organisation: Any, user: Any = None) -> AIRequestLog:
    with tenant_context(organisation):
        return AIRequestLog.objects.create(
            user=user,
            feature="inbox",
            prompt_key="inbox.reply",
            prompt_version=1,
            provider="fake",
            status="ok",
            redacted_input_hash="0" * 64,
        )


class TestRequestLogs(TenantIsolationTestMixin):
    list_url = "/api/v1/ai/requests"

    def make_object(self, organisation):
        return _log(organisation)


class TestAssists(TenantIsolationTestMixin):
    list_url = "/api/v1/ai/assists"

    def make_object(self, organisation):
        log = _log(organisation)
        with tenant_context(organisation):
            return AIAssist.objects.create(
                request=log, feature="inbox", subject_type="thread", subject_id="x"
            )


class TestProposals(TenantIsolationTestMixin):
    """Proposals are the requester's own, so the acting user owns the object here."""

    list_url = "/api/v1/ai/proposals"

    def acting_user(self, organisation):
        _owner.setdefault("user", UserFactory(is_superuser=True))
        return _owner["user"]

    def make_object(self, organisation):
        user = _owner.setdefault("user", UserFactory(is_superuser=True))
        with tenant_context(organisation):
            return AIProposal.objects.create(
                user=user,
                feature="command_bar",
                action="create_task",
                params={"title": "Call"},
                summary="Create a task",
            )

    def teardown_method(self):
        _owner.clear()


class TestThreadInsights(TenantIsolationTestMixin):
    list_url = "/api/v1/ai/thread-insights"

    def make_object(self, organisation):
        thread = ThreadFactory(organisation=organisation)
        with tenant_context(organisation):
            return ThreadInsight.objects.create(
                thread=thread, intent="billing", confidence=90, classified_at=now()
            )
