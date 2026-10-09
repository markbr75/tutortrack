from typing import Any

from django.core.management.base import BaseCommand

from tutortrack.core.crypto import encrypted_fields, rotate_field
from tutortrack.core.db import PLATFORM_DB_ALIAS


class Command(BaseCommand):
    help = (
        "Re-encrypt every EncryptedField value with the newest FIELD_ENCRYPTION_KEYS key. "
        "Runs on the platform connection (BYPASSRLS) so tenant tables are included."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--database", default=PLATFORM_DB_ALIAS)

    def handle(self, *args: Any, **options: Any) -> None:
        total = 0
        for model, field in encrypted_fields():
            count = rotate_field(model, field, using=options["database"])
            total += count
            self.stdout.write(f"{model._meta.label}.{field}: {count}")
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {total} values."))
