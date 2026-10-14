"""E29 safeguards on the E13 Phase 2 paths: inbox messages people write and broadcasts."""

from __future__ import annotations

import pytest
from django.db import transaction

from tutortrack.comms import inbox
from tutortrack.comms import services as comms
from tutortrack.comms.models import Message, Thread, ThreadMessage
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.privacy.models import SafeguardingFlag

pytestmark = pytest.mark.django_db


def test_a_staff_inbox_reply_with_contact_details_is_blocked_and_flagged(org, family, owner):
    with tenant_context(org), transaction.atomic():
        thread = inbox.open_thread(kind=Thread.Kind.CLIENT, client=family.client)
        with pytest.raises(BusinessRuleViolation):
            inbox.reply(thread, owner, body="Text me on 07700900999")
        assert not ThreadMessage.objects.filter(thread=thread).exists()
        flag = SafeguardingFlag.objects.get()
    assert flag.blocked
    assert flag.reasons == ["contact_details"]
    assert str(flag.sender_id) == str(owner.pk)


def test_a_tutor_portal_message_with_contact_details_is_blocked(org, family, tutor):
    author = inbox.Author("tutor", str(tutor.pk), "Nia", tutor.membership.user)
    with tenant_context(org), transaction.atomic():
        thread = inbox.open_thread(kind=Thread.Kind.TUTOR_FAMILY, client=family.client, tutor=tutor)
        with pytest.raises(BusinessRuleViolation):
            inbox.post_from_portal(thread, author, body="Email me at nia@example.org")
        ok = inbox.post_from_portal(thread, author, body="See you on Monday")
        flag = SafeguardingFlag.objects.get()
    assert ok.body == "See you on Monday"
    assert flag.blocked
    assert flag.reasons == ["contact_details"]


def test_marketing_queued_to_a_child_is_suppressed(org, family):
    child_user = MembershipFactory(organisation=org, role="student").user
    with tenant_context(org), transaction.atomic():
        family.student.user = child_user
        family.student.save()
        recipient = comms.registry.Recipient(
            kind="user",
            id=str(child_user.pk),
            name="Arjun",
            first_name="Arjun",
            email=child_user.email,
            user_id=str(child_user.pk),
        )

        def queue(category: str, key: str) -> Message | None:
            return comms.queue_message(
                type_key="broadcast_email",
                channel="email",
                recipient=recipient,
                subject="Summer offer",
                body="20% off",
                dedupe_key=key,
                category=category,
            )

        marketing = queue("marketing", "m1")
        service = queue("service", "m2")
    assert marketing is not None
    assert marketing.status == Message.Status.SUPPRESSED
    assert marketing.error == "aadc:no_marketing_to_children"
    assert service is not None
    assert service.status != Message.Status.SUPPRESSED
