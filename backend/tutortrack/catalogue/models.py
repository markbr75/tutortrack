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
    """A bookable room inside a location (FR-06-10, E06-T10). E08 prevents room clashes
    with a database exclusion constraint on lessons."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True, default="")
    capacity = models.PositiveIntegerField(null=True, blank=True)
    bookable = models.BooleanField(default=True)  # offered to online booking (E08-T14)
    colour = models.CharField(max_length=7, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["location", "name"]
        constraints = [
            models.UniqueConstraint(fields=["location", "name"], name="room_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class RoomResource(TenantModel):
    """Equipment in a room (whiteboard, piano, 6 laptops)."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="resources")
    name = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["room", "name"], name="room_resource_unique")
        ]

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


# --- pay tiers and tutor rates (FR-06-5, E06-T07) ------------------------------------------------


class PayTier(TenantModel):
    """A wage tier (Associate, Senior, Expert). Higher ``order`` = more senior."""

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "name"], name="pay_tier_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class ServiceTierRate(TenantModel):
    """A service's pay rate (and optionally charge rate) for one tier, in the service's
    currency."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="tier_rates")
    tier = models.ForeignKey(PayTier, on_delete=models.CASCADE, related_name="service_rates")
    currency = CurrencyField()
    pay_rate = RateField(null=True, blank=True)
    charge_rate = RateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["service", "tier"], name="service_tier_rate_unique"),
            models.CheckConstraint(
                condition=models.Q(pay_rate_amount__isnull=False)
                | models.Q(charge_rate_amount__isnull=False),
                name="service_tier_rate_has_rate",
            ),
        ]


class TutorPayTierAssignment(TenantModel):
    """A tutor's tier from ``effective_from`` (until their next assignment)."""

    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="pay_tier_assignments"
    )
    tier = models.ForeignKey(PayTier, on_delete=models.PROTECT, related_name="assignments")
    effective_from = models.DateField()
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["tutor", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["tutor", "effective_from"], name="tutor_tier_effective_unique"
            )
        ]


class TutorServiceRate(TenantModel):
    """A tutor's personal pay rate for a service (beats their tier's rate)."""

    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="service_rates"
    )
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="tutor_rates")
    currency = CurrencyField()
    pay_rate = RateField()

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tutor", "service"], name="tutor_service_rate_unique")
        ]


# --- holidays and premiums (FR-06-6, E06-T08) ----------------------------------------------------


class HolidayCalendar(TenantModel):
    """Public holidays for the organisation (``branch`` empty) or one branch. Used by
    premium rules and by lesson series that skip holidays (E08)."""

    name = models.CharField(max_length=100)
    country = models.CharField(max_length=2, blank=True, default="")
    region = models.CharField(max_length=50, blank=True, default="")
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    skip_lessons = models.BooleanField(default=True)  # series that skip holidays skip these
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Holiday(TenantModel):
    calendar = models.ForeignKey(HolidayCalendar, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["calendar", "date"], name="holiday_date_unique")
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.date}"


class AdjustmentRule(TenantModel):
    """Shared fields of premium and discount rules. Matching rules are taken in
    ``priority`` order (highest first): a non-stackable rule that comes first applies
    alone, otherwise every matching stackable rule applies."""

    name = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    stackable = models.BooleanField(default=True)
    services = models.JSONField(default=list, blank=True)  # service ids; [] = all
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        abstract = True
        ordering = ["-priority", "name"]

    def __str__(self) -> str:
        return self.name


class PremiumRule(AdjustmentRule):
    """A surcharge (weekend, evening, holiday, short notice, travel, group...) on the
    charge and/or the pay (FR-06-6)."""

    class Delivery(models.TextChoices):
        ANY = "any", _("In person or online")
        IN_PERSON = "in_person", _("In person")
        ONLINE = "online", _("Online")

    weekdays = models.JSONField(default=list, blank=True)  # Monday = 0; [] = every day
    time_from = models.TimeField(null=True, blank=True)  # local start-time window
    time_to = models.TimeField(null=True, blank=True)
    public_holidays = models.BooleanField(default=False)  # only on holiday dates
    short_notice_hours = models.PositiveIntegerField(null=True, blank=True)
    location_types = models.JSONField(default=list, blank=True)  # Location.Type values
    delivery = models.CharField(max_length=10, choices=Delivery.choices, default=Delivery.ANY)
    subjects = models.JSONField(default=list, blank=True)  # subject ids
    levels = models.JSONField(default=list, blank=True)  # level ids
    min_students = models.PositiveIntegerField(null=True, blank=True)
    max_students = models.PositiveIntegerField(null=True, blank=True)
    currency = CurrencyField(blank=True, default="")  # of the fixed amounts
    charge_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    charge_fixed = RateField(null=True, blank=True)
    pay_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    pay_fixed = RateField(null=True, blank=True)

    class Meta(AdjustmentRule.Meta):
        pass


# --- discounts, promo codes and price lists (FR-06-7, FR-06-11, E06-T09) -------------------------


class DiscountRule(AdjustmentRule):
    class Kind(models.TextChoices):
        SIBLING = "sibling", _("Sibling")
        VOLUME = "volume", _("Volume")
        FIRST_LESSON = "first_lesson", _("First lesson / trial")
        CLIENT = "client", _("Client discount")
        SCHOLARSHIP = "scholarship", _("Scholarship / bursary")
        PROMO = "promo", _("Promo code")
        MULTI_CLASS = "multi_class", _("Several classes in a term")

    kind = models.CharField(max_length=12, choices=Kind.choices)
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    currency = CurrencyField(blank=True, default="")
    fixed_amount = RateField(null=True, blank=True)  # off each lesson
    fixed_price = RateField(null=True, blank=True)  # the lesson costs this (trial price)
    sibling_from = models.PositiveIntegerField(default=2)  # 2 = second child onwards
    volume_min_lessons = models.PositiveIntegerField(null=True, blank=True)  # per month
    min_classes = models.PositiveIntegerField(null=True, blank=True)  # multi_class: per term
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )

    class Meta(AdjustmentRule.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(percent__isnull=False)
                | models.Q(fixed_amount_amount__isnull=False)
                | models.Q(fixed_price_amount__isnull=False),
                name="discount_has_effect",
            )
        ]


class PromoCode(TenantModel):
    """A code entered at online booking (E08-T14) that applies a promo discount."""

    code = models.CharField(max_length=40)
    discount = models.ForeignKey(DiscountRule, on_delete=models.CASCADE, related_name="promo_codes")
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    max_uses_per_client = models.PositiveIntegerField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    new_clients_only = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "code"], name="promo_code_unique")
        ]

    def __str__(self) -> str:
        return self.code


class PromoRedemption(TenantModel):
    promo_code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reference = models.CharField(max_length=100, blank=True, default="")  # e.g. a booking id

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["promo_code", "reference"], name="promo_redemption_unique"
            )
        ]


class PriceList(TenantModel):
    """Contract prices for specific clients (a school or local authority), FR-06-11."""

    name = models.CharField(max_length=150)
    currency = CurrencyField()
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PriceListItem(TenantModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="+")
    currency = CurrencyField()
    charge_rate = RateField()

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["price_list", "service"], name="price_list_item_unique")
        ]


class PriceListClient(TenantModel):
    """A client on a price list."""

    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="clients")
    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "client"], name="price_list_client_unique"
            )
        ]
