"""Central Celery Beat schedule. Every scheduled task must be idempotent.

Per-tenant work is scheduled as a single master task that fans out one task per active
organisation (see ``tutortrack.core.tasks.fan_out_per_org``).
"""

from datetime import timedelta

BEAT_SCHEDULE = {
    # Fallback sweep; most events are dispatched immediately via on_commit.
    "outbox-dispatch": {
        "task": "tutortrack.core.events.tasks.dispatch_outbox",
        "schedule": timedelta(seconds=10),
    },
    "idempotency-cleanup": {
        "task": "tutortrack.core.tasks.purge_expired_idempotency_records",
        "schedule": timedelta(hours=1),
    },
}
