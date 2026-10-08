"""Demo-data mode (FR-02-6 "explore with demo data"; E02-T08).

Apps contribute realistic sample records for a *real* organisation from a ``demo.py``
module (autodiscovered), tracking everything they create so it can be wiped in one click::

    from tutortrack.tenancy.demo import DemoContext, demo_provider

    @demo_provider(order=50)
    def students(ctx: DemoContext) -> None:
        client = people_services.create_client(...)
        ctx.track(client)

Wiping deletes tracked records newest first, then clears ``has_demo_data``. Providers that
need custom clean-up (e.g. financial records, which are otherwise never deleted) pass
``wipe=`` to handle their own records.

Distinct from ``seeds.py``/``seed_demo``, which builds the local development dataset.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils.module_loading import autodiscover_modules
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import branch_scope, require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation

from .models import DemoRecord, Organisation


@dataclass
class DemoContext:
    organisation: Organisation
    provider: str
    created: list[models.Model] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def track(self, instance: models.Model) -> models.Model:
        self.created.append(instance)
        return instance


@dataclass(frozen=True)
class DemoProvider:
    order: int
    name: str
    create: Callable[[DemoContext], None]
    wipe: Callable[[list[DemoRecord]], None] | None = None


_providers: dict[str, DemoProvider] = {}


def demo_provider(
    *, order: int, wipe: Callable[[list[DemoRecord]], None] | None = None
) -> Callable[[Callable[[DemoContext], None]], Callable[[DemoContext], None]]:
    def decorator(func: Callable[[DemoContext], None]) -> Callable[[DemoContext], None]:
        name = f"{func.__module__}.{func.__qualname__}"
        _providers[name] = DemoProvider(order=order, name=name, create=func, wipe=wipe)
        return func

    return decorator


def providers() -> list[DemoProvider]:
    autodiscover_modules("demo")
    return sorted(_providers.values(), key=lambda p: (p.order, p.name))


def _organisation() -> Organisation:
    return Organisation.objects.get(pk=require_organisation_id())


@transaction.atomic
def load_demo_data() -> int:
    """Add sample data to the organisation in context. Returns the number of records."""
    organisation = Organisation.objects.select_for_update().get(pk=require_organisation_id())
    if organisation.has_demo_data:
        raise BusinessRuleViolation(_("Demo data is already loaded."))
    sequence = 0
    for provider in providers():
        ctx = DemoContext(organisation=organisation, provider=provider.name)
        provider.create(ctx)
        for instance in ctx.created:
            sequence += 1
            DemoRecord.objects.create(
                content_type=ContentType.objects.get_for_model(instance),
                object_id=str(instance.pk),
                provider=provider.name,
                sequence=sequence,
            )
    with audit.track(organisation, action="load_demo_data"):
        organisation.has_demo_data = True
        organisation.save(update_fields=["has_demo_data", "updated_at"])
    return sequence


@transaction.atomic
def wipe_demo_data() -> int:
    """Delete every tracked demo record (newest first). Returns how many were removed."""
    organisation = Organisation.objects.select_for_update().get(pk=require_organisation_id())
    records = list(DemoRecord.objects.order_by("-sequence"))
    custom = {p.name: p for p in _providers.values() if p.wipe is not None}
    by_provider: dict[str, list[DemoRecord]] = {}
    for record in records:
        if record.provider in custom:
            by_provider.setdefault(record.provider, []).append(record)
            continue
        model = record.content_type.model_class()
        if model is not None:
            # Tenant-scoped manager; branch restrictions don't apply to an org-wide wipe.
            with branch_scope(None):
                model._default_manager.filter(pk=record.object_id).delete()
    for name, provider_records in by_provider.items():
        custom[name].wipe(provider_records)  # type: ignore[misc]
    DemoRecord.objects.all().delete()
    with audit.track(organisation, action="wipe_demo_data"):
        organisation.has_demo_data = False
        organisation.save(update_fields=["has_demo_data", "updated_at"])
    return len(records)
