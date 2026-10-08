from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from tutortrack.core.seeding import SeedContext, run_all


class Command(BaseCommand):
    help = "Load idempotent demo data (platform admin, demo organisation, flags, ...)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--force", action="store_true", help="Allow seeding when DEBUG is off (never prod)."
        )

    def handle(self, *args: Any, force: bool = False, **options: Any) -> None:
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed with DEBUG off. Pass --force if you're sure.")
        self.stdout.write("Seeding demo data:")
        with transaction.atomic():
            ran = run_all(SeedContext(log=self.stdout.write))
        self.stdout.write(self.style.SUCCESS(f"Done ({len(ran)} steps)."))
