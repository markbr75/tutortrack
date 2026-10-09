"""Field-level encryption for secrets (CLAUDE.md rule 11).

``EncryptedField`` stores Fernet ciphertext. Keys come from ``FIELD_ENCRYPTION_KEYS``
(newest first; older keys still decrypt, so keys can be rotated with
``rotate_field(model, "field")``). E03 introduced this for MFA secrets; E29 moves the key
material to KMS and adds bank details and safeguarding notes.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@cache
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS must contain at least one key")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def fernet() -> MultiFernet:
    return _fernet(tuple(settings.FIELD_ENCRYPTION_KEYS))


def encrypt(value: str) -> str:
    return fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt value: unknown key or corrupted data") from exc


class EncryptedField(models.TextField):
    """A text value encrypted at rest. Not searchable or orderable by design."""

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> str | None:
        return None if value is None else decrypt(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return None if value is None else encrypt(str(value))

    def get_lookup(self, lookup_name: str) -> Any:
        if lookup_name not in {"isnull"}:
            return None  # ciphertext is randomised; equality lookups would be meaningless
        return super().get_lookup(lookup_name)


def rotate_field(model: type[models.Model], field: str, *, using: str = "default") -> int:
    """Re-encrypt ``field`` with the newest key. Returns rows updated."""
    count = 0
    column = model._meta.get_field(field).column  # type: ignore[union-attr]
    from django.db import connections

    with connections[using].cursor() as cursor:
        cursor.execute(f'SELECT id, "{column}" FROM "{model._meta.db_table}"')  # noqa: S608
        for pk, token in cursor.fetchall():
            if token is None:
                continue
            rotated = fernet().rotate(token.encode()).decode()
            cursor.execute(
                f'UPDATE "{model._meta.db_table}" SET "{column}" = %s WHERE id = %s',  # noqa: S608
                [rotated, pk],
            )
            count += 1
    return count
