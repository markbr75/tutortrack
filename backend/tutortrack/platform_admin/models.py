"""Daily per-organisation facts for customer success and SaaS metrics (E30 Part 2).

Both tables are tenant data (RLS like any other): the nightly ``PlatformInsightsWorkflow``
writes one row per organisation per day inside that organisation's tenant context, and
only the platform console reads across organisations (BYPASSRLS connection).

* ``SubscriptionSnapshot``: the subscription that day (plan, status, seats, MRR in the
  billing currency). MRR movements, churn, trial conversion and cohorts are derived from
  consecutive snapshots (``platform_admin.metrics``).
* ``TenantHealthScore``: the health score and its components (``platform_admin.health``).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class SubscriptionSnapshot(TenantModel):
    date = models.DateField()
    plan_key = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=10, blank=True, default="")  # Subscription.Status
    interval = models.CharField(max_length=5, blank=True, default="")
    currency = models.CharField(max_length=3, blank=True, default="")
    seats = models.PositiveIntegerField(default=0)
    mrr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    signed_up_on = models.DateField(null=True, blank=True)  # the organisation's creation

    class Meta(TenantModel.Meta):
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "date"], name="subscription_snap_day")
        ]
        indexes = [models.Index(fields=["date", "currency"], name="subscription_snap_date")]


class TenantHealthScore(TenantModel):
    class Risk(models.TextChoices):
        HEALTHY = "healthy", _("Healthy")
        WATCH = "watch", _("Watch")
        AT_RISK = "at_risk", _("At risk")

    date = models.DateField()
    score = models.PositiveSmallIntegerField()
    risk = models.CharField(max_length=8, choices=Risk.choices)
    components = models.JSONField(default=dict)  # {name: 0-100 or None}
    inputs = models.JSONField(default=dict)  # the raw counts behind the components
    alerted_at = models.DateTimeField(null=True, blank=True)  # churn-risk alert sent

    class Meta(TenantModel.Meta):
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "date"], name="health_score_day")
        ]
        indexes = [models.Index(fields=["date", "risk"], name="health_score_date_risk")]
