"""Workflow and activity registry, filled from each app's ``workflows.py`` and
``activities.py`` (autodiscovered by the worker)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from django.utils.module_loading import autodiscover_modules

ALL_QUEUES = "*"
T = TypeVar("T")


@dataclass
class Registry:
    workflows: dict[str, list[type]] = field(default_factory=lambda: defaultdict(list))
    activities: dict[str, list[Callable[..., Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    processes: dict[str, ProcessInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessInfo:
    """What the processes API needs to know about a workflow type."""

    process: str
    workflow: type
    task_queue: str
    cancel_permission: str | None  # None: cannot be cancelled from the API


registry = Registry()


def register_workflow(
    *, process: str, task_queue: str = "default", cancel_permission: str | None = None
) -> Callable[[type[T]], type[T]]:
    """Class decorator, applied *outside* ``@workflow.defn``."""

    def decorator(cls: type[T]) -> type[T]:
        if cls not in registry.workflows[task_queue]:
            registry.workflows[task_queue].append(cls)
        registry.processes[process] = ProcessInfo(process, cls, task_queue, cancel_permission)
        return cls

    return decorator


def register_activity(fn: Callable[..., Any], task_queue: str) -> None:
    if fn not in registry.activities[task_queue]:
        registry.activities[task_queue].append(fn)


def discover() -> Registry:
    autodiscover_modules("activities")
    autodiscover_modules("workflows")
    return registry
