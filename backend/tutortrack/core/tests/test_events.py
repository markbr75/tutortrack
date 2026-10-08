import threading
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

import pytest
from django.db import connection, transaction

from tutortrack.core.context import current_organisation_id, request_context
from tutortrack.core.events import (
    DomainEvent,
    EventEnvelope,
    PublishOutsideTransaction,
    publish,
    subscribe,
    unsubscribe,
)
from tutortrack.core.events.dispatcher import dispatch_batch, replay_dead_letter
from tutortrack.core.models import OutboxEvent, ProcessedEvent
from tutortrack.core.money import Money


@dataclass(frozen=True, kw_only=True)
class GadgetRenamed(DomainEvent):
    event_type: ClassVar[str] = "test.gadget_renamed"
    subject_type: ClassVar[str] = "gadget"

    old_name: str
    new_name: str
    price: Money | None = None


@pytest.fixture
def received():
    """Registers a recording subscriber for the test event and removes it afterwards."""
    calls: list[tuple[EventEnvelope, UUID | None]] = []

    @subscribe("test.gadget_renamed", name="tests.recorder")
    def recorder(event: EventEnvelope) -> None:
        calls.append((event, current_organisation_id()))

    yield calls
    unsubscribe("tests.recorder")


def _publish(org=None, **kwargs):
    with transaction.atomic():
        return publish(
            GadgetRenamed(subject_id="g-1", old_name="A", new_name="B", **kwargs),
            organisation_id=org.pk if org else None,
        )


@pytest.mark.django_db(transaction=True)
def test_publish_outside_transaction_raises():
    with pytest.raises(PublishOutsideTransaction):
        publish(GadgetRenamed(subject_id="g", old_name="a", new_name="b"))


@pytest.mark.django_db(transaction=True)
def test_rolled_back_transaction_publishes_nothing(org):
    class Boom(Exception):
        pass

    with pytest.raises(Boom), transaction.atomic():
        publish(GadgetRenamed(subject_id="g", old_name="a", new_name="b"), organisation_id=org.pk)
        raise Boom
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
def test_envelope_contents(org, user):
    with request_context(user_id=user.pk):
        outbox = _publish(org, price=Money("40", "GBP"))
    envelope = EventEnvelope.from_payload(outbox.payload)
    assert envelope.id == outbox.id
    assert envelope.type == "test.gadget_renamed"
    assert envelope.organisation_id == org.pk
    assert envelope.subject == {"type": "gadget", "id": "g-1"}
    assert envelope.actor == {"type": "user", "id": str(user.pk)}
    assert envelope.data == {
        "old_name": "A",
        "new_name": "B",
        "price": {"amount": "40", "currency": "GBP"},
    }


@pytest.mark.django_db
def test_dispatch_delivers_in_tenant_context_and_marks_dispatched(org, received):
    outbox = _publish(org)
    assert dispatch_batch() == 1

    assert len(received) == 1
    envelope, org_in_handler = received[0]
    assert envelope.id == outbox.id
    assert org_in_handler == org.pk

    outbox.refresh_from_db()
    assert outbox.dispatched_at is not None
    assert dispatch_batch() == 0  # nothing left


@pytest.mark.django_db
def test_failing_subscriber_is_retried_without_rerunning_successful_ones(org, received):
    attempts = {"n": 0}

    @subscribe("test.gadget_renamed", name="tests.flaky")
    def flaky(event: EventEnvelope) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("temporary failure")

    try:
        outbox = _publish(org)
        dispatch_batch()
        outbox.refresh_from_db()
        assert outbox.dispatched_at is None
        assert outbox.attempts == 1
        assert "temporary failure" in outbox.last_error

        dispatch_batch()  # backoff is 0s in test settings
        outbox.refresh_from_db()
        assert outbox.dispatched_at is not None
        assert attempts["n"] == 2
        assert len(received) == 1  # the recorder ran exactly once
        assert ProcessedEvent.objects.filter(event=outbox).count() == 2
    finally:
        unsubscribe("tests.flaky")


@pytest.mark.django_db
def test_event_is_dead_lettered_after_max_attempts_and_can_be_replayed(org, settings):
    @subscribe("test.gadget_renamed", name="tests.broken")
    def broken(event: EventEnvelope) -> None:
        raise RuntimeError("always fails")

    try:
        outbox = _publish(org)
        for _ in range(settings.OUTBOX["MAX_ATTEMPTS"]):
            dispatch_batch()
        outbox.refresh_from_db()
        assert outbox.dead_lettered_at is not None
        assert dispatch_batch() == 0

        replay_dead_letter(outbox)
        unsubscribe("tests.broken")
        assert dispatch_batch() == 1
        outbox.refresh_from_db()
        assert outbox.dispatched_at is not None
    finally:
        unsubscribe("tests.broken")


@pytest.mark.django_db
def test_wildcard_subscribers_receive_every_event(org):
    seen = []

    @subscribe("*", name="tests.wildcard")
    def everything(event: EventEnvelope) -> None:
        seen.append(event.type)

    try:
        _publish(org)
        dispatch_batch()
        assert seen == ["test.gadget_renamed"]
    finally:
        unsubscribe("tests.wildcard")


def test_duplicate_event_types_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):

        @dataclass(frozen=True, kw_only=True)
        class Clash(DomainEvent):
            event_type: ClassVar[str] = "test.gadget_renamed"
            subject_type: ClassVar[str] = "gadget"


@pytest.mark.django_db(transaction=True)
def test_concurrent_dispatchers_process_each_event_exactly_once(org):
    lock = threading.Lock()
    handled: list[UUID] = []

    @subscribe("test.gadget_renamed", name="tests.counter")
    def counter(event: EventEnvelope) -> None:
        with lock:
            handled.append(event.id)

    try:
        for _ in range(30):
            _publish(org)

        def worker() -> None:
            try:
                while dispatch_batch(batch_size=5):
                    pass
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(handled) == 30
        assert len(set(handled)) == 30
        assert OutboxEvent.objects.filter(dispatched_at__isnull=True).count() == 0
    finally:
        unsubscribe("tests.counter")
