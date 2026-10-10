# Alerts

| Alarm | Meaning | First steps |
|---|---|---|
| `api-5xx-rate` (paging) | > 1% of requests fail for 5 minutes | Sentry for the error; recent deploy? → [rollback.md](rollback.md); DB health |
| `api-latency-p95` | p95 above 1.5s for 10 minutes | RDS Performance Insights for slow queries; web task CPU |
| `unhealthy-web` (paging) | Web tasks fail health checks | ECS events; `/readyz` (DB, Redis); recent deploy |
| `outbox-lag` (paging) | Events more than 60s behind | Is `worker` running? Queue depth; one failing subscriber looping? |
| `dead-letters` | An event failed every retry | Console → Operations → dead letters: read the error, fix, replay |
| `payment-webhooks` (paging) | Stripe Connect webhooks not processed | Worker logs for `payments.tasks.process_webhook`; Stripe status |
| `billing-webhooks` | Stripe Billing webhooks not processed | Worker logs for `subscriptions.tasks.process_billing_event` |
| `celery-queue-depth` | More than 1,000 jobs waiting | Scale `worker`; look for a task storm in logs |
| `db-cpu`, `db-free-storage` | Database under pressure | Performance Insights; storage autoscaling headroom |

Missing application metrics count as breaching: if every `TutorTrack/*` alarm fires at
once, check that `beat` is running.
