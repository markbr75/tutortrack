from typing import Any

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Print a new key for FIELD_ENCRYPTION_KEYS. With FIELD_ENCRYPTION_KMS_KEY_ID set, the "
        "key is a KMS data key and only its wrapped form is printed (envelope encryption)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--temporal", action="store_true", help="Format for TEMPORAL_PAYLOAD_KEYS"
        )
        parser.add_argument("--key-id", default="", help="Key id prefix (Temporal keys)")

    def handle(self, *args: Any, **options: Any) -> None:
        kms_key = settings.FIELD_ENCRYPTION_KMS_KEY_ID
        if kms_key:
            from tutortrack.core import kms

            _, wrapped = kms.generate_data_key(kms_key)
            value = f"{options['key_id'] or 'k1'}:kms:{wrapped}" if options["temporal"] else wrapped
        elif options["temporal"]:
            import base64
            import os

            value = f"{options['key_id'] or 'k1'}:{base64.b64encode(os.urandom(32)).decode()}"
        else:
            value = Fernet.generate_key().decode()
        self.stdout.write(value)
