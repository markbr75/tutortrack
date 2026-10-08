from django.db import models

from .base import TenantModel


class Sequence(TenantModel):
    """Gap-free per-organisation counter (invoice numbers, pay runs, jobs...).

    Always go through ``core.sequences.next_number``, which locks the row.
    """

    key = models.CharField(max_length=50)
    next_value = models.PositiveBigIntegerField(default=1)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="sequence_org_key_unique")
        ]

    def __str__(self) -> str:
        return f"{self.key}={self.next_value}"
