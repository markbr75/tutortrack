"""Per-organisation Temporal Schedules (E32 FR-32-7).

Recurring per-tenant processes (invoice runs, pay-run cut-offs) are Temporal Schedules,
created/updated by the settings services that own them; global housekeeping stays on
Celery Beat. Each schedule is tracked as a ``ScheduleLink`` so an organisation's schedules
can be paused on suspension and deleted on closure.
"""

from __future__ import annotations

from typing import Any

import structlog
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from ..context import tenant_context
from . import runtime
from .client import get_client
from .ops import process_info

logger = structlog.get_logger(__name__)


def schedule_id(process: str, organisation_id: Any, *parts: Any) -> str:
    return ":".join(["schedule", process, str(organisation_id), *(str(p) for p in parts)])


async def _ensure(
    sid: str, workflow: type, input: Any, spec: ScheduleSpec, workflow_id_prefix: str
) -> None:
    info = process_info(workflow)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            workflow.run,  # type: ignore[attr-defined]
            input,
            id=workflow_id_prefix,
            task_queue=info.task_queue,
        ),
        spec=spec,
    )
    client = await get_client()
    handle = client.get_schedule_handle(sid)
    try:
        await handle.describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        await client.create_schedule(sid, schedule)
        return

    def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    await handle.update(updater)


def ensure_schedule(
    *,
    process: str,
    workflow: type,
    input: Any,
    cron: list[str],
    timezone: str,
    parts: tuple[Any, ...] = (),
) -> str:
    """Create or update the organisation's schedule; returns its id. Each run starts a
    workflow with id ``<schedule id>-<scheduled time>`` (Temporal appends the time)."""
    from ..models import ScheduleLink

    sid = schedule_id(process, input.organisation_id, *parts)
    spec = ScheduleSpec(cron_expressions=cron, time_zone_name=timezone)
    runtime.run(_ensure(sid, workflow, input, spec, sid.replace("schedule:", "", 1)))
    with tenant_context(input.organisation_id):
        ScheduleLink.objects.update_or_create(
            schedule_id=sid, defaults={"process": process, "paused": False}
        )
    return sid


async def _each(sids: list[str], action: str, note: str) -> list[str]:
    client = await get_client()
    done = []
    for sid in sids:
        handle = client.get_schedule_handle(sid)
        try:
            if action == "pause":
                await handle.pause(note=note)
            elif action == "unpause":
                await handle.unpause(note=note)
            else:
                await handle.delete()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
            logger.info("schedule.missing", schedule_id=sid)
        done.append(sid)
    return done


def _apply(organisation_id: Any, action: str, note: str = "") -> list[str]:
    from ..models import ScheduleLink

    with tenant_context(organisation_id):
        all_ids = list(ScheduleLink.objects.values_list("schedule_id", flat=True))
    if not all_ids:
        return []  # nothing to do: don't touch Temporal
    sids = runtime.run(_each(all_ids, action, note))
    with tenant_context(organisation_id):
        qs = ScheduleLink.objects.filter(schedule_id__in=sids)
        if action == "delete":
            qs.delete()
        else:
            qs.update(paused=action == "pause")
    return sids


def pause_organisation_schedules(organisation_id: Any, note: str = "") -> list[str]:
    return _apply(organisation_id, "pause", note)


def unpause_organisation_schedules(organisation_id: Any, note: str = "") -> list[str]:
    return _apply(organisation_id, "unpause", note)


def delete_organisation_schedules(organisation_id: Any) -> list[str]:
    return _apply(organisation_id, "delete")


def delete_schedule(organisation_id: Any, sid: str) -> bool:
    """Delete one schedule (e.g. invoicing switched back to manual). False if unknown."""
    from ..models import ScheduleLink

    with tenant_context(organisation_id):
        if not ScheduleLink.objects.filter(schedule_id=sid).exists():
            return False
    runtime.run(_each([sid], "delete", ""))
    with tenant_context(organisation_id):
        ScheduleLink.objects.filter(schedule_id=sid).delete()
    return True
