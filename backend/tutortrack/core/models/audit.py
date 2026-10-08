from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from ..ids import new_id


class AuditEntry(models.Model):
    """Append-only record of a change (or sensitive read).

    UPDATE/DELETE are blocked by a database trigger; retention purges (E29) must first run
    ``SET LOCAL tutortrack.audit_purge = 'on'``. Foreign keys don't enforce constraints so
    audit history outlives deleted users and organisations.
    """

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    organisation = models.ForeignKey(
        "tenancy.Organisation",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    action = models.CharField(max_length=50)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=200, blank=True, default="")
    changes = models.JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name_plural = "audit entries"
        indexes = [
            models.Index(
                fields=["organisation", "object_type", "object_id", "-created_at"],
                name="audit_object_idx",
            ),
            models.Index(fields=["organisation", "actor", "-created_at"], name="audit_actor_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type}:{self.object_id}"
