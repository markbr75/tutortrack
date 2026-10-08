from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tutortrack.core.api.serializers import MoneySerializerField
from tutortrack.core.money import CurrencyMismatch, Money, minor_units, sum_money

from .factories import WidgetFactory
from .testapp.models import Widget

CURRENCIES = ["GBP", "USD", "EUR", "JPY", "KWD", "AUD"]

amounts = st.decimals(
    min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=4, allow_nan=False
)
ratios = st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=12).filter(
    lambda r: sum(r) > 0
)


@given(amount=amounts, currency=st.sampled_from(CURRENCIES), weights=ratios)
def test_allocate_never_loses_or_creates_minor_units(amount, currency, weights):
    money = Money(amount, currency)
    parts = money.allocate(weights)
    assert len(parts) == len(weights)
    assert sum_money(parts, currency) == money.round_to_minor()
    assert all(p.is_rounded() for p in parts)
    # zero-weight parts get nothing
    assert all(p.is_zero() for p, w in zip(parts, weights, strict=True) if w == 0)


@given(amount=amounts, weights=ratios)
def test_allocate_parts_differ_by_at_most_one_minor_unit_from_exact(amount, weights):
    money = Money(amount, "GBP")
    total = sum(weights)
    for part, weight in zip(money.allocate(weights), weights, strict=True):
        exact = money.round_to_minor().amount * weight / total
        assert abs(part.amount - exact) < Decimal("0.01")


def test_allocate_is_deterministic_for_ties():
    assert [p.amount for p in Money("100", "GBP").allocate([1, 1, 1])] == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("2.345", "GBP", "2.35"),  # half-up, not banker's rounding
        ("2.355", "GBP", "2.36"),
        ("-2.345", "GBP", "-2.35"),
        ("1234.5", "JPY", "1235"),  # 0 decimal places
        ("1.2345", "KWD", "1.235"),  # 3 decimal places
    ],
)
def test_round_to_minor_is_half_up(amount, currency, expected):
    assert Money(amount, currency).round_to_minor().amount == Decimal(expected)


def test_minor_units():
    assert minor_units("GBP") == 2
    assert minor_units("JPY") == 0
    assert minor_units("KWD") == 3


def test_arithmetic_and_comparisons():
    a, b = Money("10.50", "GBP"), Money("2.25", "GBP")
    assert a + b == Money("12.75", "GBP")
    assert a - b == Money("8.25", "GBP")
    assert a * 2 == Money("21.00", "GBP")
    assert 3 * b == Money("6.75", "GBP")
    assert (a / 3).round_to_minor() == Money("3.50", "GBP")
    assert -a == Money("-10.50", "GBP")
    assert b < a
    assert sum([a, b]) == Money("12.75", "GBP")


def test_rejects_floats_and_mixed_currencies():
    with pytest.raises(TypeError):
        Money(1.5, "GBP")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money("1", "GBP") * 1.5  # type: ignore[operator]
    with pytest.raises(CurrencyMismatch):
        Money("1", "GBP") + Money("1", "USD")
    with pytest.raises(ValueError, match="Unknown currency"):
        Money("1", "XXZ")


def test_to_minor_and_from_minor_round_trip():
    assert Money("12.34", "GBP").to_minor() == 1234
    assert Money.from_minor(1234, "GBP") == Money("12.34", "GBP")
    assert Money.from_minor(500, "JPY") == Money("500", "JPY")


def test_format_is_locale_aware():
    assert Money("1234.5", "GBP").format("en_GB") == "£1,234.50"
    assert Money("1234.5", "USD").format("en_US") == "$1,234.50"


# --- model fields -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_money_field_round_trips_through_the_database(tenant):
    widget = Widget.objects.create(
        name="Maths", price=Money("40.00", "GBP"), hourly_rate=Money("33.3333", "GBP")
    )
    fresh = Widget.objects.get(pk=widget.pk)
    assert fresh.price == Money("40.00", "GBP")
    assert fresh.hourly_rate == Money("33.3333", "GBP")
    assert fresh.price_amount == Decimal("40.00")
    assert Widget.objects.filter(price=Money("40", "GBP")).count() == 1
    assert Widget.objects.filter(price_amount__gt=10).count() == 1


@pytest.mark.django_db
def test_money_field_refuses_to_silently_round(tenant):
    widget = WidgetFactory(organisation=tenant)
    widget.price = Money("10.005", "GBP")
    with pytest.raises(ValueError, match="round it before saving"):
        widget.save()


@pytest.mark.django_db
def test_money_field_rejects_a_different_currency(tenant):
    widget = WidgetFactory(organisation=tenant, currency="GBP")
    with pytest.raises(CurrencyMismatch):
        widget.price = Money("10", "USD")


def test_money_field_requires_money_instances():
    with pytest.raises(TypeError):
        Widget(name="x", price=Decimal("10"))


# --- serializer field ---------------------------------------------------------------------------


def test_money_serializer_field_round_trip():
    field = MoneySerializerField(decimal_places=2)
    assert field.to_representation(Money("40", "GBP")) == {"amount": "40.00", "currency": "GBP"}
    assert field.to_internal_value({"amount": "12.5", "currency": "gbp"}) == Money("12.5", "GBP")


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": 12.5, "currency": "GBP"},  # float
        {"amount": "12.555", "currency": "GBP"},  # too many places
        {"amount": "abc", "currency": "GBP"},
        {"amount": "1", "currency": "ZZZ"},
        "12.50",
    ],
)
def test_money_serializer_field_rejects_bad_input(payload):
    from rest_framework.exceptions import ValidationError

    with pytest.raises(ValidationError):
        MoneySerializerField(decimal_places=2).to_internal_value(payload)
