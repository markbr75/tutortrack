"""``migrate`` runs as the table-owner role.

The application role (``default``) cannot create tables, and must not own them or RLS
would not apply to it. When an ``owner`` database alias is configured, a plain
``manage.py migrate`` is redirected to it; ``--database`` still wins when given explicitly
for another alias.
"""

from typing import Any

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS

from tutortrack.core.db import OWNER_DB_ALIAS


class Command(MigrateCommand):
    def handle(self, *args: Any, **options: Any) -> None:
        if options.get("database") == DEFAULT_DB_ALIAS and OWNER_DB_ALIAS in settings.DATABASES:
            options["database"] = OWNER_DB_ALIAS
        super().handle(*args, **options)
