from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from ..ids import new_id


class OutboxEvent(models.Model):
    """A domain event written in the same transaction as the change that caused it.

    The row id *is* the event id. Rows are dispatched by ``core.events.dispatcher``.
    Platform-level events (no tenant) have a null organisation.
    """

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    organisation = models.ForeignKey(
        "tenancy.Organisation", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    event_type = models.CharField(max_length=100, db_index=True)
    event_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(encoder=DjangoJSONEncoder)
    occurred_at = models.DateTimeField(default=timezone.now)
    available_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    dispatched_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["available_at", "id"],
                name="outbox_pending_idx",
                condition=models.Q(dispatched_at__isnull=True, dead_lettered_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.id}"


class ProcessedEvent(models.Model):
    """Records that a subscriber has handled an event, making handlers idempotent."""

    subscriber = models.CharField(max_length=255)
    event = models.ForeignKey(OutboxEvent, on_delete=models.CASCADE, related_name="processed")
    processed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["subscriber", "event"], name="processed_event_unique")
        ]

    def __str__(self) -> str:
        return f"{self.subscriber} <- {self.event_id}"
