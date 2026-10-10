"""Central Celery Beat schedule. Every scheduled task must be idempotent.

Per-tenant work is scheduled as a single master task that fans out one task per active
organisation (see ``tutortrack.core.tasks.fan_out_per_org``).
"""

from datetime import timedelta

from celery.schedules import crontab

BEAT_SCHEDULE = {
    # Recurring lessons are materialised up to a rolling horizon (E08 FR-08-2).
    "extend-series-horizons": {
        "task": "tutortrack.scheduling.tasks.extend_all_series_horizons",
        "schedule": crontab(hour=2, minute=30),
    },
    # Lessons that just ended while still planned get an UnconfirmedLessonWorkflow (E09).
    "start-unconfirmed-checks": {
        "task": "tutortrack.delivery.tasks.start_all_unconfirmed_checks",
        "schedule": timedelta(minutes=15),
    },
    # Lesson reminders at each configured offset (E13-T06); dedupe keys make it idempotent.
    "lesson-reminders": {
        "task": "tutortrack.comms.tasks.send_all_lesson_reminders",
        "schedule": timedelta(minutes=5),
    },
    # Our subscription (E04): seat counts nightly, revenue share for the day before.
    "subscription-seats": {
        "task": "tutortrack.subscriptions.tasks.sync_all_seats",
        "schedule": crontab(hour=3, minute=10),
    },
    "subscription-revenue": {
        "task": "tutortrack.subscriptions.tasks.report_all_revenue",
        "schedule": crontab(hour=3, minute=40),
    },
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
