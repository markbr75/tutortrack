"""Celery application. Tasks live in each app's ``tasks.py`` and are autodiscovered."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("tutortrack")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Queues (see docs/02-architecture.md §9). Routing is by task-name prefix.
app.conf.task_routes = {
    "tutortrack.core.events.*": {"queue": "outbox"},
    "tutortrack.comms.*": {"queue": "notifications"},
    "tutortrack.billing.*": {"queue": "billing"},
    "tutortrack.payments.*": {"queue": "billing"},
    "tutortrack.payroll.*": {"queue": "billing"},
    "tutortrack.integrations.*": {"queue": "integrations"},
    "tutortrack.migration.*": {"queue": "imports"},
    "tutortrack.reporting.*": {"queue": "reports"},
}


def _load_beat_schedule() -> None:
    from config.celery_schedule import BEAT_SCHEDULE

    app.conf.beat_schedule = BEAT_SCHEDULE


app.on_after_configure.connect(lambda sender, **_: _load_beat_schedule(), weak=False)
