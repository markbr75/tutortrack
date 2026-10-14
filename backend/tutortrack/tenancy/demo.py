"""Demo-data mode (FR-02-6 "explore with demo data"; E02-T08, gap batch G2).

Apps contribute realistic sample records for a *real* organisation from a ``demo.py``
module (autodiscovered); "Explore with demo data" and E27 sandboxes load them and "Clear
demo data" removes them in one click::

    from tutortrack.tenancy.demo import DemoContext, demo_provider

    @demo_provider(order=50)
    def students(ctx: DemoContext) -> None:
        client = people_services.create_client(...)

Providers create records through their app's services. **Every tenant row saved while a
provider runs is tracked automatically** (``post_save``), so side records such as ledger
entries, charges and audit-free child rows go too; rows written with ``bulk_create`` (no
signal) must be passed to ``ctx.track``. ``ctx.extras`` passes records between providers.

While loading (``core.demo_mode``): sample documents get ``DEMO-`` numbers, nothing is sent
and after-commit callbacks the providers register (workflow starts, emails, receipts) are
dropped. Domain events are recorded and handled at once by
the in-product projections only (billing, pay and reporting, ``INLINE_SUBSCRIBERS``), then
marked dispatched, so notifications, automations, accounting sync and webhooks never see
sample data.

Wiping deletes tracked records newest first, with their cascades, in repeated passes
(something real may still point at a sample record: it is then kept and reported). Providers
that need custom clean-up pass ``wipe=`` to handle their own records.

Distinct from ``seeds.py``/``seed_demo``, which builds the local development dataset.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import structlog
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models, transaction
from django.db.models import ProtectedError, RestrictedError
from django.db.models.signals import post_save
from django.utils.module_loading import autodiscover_modules
from django.utils.translation import gettext as _

from tutortrack.core import audit, demo_mode
from tutortrack.core.context import branch_scope, require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import TenantModel

from .models import DemoRecord, Organisation

logger = structlog.get_logger(__name__)

# Event handlers that build in-product state from sample data (charges from completed
# lessons, pay items, report facts). Everything else (messages, automations, workflows,
# accounting sync, webhooks...) ignores sample data.
INLINE_SUBSCRIBERS = (
    "tutortrack.billing.handlers.",
    "tutortrack.payroll.handlers.",
    "tutortrack.reporting.handlers.",
)
MAX_WIPE_PASSES = 6


@dataclass
class DemoContext:
    organisation: Organisation
    provider: str
    created: list[models.Model] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    events: list[Any] = field(default_factory=list)
    _seen: set[tuple[type, str]] = field(default_factory=set)

    def track(self, instance: models.Model) -> models.Model:
        key = (type(instance), str(instance.pk))
        if key not in self._seen:
            self._seen.add(key)
            self.created.append(instance)
        return instance

    def track_all(self, instances: Iterable[models.Model]) -> None:
        for instance in instances:
            self.track(instance)


_current: ContextVar[DemoContext | None] = ContextVar("tutortrack_demo_context", default=None)


def _record_created(
    sender: type, instance: Any, created: bool, raw: bool = False, **kwargs: Any
) -> None:
    ctx = _current.get()
    if ctx is None or not created or raw:
        return
    from tutortrack.core.models import OutboxEvent

    if isinstance(instance, OutboxEvent):
        ctx.events.append(instance)
    elif isinstance(instance, TenantModel) and not isinstance(instance, DemoRecord):
        ctx.track(instance)


post_save.connect(_record_created, dispatch_uid="tutortrack.tenancy.demo.track")


def _dispatch_inline(ctx: DemoContext) -> None:
    """Run the in-product projections for the events this provider raised, then mark every
    one dispatched so no other subscriber (or the outbox dispatcher) sees them."""
    from tutortrack.core.events.base import EventEnvelope
    from tutortrack.core.events.registry import subscribers_for
    from tutortrack.core.models import OutboxEvent, ProcessedEvent
    from tutortrack.core.time import now

    done = 0
    while done < len(ctx.events):  # handlers may publish further events
        event = ctx.events[done]
        done += 1
        envelope = EventEnvelope.from_payload(event.payload)
        for subscriber in subscribers_for(event.event_type):
            if not subscriber.name.startswith(INLINE_SUBSCRIBERS):
                continue
            try:
                with transaction.atomic():
                    subscriber.handler(envelope)
                    ProcessedEvent.objects.create(subscriber=subscriber.name, event=event)
            except Exception:  # sample data must never block loading
                logger.exception(
                    "demo.handler_failed", subscriber=subscriber.name, event_type=event.event_type
                )
    OutboxEvent.objects.filter(pk__in=[e.pk for e in ctx.events]).update(dispatched_at=now())
    ctx.events.clear()


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
    extras: dict[str, Any] = {}
    for provider in providers():
        ctx = DemoContext(organisation=organisation, provider=provider.name, extras=extras)
        token = _current.set(ctx)
        callbacks = len(connection.run_on_commit)
        try:
            with demo_mode.loading(), transaction.atomic():
                provider.create(ctx)
                _dispatch_inline(ctx)
        finally:
            _current.reset(token)
            # No after-commit side effects (emails, workflow starts, receipts, outbox kicks).
            del connection.run_on_commit[callbacks:]
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


def _delete_tracked(records: list[DemoRecord]) -> list[DemoRecord]:
    """Delete each record (with its cascades) newest first, in passes: one record may only
    become deletable once a later one has gone. Returns what could not be deleted."""
    pending = records
    for _pass in range(MAX_WIPE_PASSES):
        blocked: list[DemoRecord] = []
        for record in pending:
            model = record.content_type.model_class()
            if model is None:
                continue
            try:
                with transaction.atomic():
                    model._default_manager.filter(pk=record.object_id).delete()
            except (ProtectedError, RestrictedError):
                blocked.append(record)
        if not blocked or len(blocked) == len(pending):
            return blocked
        pending = blocked
    return pending


@transaction.atomic
def wipe_demo_data() -> int:
    """Delete every tracked demo record (newest first). Returns how many were removed.
    Sample records that real data now refers to (say a real invoice for a sample family)
    are kept, still marked as demo data."""
    organisation = Organisation.objects.select_for_update().get(pk=require_organisation_id())
    records = list(DemoRecord.objects.select_related("content_type").order_by("-sequence"))
    providers()  # make sure custom wipes are registered
    custom = {p.name: p for p in _providers.values() if p.wipe is not None}
    by_provider: dict[str, list[DemoRecord]] = {}
    generic: list[DemoRecord] = []
    for record in records:
        if record.provider in custom:
            by_provider.setdefault(record.provider, []).append(record)
        else:
            generic.append(record)
    for name, provider_records in by_provider.items():
        custom[name].wipe(provider_records)  # type: ignore[misc]
    # Tenant-scoped managers; branch restrictions don't apply to an org-wide wipe.
    with branch_scope(None):
        kept = _delete_tracked(generic)
    if kept:
        logger.warning("demo.records_kept", count=len(kept))
    DemoRecord.objects.exclude(pk__in=[r.pk for r in kept]).delete()
    with audit.track(organisation, action="wipe_demo_data"):
        organisation.has_demo_data = bool(kept)
        organisation.save(update_fields=["has_demo_data", "updated_at"])
    return len(records) - len(kept)
