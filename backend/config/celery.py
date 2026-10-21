"""Celery application. Tasks live in each app's ``tasks.py`` and are autodiscovered."""

import os

from celery import Celery
from kombu import Exchange, Queue

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

# Every queue is declared, so a worker started without -Q (local development) consumes them all;
# deployed workers still pick theirs with -Q.
QUEUES = ("default", "outbox", "notifications", "billing", "integrations", "imports", "reports")
# Own exchange and routing key per queue, as Celery creates them on demand (a shared key would
# copy each task into every queue).
app.conf.task_queues = [Queue(name, Exchange(name), routing_key=name) for name in QUEUES]


def _load_beat_schedule() -> None:
    from config.celery_schedule import BEAT_SCHEDULE

    app.conf.beat_schedule = BEAT_SCHEDULE


app.on_after_configure.connect(lambda sender, **_: _load_beat_schedule(), weak=False)
