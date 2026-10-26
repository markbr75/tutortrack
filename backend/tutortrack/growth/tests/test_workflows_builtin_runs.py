"""E33-T06: the review request built-in running on Temporal: the link, one reminder and
closing the link when it runs out."""

from __future__ import annotations

import pytest
from django.db import transaction

from tutortrack.automations import services as automations
from tutortrack.automations.models import AutomationRun
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.growth import services
from tutortrack.growth.models import ReviewRequest
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, TutorProfileFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_a_review_request_is_sent_reminded_then_closed(org, temporal_env):
    with tenant_context(org):
        automations.install_builtins()
        client = ClientFactory(organisation=org, display_name="The Patels")
        ContactFactory(organisation=org, client=client, email="priya@example.com", mobile="")
        tutor = TutorProfileFactory(organisation=org, first_name="Nia")
    dispatch_batch()
    with tenant_context(org), transaction.atomic():
        request = services.request_review(client=client, tutor=tutor)
    dispatch_batch()  # review.requested starts the run
    with tenant_context(org):
        run = AutomationRun.objects.get(
            automation__builtin_key="review_request", subject_id=str(request.pk)
        )
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        request = ReviewRequest.objects.get(pk=request.pk)
        assert request.status == "expired"
        assert request.sent_at is not None
        assert request.reminded_at is not None
        assert Message.objects.filter(type_key="review_request").count() == 2
