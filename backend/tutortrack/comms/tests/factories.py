from __future__ import annotations

import factory

from tutortrack.comms.models import (
    Broadcast,
    CannedReply,
    PhoneNumber,
    Segment,
    SenderDomain,
    Thread,
    ThreadMessage,
    WhatsAppTemplate,
)
from tutortrack.core.tests.factories import TenantFactory


class SegmentFactory(TenantFactory):
    class Meta:
        model = Segment

    name = factory.Sequence(lambda n: f"Segment {n}")
    audience = "contacts"
    definition = factory.LazyFunction(lambda: {"client_statuses": ["active"]})


class BroadcastFactory(TenantFactory):
    class Meta:
        model = Broadcast

    name = factory.Sequence(lambda n: f"Broadcast {n}")
    channel = "email"
    purpose = "operational"
    subject = "News"
    body = "Hello {{ recipient.first_name }}"
    audience = "contacts"
    definition = factory.LazyFunction(dict)


class ThreadFactory(TenantFactory):
    class Meta:
        model = Thread

    kind = "other"
    subject = "Hello"
    contact_name = "Someone"
    contact_email = factory.Sequence(lambda n: f"someone{n}@example.com")


class ThreadMessageFactory(TenantFactory):
    class Meta:
        model = ThreadMessage

    thread = factory.SubFactory(ThreadFactory, organisation=factory.SelfAttribute("..organisation"))
    direction = "inbound"
    channel = "email"
    author_type = "external"
    author_name = "Someone"
    body = "Hello there"


class CannedReplyFactory(TenantFactory):
    class Meta:
        model = CannedReply

    title = factory.Sequence(lambda n: f"Reply {n}")
    body = "Thanks, we'll be in touch."


class SenderDomainFactory(TenantFactory):
    class Meta:
        model = SenderDomain

    domain = factory.Sequence(lambda n: f"school{n}.example.com")


class PhoneNumberFactory(TenantFactory):
    class Meta:
        model = PhoneNumber

    channel = "sms"
    number = factory.Sequence(lambda n: f"+4477009{n:05d}")


class WhatsAppTemplateFactory(TenantFactory):
    class Meta:
        model = WhatsAppTemplate

    name = factory.Sequence(lambda n: f"template_{n}")
    body = "Hi {{1}}, news from {{2}}."
    variables = factory.LazyFunction(
        lambda: ["{{ recipient.first_name }}", "{{ organisation.name }}"]
    )
    status = "approved"
    content_sid = "HX-test-template"
