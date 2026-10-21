"""Core data in the E29 retention engine: anonymous public-form uploads that were never sent
with a form (gap batch G5a) are deleted after a day or two."""

from __future__ import annotations

from datetime import datetime

from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import RetentionCategory, register_retention


def _purge_unclaimed(cutoff: datetime, dry_run: bool, limit: int) -> int:
    from .storage.public import purge_unclaimed

    return purge_unclaimed(cutoff, dry_run, limit)


register_retention(
    RetentionCategory(
        key="unclaimed_public_uploads",
        label=gettext_lazy("Files uploaded on public forms that were never sent"),
        default_days=2,
        purge=_purge_unclaimed,
        order=90,
    )
)
