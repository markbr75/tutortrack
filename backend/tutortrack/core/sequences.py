"""Gap-free, per-organisation sequential numbers (INV-000123, CN-000004, PR-000017...).

The counter row is locked with ``SELECT ... FOR UPDATE`` in the caller's transaction, so a
number is only consumed if the document using it commits. That is what makes it gap-free:
a rolled-back invoice never burns a number.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, connection, transaction

from .context import require_organisation_id
from .models import Sequence


class SequenceOutsideTransaction(RuntimeError):
    pass


def _locked_sequence(org_id: uuid.UUID, key: str) -> Sequence:
    seq = Sequence.all_tenants.select_for_update().filter(organisation_id=org_id, key=key).first()
    if seq is not None:
        return seq
    try:
        with transaction.atomic():
            # The new row is locked by this transaction until it commits.
            return Sequence.all_tenants.create(organisation_id=org_id, key=key, next_value=1)
    except IntegrityError:
        # Another transaction created it first; wait for its lock.
        return Sequence.all_tenants.select_for_update().get(organisation_id=org_id, key=key)


def next_value(key: str, *, organisation_id: uuid.UUID | None = None) -> int:
    if not connection.in_atomic_block:
        raise SequenceOutsideTransaction(
            "next_value() must run inside the transaction that saves the numbered document"
        )
    org_id = organisation_id or require_organisation_id()
    seq = _locked_sequence(org_id, key)
    value = seq.next_value
    Sequence.all_tenants.filter(pk=seq.pk).update(next_value=value + 1)
    return value


def next_number(
    key: str, *, prefix: str = "", padding: int = 6, organisation_id: uuid.UUID | None = None
) -> str:
    """e.g. ``next_number("invoice", prefix="INV-")`` -> ``"INV-000001"``."""
    return f"{prefix}{next_value(key, organisation_id=organisation_id):0{padding}d}"
