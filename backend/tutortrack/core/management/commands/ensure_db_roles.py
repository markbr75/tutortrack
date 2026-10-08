from typing import Any

from django.core.management.base import BaseCommand

from tutortrack.core.db import OWNER_DB_ALIAS
from tutortrack.core.dbroles import ensure_roles, grant_privileges


class Command(BaseCommand):
    help = (
        "Create/update the application (RLS-restricted) and platform (BYPASSRLS) database "
        "roles from DATABASE_URL / DATABASE_PLATFORM_URL, and grant table privileges. "
        "Runs as the owner role (DATABASE_OWNER_URL). Idempotent."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--database", default=OWNER_DB_ALIAS)

    def handle(self, *args: Any, **options: Any) -> None:
        created = ensure_roles(options["database"])
        grant_privileges(options["database"])
        for name in created:
            self.stdout.write(self.style.SUCCESS(f"Created role {name}."))
        self.stdout.write("Database roles and privileges are up to date.")
