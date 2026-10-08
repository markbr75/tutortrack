from django.db import models
from django.utils import timezone

from ..ids import new_id


class IdempotencyRecord(models.Model):
    """Stored response for a POST that carried an ``Idempotency-Key`` header (kept 24h).

    Not a TenantModel: the record is looked up in middleware, before views run.
    ``principal`` is the user id, or a hash of the Authorization header for token clients.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    organisation_id = models.UUIDField(null=True, blank=True)
    principal = models.CharField(max_length=128)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.BinaryField(null=True, blank=True)
    response_content_type = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation_id", "principal", "key"],
                name="idempotency_unique",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.principal}:{self.key}"
