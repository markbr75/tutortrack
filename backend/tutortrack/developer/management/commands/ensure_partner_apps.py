from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Create the platform partner OAuth apps (Zapier, Make) if they don't exist."

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.developer.partners import ensure_partner_apps

        with transaction.atomic():
            created = ensure_partner_apps()
        for key, secret in created.items():
            if secret is None:
                self.stdout.write(f"{key}: already registered")
            else:
                # Shown once, for the partner console; never logged anywhere else.
                self.stdout.write(f"{key}: created, client secret {secret}")
