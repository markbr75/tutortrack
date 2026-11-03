"""Reads for pathways (E34 FR-34-1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import scope_queryset
from tutortrack.core.time import now

from .models import PathwayRun, PathwayStep, PathwayTemplate


def templates() -> QuerySet[PathwayTemplate]:
    return PathwayTemplate.objects.select_related("current_version")


def runs(user: Any) -> QuerySet[PathwayRun]:
    return scope_queryset(
        user,
        PathwayRun.objects.select_related("template", "version", "tutor", "owner"),
        "pathway.view",
    )


def run_steps(run: PathwayRun) -> QuerySet[PathwayStep]:
    return run.steps.select_related("completed_by").order_by("position")


def my_tasks(tutor: Any) -> QuerySet[PathwayStep]:
    """The steps a tutor has to do now, or has sent and is waiting on (FR-34-1 Tasks)."""
    return (
        PathwayStep.objects.filter(
            run__tutor=tutor,
            run__status=PathwayRun.Status.RUNNING,
            assignee=PathwayStep.Assignee.PARTICIPANT,
            status__in=(PathwayStep.Status.OPEN, PathwayStep.Status.REVIEW),
        )
        .select_related("run__template")
        .order_by("due_at", "run__started_at", "position")
    )


def my_booked_calls(tutor: Any) -> list[PathwayStep]:
    """Calls the tutor booked through a pathway that haven't happened yet (shown with their
    tasks, with the meeting link)."""
    moment = now()
    steps = PathwayStep.objects.filter(
        run__tutor=tutor,
        type="book_call",
        status=PathwayStep.Status.DONE,
        completed_at__gte=moment - timedelta(days=60),
    ).select_related("run__template")
    upcoming = [
        s
        for s in steps
        if s.result.get("start") and datetime.fromisoformat(s.result["start"]) > moment
    ]
    return sorted(upcoming, key=lambda s: s.result["start"])
