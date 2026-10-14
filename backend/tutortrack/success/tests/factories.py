from __future__ import annotations

import factory
from django.utils import timezone

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.identity.tests.factories import UserFactory
from tutortrack.success.models import (
    ProductEvent,
    SupportConversation,
    SupportMessage,
    SurveyResponse,
)


class SupportConversationFactory(TenantFactory):
    class Meta:
        model = SupportConversation

    subject = "How do I run invoices?"
    opened_by = factory.SubFactory(UserFactory)
    last_message_at = factory.LazyFunction(timezone.now)


class SupportMessageFactory(TenantFactory):
    class Meta:
        model = SupportMessage

    conversation = factory.SubFactory(
        SupportConversationFactory, organisation=factory.SelfAttribute("..organisation")
    )
    author = factory.SelfAttribute("conversation.opened_by")
    body = "Where is the invoice run?"


class SurveyResponseFactory(TenantFactory):
    class Meta:
        model = SurveyResponse

    user = factory.SubFactory(UserFactory)
    kind = SurveyResponse.Kind.NPS
    score = 9
    role = "owner"


class ProductEventFactory(TenantFactory):
    class Meta:
        model = ProductEvent

    name = "page.viewed"
    actor = factory.Sequence(lambda n: f"{n:032x}")
    route = "/billing"
    occurred_at = factory.LazyFunction(timezone.now)
