"""Field-level encryption for secrets and sensitive PII (CLAUDE.md rule 11, FR-29-1).

``EncryptedField`` stores Fernet ciphertext (AES-128-CBC + HMAC-SHA256). Keys come from
``FIELD_ENCRYPTION_KEYS``, newest first; older keys still decrypt.

* Envelope encryption (production): with ``FIELD_ENCRYPTION_KMS_KEY_ID`` set, each entry is
  a KMS-wrapped 32-byte data key (``manage.py generate_encryption_key``), unwrapped once per
  process via KMS.
* Development/tests: entries are plain Fernet keys.
* Rotation: put a new key first, deploy, run ``manage.py rotate_encryption_keys`` (re-encrypts
  every encrypted column), then drop the old key.
"""

from __future__ import annotations

import base64
from functools import cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@cache
def _fernet(keys: tuple[str, ...], kms_key_id: str) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS must contain at least one key")
    if kms_key_id:
        from . import kms

        return MultiFernet([Fernet(base64.urlsafe_b64encode(kms.unwrap(k))) for k in keys])
    return MultiFernet([Fernet(k.encode()) for k in keys])


def fernet() -> MultiFernet:
    return _fernet(
        tuple(settings.FIELD_ENCRYPTION_KEYS),
        getattr(settings, "FIELD_ENCRYPTION_KMS_KEY_ID", "") or "",
    )


def encrypted_fields() -> list[tuple[type[models.Model], str]]:
    """Every (model, field name) using EncryptedField, for rotation."""
    from django.apps import apps

    return [
        (model, field.name)
        for model in apps.get_models()
        for field in model._meta.concrete_fields
        if isinstance(field, EncryptedField)
    ]


def encrypt(value: str) -> str:
    return fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt value: unknown key or corrupted data") from exc


class EncryptedField(models.TextField):
    """A text value encrypted at rest. Not searchable or orderable by design.

    Empty strings are stored as empty (they reveal nothing and keep ``blank=True`` defaults
    and pre-existing empty values readable)."""

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> str | None:
        if value is None or value == "":
            return value
        return decrypt(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def get_lookup(self, lookup_name: str) -> Any:
        if lookup_name not in {"isnull"}:
            return None  # ciphertext is randomised; equality lookups would be meaningless
        return super().get_lookup(lookup_name)


def rotate_field(model: type[models.Model], field: str, *, using: str = "default") -> int:
    """Re-encrypt ``field`` with the newest key. Returns rows updated.

    Raw SQL on ``using``: tenant tables need a connection that bypasses RLS (the
    ``rotate_encryption_keys`` command uses the platform alias)."""
    count = 0
    column = model._meta.get_field(field).column  # type: ignore[union-attr]
    from django.db import connections

    with connections[using].cursor() as cursor:
        cursor.execute(f'SELECT id, "{column}" FROM "{model._meta.db_table}"')  # noqa: S608
        for pk, token in cursor.fetchall():
            if not token:
                continue
            rotated = fernet().rotate(token.encode()).decode()
            cursor.execute(
                f'UPDATE "{model._meta.db_table}" SET "{column}" = %s WHERE id = %s',  # noqa: S608
                [rotated, pk],
            )
            count += 1
    return count
