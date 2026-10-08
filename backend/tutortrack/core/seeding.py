"""Demo-data seeding registry used by ``manage.py seed_demo``.

Each app adds its demo data in a ``seeds.py`` module:

    from tutortrack.core.seeding import SeedContext, seed_step

    @seed_step(order=50)
    def students(ctx: SeedContext) -> None:
        ...  # create demo students for ctx.organisation using the app's factories/services

Steps run in ``order`` and must be idempotent (re-running the command is safe).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.utils.module_loading import autodiscover_modules


@dataclass
class SeedContext:
    organisation: Any = None
    admin: Any = None
    log: Callable[[str], None] = print
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeedStep:
    order: int
    name: str
    func: Callable[[SeedContext], None]


_steps: dict[str, SeedStep] = {}


def seed_step(*, order: int) -> Callable[[Callable[[SeedContext], None]], Callable[..., None]]:
    def decorator(func: Callable[[SeedContext], None]) -> Callable[[SeedContext], None]:
        name = f"{func.__module__}.{func.__qualname__}"
        _steps[name] = SeedStep(order=order, name=name, func=func)
        return func

    return decorator


def run_all(ctx: SeedContext) -> list[str]:
    autodiscover_modules("seeds")
    ran = []
    for step in sorted(_steps.values(), key=lambda s: (s.order, s.name)):
        ctx.log(f"  - {step.name}")
        step.func(ctx)
        ran.append(step.name)
    return ran
