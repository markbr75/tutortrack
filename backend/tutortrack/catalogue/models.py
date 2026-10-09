"""What the business sells and how it is priced (E06)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField, RateField
from tutortrack.core.models import TenantModel


class OrderedModel(TenantModel):
    order = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        abstract = True


class Category(OrderedModel):
    """Optional grouping of subjects and services (Academic, Music, Test Prep...)."""

    name = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        ordering = ["order", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["organisation", "name"], name="category_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class Subject(OrderedModel):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="subjects"
    )
    exam_boards = models.JSONField(default=list, blank=True)  # ["AQA", "Edexcel"]

    class Meta(TenantModel.Meta):
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "name"], name="subject_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class Level(OrderedModel):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="levels")
    name = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        ordering = ["subject", "order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["subject", "name"], name="level_name_unique")
        ]

    def __str__(self) -> str:
        return f"{self.subject.name} {self.name}"


class TaxRate(TenantModel):
    name = models.CharField(max_length=100)
    percent = models.DecimalField(max_digits=6, decimal_places=3)
    country = models.CharField(max_length=2, blank=True, default="")
    region = models.CharField(max_length=50, blank=True, default="")
    is_default = models.BooleanField(default=False)
    exempt_reason = models.CharField(max_length=100, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation"],
                condition=models.Q(is_default=True),
                name="one_default_tax_rate",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.percent}%)"


class Service(TenantModel):
    class Format(models.TextChoices):
        ONE_TO_ONE = "one_to_one", _("One to one")
        SMALL_GROUP = "small_group", _("Small group")
        CLASS = "class", _("Class")

    class DeliveryMode(models.TextChoices):
        IN_PERSON = "in_person", _("In person")
        ONLINE = "online", _("Online")
        HYBRID = "hybrid", _("Hybrid")

    class PricingUnit(models.TextChoices):
        PER_HOUR = "per_hour", _("Per hour")
        PER_LESSON = "per_lesson", _("Per lesson")
        PER_STUDENT_PER_LESSON = "per_student_per_lesson", _("Per student per lesson")
        PER_MONTH = "per_month", _("Per month")
        PER_TERM = "per_term", _("Per term")

    class PayUnit(models.TextChoices):
        PER_HOUR = "per_hour", _("Per hour")
        PER_LESSON = "per_lesson", _("Per lesson")

    class GroupCharge(models.TextChoices):
        PER_STUDENT = "per_student", _("Each student pays the rate")
        SPLIT = "split", _("The rate is split between students")

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")  # internal
    public_description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="services"
    )
    subject = models.ForeignKey(
        Subject, null=True, blank=True, on_delete=models.PROTECT, related_name="services"
    )
    level = models.ForeignKey(
        Level, null=True, blank=True, on_delete=models.PROTECT, related_name="services"
    )
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.ONE_TO_ONE)
    max_students = models.PositiveIntegerField(default=1)
    delivery_mode = models.CharField(
        max_length=10, choices=DeliveryMode.choices, default=DeliveryMode.IN_PERSON
    )
    default_duration_minutes = models.PositiveIntegerField(default=60)
    allowed_durations = models.JSONField(default=list, blank=True)  # minutes; [] = any
    pricing_unit = models.CharField(
        max_length=25, choices=PricingUnit.choices, default=PricingUnit.PER_HOUR
    )
    group_charge = models.CharField(
        max_length=12, choices=GroupCharge.choices, default=GroupCharge.PER_STUDENT
    )
    currency = CurrencyField()
    charge_rate = RateField()
    pay_unit = models.CharField(max_length=10, choices=PayUnit.choices, default=PayUnit.PER_HOUR)
    pay_rate = RateField(null=True, blank=True)
    pay_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_rate = models.ForeignKey(
        TaxRate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revenue_account_code = models.CharField(max_length=30, blank=True, default="")
    branches = models.ManyToManyField("tenancy.Branch", blank=True, related_name="+")  # [] = all
    bookable_online = models.BooleanField(default=False)
    colour = models.CharField(max_length=7, default="#2563eb")
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pay_rate_amount__isnull=True)
                | models.Q(pay_percent__isnull=True),
                name="service_pay_rate_or_percent",
            ),
            models.CheckConstraint(
                condition=models.Q(charge_rate_amount__gte=0), name="service_charge_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ServicePrice(TenantModel):
    """Prices in another currency for multi-currency organisations (FR-06-12)."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="prices")
    currency = CurrencyField()
    charge_rate = RateField()
    pay_rate = RateField(null=True, blank=True)
    pay_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["service", "currency"], name="service_price_currency_unique"
            )
        ]


class Location(TenantModel):
    class Type(models.TextChoices):
        CENTRE = "centre", _("Centre")
        CLIENT_HOME = "client_home", _("Client's home")
        TUTOR_HOME = "tutor_home", _("Tutor's home")
        SCHOOL = "school", _("School")
        ONLINE = "online", _("Online")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=150)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.CENTRE)
    address = models.ForeignKey(
        "people.Address", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    timezone = models.CharField(max_length=64, blank=True, default="")
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    capacity = models.PositiveIntegerField(null=True, blank=True)
    opening_hours = models.JSONField(default=dict, blank=True)  # same shape as business hours
    online_url = models.URLField(blank=True, default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Room(TenantModel):
    """Stub for Phase 2 (E06-T10): rooms inside a location."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=100)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["location", "name"]

    def __str__(self) -> str:
        return self.name


class Product(TenantModel):
    """Ad hoc charges: registration fees, materials, exam entries... (FR-06-9)."""

    class Category(models.TextChoices):
        REGISTRATION = "registration", _("Registration fee")
        MATERIALS = "materials", _("Materials")
        BOOKS = "books", _("Books")
        EXAM_ENTRY = "exam_entry", _("Exam entry")
        LATE_CANCEL = "late_cancel", _("Late cancellation fee")
        TRAVEL = "travel", _("Travel fee")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.OTHER)
    currency = CurrencyField()
    price = MoneyField()
    tax_rate = models.ForeignKey(
        TaxRate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    account_code = models.CharField(max_length=30, blank=True, default="")
    tutor_share_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PackageTemplate(TenantModel):
    """Prepaid bundles of hours, lessons or credit (FR-06-8). Sales live in E10."""

    class Quantity(models.TextChoices):
        HOURS = "hours", _("Hours")
        LESSONS = "lessons", _("Lessons")
        CREDIT = "credit", _("Credit")

    class Refund(models.TextChoices):
        NONE = "none", _("Not refundable")
        UNUSED_PRO_RATA = "unused_pro_rata", _("Unused part refundable")
        FULL = "full", _("Fully refundable before first use")

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    services = models.ManyToManyField(Service, blank=True, related_name="+")  # [] = any
    quantity_type = models.CharField(max_length=8, choices=Quantity.choices)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    currency = CurrencyField()
    price = MoneyField()
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    tax_rate = models.ForeignKey(
        TaxRate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    transferable_between_siblings = models.BooleanField(default=False)
    refund_policy = models.CharField(max_length=16, choices=Refund.choices, default=Refund.NONE)
    bookable_online = models.BooleanField(default=False)
    auto_renew = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="package_quantity_gt0"),
            models.CheckConstraint(
                condition=models.Q(price_amount__gte=0), name="package_price_gte0"
            ),
        ]

    def __str__(self) -> str:
        return self.name
