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

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.ids import new_id
from tutortrack.core.models import TenantModel


class SubscriptionSnapshot(TenantModel):
    date = models.DateField()
    plan_key = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=10, blank=True, default="")  # Subscription.Status
    interval = models.CharField(max_length=5, blank=True, default="")
    currency = models.CharField(max_length=3, blank=True, default="")
    seats = models.PositiveIntegerField(default=0)
    mrr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # G6: the revenue-share part of ``mrr`` (share x payments processed, last 30 days).
    revenue_share_mrr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
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


# --- notify customers (G6, FR-29-9): platform data, not tenant data ----------------------------


class CustomerNotice(models.Model):
    """A notice platform staff send to organisations' owners and admins (breach, security,
    service or legal). Sent once; each organisation's delivery is recorded."""

    class Kind(models.TextChoices):
        BREACH = "breach", _("Personal data breach")
        SECURITY = "security", _("Security incident")
        SERVICE = "service", _("Service incident")
        LEGAL = "legal", _("Legal change")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SENDING = "sending", _("Sending")
        SENT = "sent", _("Sent")

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    template = models.CharField(max_length=20)
    subject = models.CharField(max_length=300)
    body = models.TextField()
    variables = models.JSONField(default=dict, blank=True)
    organisation_ids = models.JSONField(default=list, blank=True)  # empty: every open one
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    reason = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    organisations_count = models.PositiveIntegerField(default=0)
    recipients_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.subject


class CustomerNoticeDelivery(models.Model):
    notice = models.ForeignKey(CustomerNotice, on_delete=models.CASCADE, related_name="deliveries")
    organisation = models.ForeignKey(
        "tenancy.Organisation", on_delete=models.CASCADE, related_name="+"
    )
    recipients = models.PositiveIntegerField(default=0)
    delivered_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notice", "organisation"], name="customer_notice_delivery_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.notice_id} -> {self.organisation_id}"
