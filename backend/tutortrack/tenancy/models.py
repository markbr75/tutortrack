"""Organisations (tenants), branches, domains and reserved slugs (E02).

``Organisation`` and ``OrganisationDomain`` are platform routing tables: they are read before
a tenant is known (tenant resolution), so they are not ``TenantModel``s and have no RLS
policy. Everything an organisation *owns* (branches, settings, memberships...) is.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField
from tutortrack.core.ids import new_id
from tutortrack.core.models import ArchivableModel, TimeStampedModel


class Organisation(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial", _("Trial")
        ACTIVE = "active", _("Active")
        PAST_DUE = "past_due", _("Past due")
        SUSPENDED = "suspended", _("Suspended")
        CANCELLED = "cancelled", _("Cancelled")

    class BusinessType(models.TextChoices):
        SOLE_TRADER = "sole_trader", _("Sole trader")
        TEAM = "team", _("Small team")
        AGENCY = "agency", _("Agency")
        CENTRE = "centre", _("Tuition centre")
        ONLINE = "online", _("Online school")

    class Mode(models.TextChoices):
        SOLO = "solo", _("Solo")
        MULTI = "multi", _("Multi-user")

    class Region(models.TextChoices):
        UK = "uk", _("United Kingdom")
        EU = "eu", _("European Union")
        US = "us", _("United States")
        AU = "au", _("Australia")

    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Monday")
        TUESDAY = 1, _("Tuesday")
        WEDNESDAY = 2, _("Wednesday")
        THURSDAY = 3, _("Thursday")
        FRIDAY = 4, _("Friday")
        SATURDAY = 5, _("Saturday")
        SUNDAY = 6, _("Sunday")

    class DateFormat(models.TextChoices):
        LOCALE = "locale", _("Locale default")
        DMY = "dd/MM/yyyy", "31/12/2026"
        MDY = "MM/dd/yyyy", "12/31/2026"
        ISO = "yyyy-MM-dd", "2026-12-31"

    class TimeFormat(models.TextChoices):
        LOCALE = "locale", _("Locale default")
        H24 = "24h", _("24-hour")
        H12 = "12h", _("12-hour")

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True, default="")
    slug = models.SlugField(max_length=63, unique=True)
    business_type = models.CharField(
        max_length=20, choices=BusinessType.choices, default=BusinessType.SOLE_TRADER
    )
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.SOLO)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)

    country = models.CharField(max_length=2, default="GB", help_text="ISO 3166-1 alpha-2")
    region = models.CharField(max_length=2, choices=Region.choices, default=Region.UK)
    default_currency = CurrencyField(default="GBP")
    timezone = models.CharField(max_length=64, default="Europe/London")
    locale = models.CharField(max_length=10, default="en-GB")

    logo = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    primary_colour = models.CharField(max_length=7, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    address = models.JSONField(default=dict, blank=True)
    company_number = models.CharField(max_length=50, blank=True, default="")
    vat_number = models.CharField(max_length=50, blank=True, default="")
    tax_number = models.CharField(max_length=50, blank=True, default="")
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=4)
    week_start_day = models.PositiveSmallIntegerField(
        choices=Weekday.choices, default=Weekday.MONDAY
    )
    date_format = models.CharField(
        max_length=12, choices=DateFormat.choices, default=DateFormat.LOCALE
    )
    time_format = models.CharField(
        max_length=8, choices=TimeFormat.choices, default=TimeFormat.LOCALE
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    has_demo_data = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.CharField(max_length=500, blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(fiscal_year_start_month__gte=1, fiscal_year_start_month__lte=12),
                name="org_fiscal_month_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_operational(self) -> bool:
        """Whether background jobs should run for this organisation."""
        return self.status in {self.Status.TRIAL, self.Status.ACTIVE, self.Status.PAST_DUE}

    @property
    def is_suspended(self) -> bool:
        return self.status == self.Status.SUSPENDED

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CANCELLED

    @property
    def base_url(self) -> str:
        """Where the organisation's admin app lives, e.g. https://acme.tutortrack.app."""
        return str(settings.TENANT_URL_TEMPLATE).format(
            slug=self.slug, domain=settings.TENANT_BASE_DOMAIN
        )


class OrganisationDomain(TimeStampedModel):
    """A hostname that routes to an organisation.

    * ``subdomain`` rows with ``redirect_until`` are former slugs: requests are redirected
      to the current slug for 90 days after a rename (FR-02-1).
    * ``custom`` rows are tenant custom domains (verification and TLS arrive in E24).
    """

    class Type(models.TextChoices):
        SUBDOMAIN = "subdomain", _("Subdomain")
        CUSTOM = "custom", _("Custom domain")

    class SSLStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField(max_length=253, unique=True)
    type = models.CharField(max_length=10, choices=Type.choices)
    verified_at = models.DateTimeField(null=True, blank=True)
    ssl_status = models.CharField(
        max_length=10, choices=SSLStatus.choices, default=SSLStatus.PENDING
    )
    redirect_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["hostname"]

    def __str__(self) -> str:
        return self.hostname


class ReservedSlug(models.Model):
    """Subdomains no organisation may claim (www, app, api, admin...)."""

    slug = models.SlugField(max_length=63, primary_key=True)
    reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug


class Branch(ArchivableModel):
    """A sub-unit of an organisation (location, brand or region). Every organisation has
    exactly one default branch, created at signup (FR-02-2)."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    address = models.JSONField(default=dict, blank=True)
    timezone = models.CharField(max_length=64)
    currency = CurrencyField()
    locale = models.CharField(max_length=10)
    tax_settings = models.JSONField(default=dict, blank=True)
    branding = models.JSONField(default=dict, blank=True)
    email_sender_name = models.CharField(max_length=100, blank=True, default="")
    email_sender_address = models.EmailField(blank=True, default="")
    invoice_prefix = models.CharField(max_length=10, blank=True, default="")
    is_default = models.BooleanField(default=False)

    class Meta(ArchivableModel.Meta):
        ordering = ["-is_default", "name"]
        verbose_name_plural = "branches"
        constraints = [
            models.UniqueConstraint(fields=["organisation", "code"], name="branch_code_unique"),
            models.UniqueConstraint(
                fields=["organisation"],
                condition=Q(is_default=True),
                name="branch_one_default_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name
