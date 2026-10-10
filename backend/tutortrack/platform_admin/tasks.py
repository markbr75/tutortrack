"""Operational metrics for alarms (E30 FR-30-3).

Every minute the platform figures are written to stdout in CloudWatch's embedded metric
format; CloudWatch Logs turns the lines into metrics (namespace ``TutorTrack``) without an
agent or API calls, and the alarms in ``infra/terraform/monitoring.tf`` watch them.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from celery import shared_task

NAMESPACE = "TutorTrack"


def emf_line(metrics: dict[str, float], dimensions: dict[str, str]) -> str:
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [list(dimensions)],
                        "Metrics": [{"Name": name, "Unit": "Count"} for name in metrics],
                    }
                ],
            },
            **dimensions,
            **metrics,
        }
    )


@shared_task(name="tutortrack.platform_admin.tasks.emit_metrics")
def emit_metrics(environment: str = "") -> dict[str, Any]:
    from django.conf import settings

    from . import selectors

    ops = selectors.operations()
    metrics = {
        "OutboxLagSeconds": ops["outbox_lag_seconds"],
        "OutboxPending": ops["outbox_pending"],
        "OutboxDeadLetters": ops["dead_letters"],
        "CeleryQueueDepth": sum(ops["queues"].values()),
        "PaymentWebhookBacklog": ops["payment_webhooks_unprocessed"],
        "BillingWebhookBacklog": ops["billing_webhooks_unprocessed"],
    }
    env = environment or str(settings.SENTRY_ENVIRONMENT)
    sys.stdout.write(emf_line(metrics, {"Environment": env}) + "\n")
    sys.stdout.flush()
    return metrics
