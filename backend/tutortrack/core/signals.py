from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .flags import invalidate_cache
from .models import FeatureFlag, FeatureFlagOverride


@receiver([post_save, post_delete], sender=FeatureFlag)
@receiver([post_save, post_delete], sender=FeatureFlagOverride)
def _flags_changed(**_: Any) -> None:
    invalidate_cache()
