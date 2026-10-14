from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Tell every operational organisation about the current sub-processor list (once per "
        "version, E29-T11). Run after a deploy that changes SUBPROCESSORS_VERSION."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.privacy.compliance import SUBPROCESSORS_VERSION
        from tutortrack.privacy.tasks import notify_subprocessor_changes

        count = notify_subprocessor_changes()
        self.stdout.write(
            f"Queued {count} organisations for sub-processors {SUBPROCESSORS_VERSION}."
        )
