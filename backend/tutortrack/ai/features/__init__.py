"""One module per AI feature (E31 FR-31-1..8). Each loads only data the person may see,
registers the people involved with a ``Redactor``, builds the per-request content and
calls ``engine.run``. Results are drafts: nothing is saved to another app's records."""

from __future__ import annotations

from typing import Any

from tutortrack.core.exceptions import NotFound
from tutortrack.core.permissions import scope_queryset


def scoped_get(
    user: Any, model: Any, codename: str, pk: Any, *, related: tuple[str, ...] = ()
) -> Any:
    """The record if ``user`` holds ``codename`` over it, else 404 (never 403)."""
    qs = scope_queryset(user, model.objects.all(), codename)
    if related:
        qs = qs.select_related(*related)
    try:
        obj = qs.filter(pk=pk).first()
    except (ValueError, TypeError):
        obj = None
    if obj is None:
        raise NotFound()
    return obj


def quoted(text: str) -> str:
    """Untrusted text, fenced so the model treats it as content."""
    return f'"""\n{(text or "").strip()}\n"""'
