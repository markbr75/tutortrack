"""Create or update the platform Temporal Schedules (E30 Part 2: nightly insights).
Idempotent; the Temporal worker task runs it before polling (infra/terraform/ecs.tf)."""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the platform-wide Temporal Schedules."

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.platform_admin.schedules import ensure_insights_schedule

        self.stdout.write(f"Schedule ready: {ensure_insights_schedule()}")
