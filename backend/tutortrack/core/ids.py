"""Identifier helpers. Primary keys are UUIDv7: time-ordered and safe to expose."""

import uuid

from uuid6 import uuid7


def new_id() -> uuid.UUID:
    """Return a new UUIDv7 as a standard ``uuid.UUID``."""
    return uuid.UUID(int=uuid7().int)
