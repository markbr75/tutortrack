import time

from celery import shared_task

from .dispatcher import dispatch_batch

TIME_BUDGET_SECONDS = 30


@shared_task(name="tutortrack.core.events.tasks.dispatch_outbox", ignore_result=True)
def dispatch_outbox() -> int:
    """Drain due outbox events for up to ~30s. Safe to run concurrently (SKIP LOCKED)."""
    started = time.monotonic()
    total = 0
    while time.monotonic() - started < TIME_BUDGET_SECONDS:
        handled = dispatch_batch()
        total += handled
        if handled == 0:
            break
    return total
