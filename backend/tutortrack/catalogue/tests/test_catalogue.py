"""E06-T01..T06: catalogue API, seeding, validation, quote API and isolation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tutortrack.catalogue import services
from tutortrack.catalogue.models import Level, Service, Subject, TaxRate
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people import services as people
from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory

from .factories import (
    LevelFactory,
    LocationFactory,
    ProductFactory,
    ServiceFactory,
    SubjectFactory,
    TaxRateFactory,
)

pytestmark = pytest.mark.django_db

S = "/api/v1/catalogue"


def api_as(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


@pytest.fixture
def admin_api(org):
    return api_as(org, "admin")


def gbp(amount):
    return {"amount": amount, "currency": "GBP"}


# --- seeding (FR-06-1, FR-06-3) ---------------------------------------------------------------


def test_new_organisation_gets_country_subjects_and_tax_rates():
    from tutortrack.tenancy.services import create_organisation

    result = create_organisation(name="Maple Tutors", owner=UserFactory(), country="US")
    org = getattr(result, "organisation", result)
    dispatch_batch()
    with tenant_context(org):
        names = set(Subject.objects.values_list("name", flat=True))
        assert {"Maths", "SAT", "ACT"} <= names
        assert "11+" not in names
        assert Level.objects.filter(subject__name="Maths", name="AP").exists()
        assert TaxRate.objects.get(is_default=True).name == "No sales tax"
        services.seed_catalogue("US")  # idempotent
        assert Subject.objects.filter(name="Maths").count() == 1


def test_uk_seed_has_exam_boards_and_vat_exempt_default(tenant):
    services.seed_catalogue("GB")
    maths = Subject.objects.get(name="Maths")
    assert "AQA" in maths.exam_boards
    assert list(maths.levels.values_list("name", flat=True))[:3] == ["KS1", "KS2", "KS3"]
    default = TaxRate.objects.get(is_default=True)
    assert (default.percent, default.exempt_reason) == (Decimal("0"), "VAT exempt private tuition")


# --- subjects and levels ----------------------------------------------------------------------


def test_subjects_with_levels_and_archiving(org, admin_api):
    created = admin_api.post(f"{S}/subjects", {"name": "Latin", "exam_boards": ["OCR", "OCR"]})
    assert created.status_code == 201, created.json()
    assert created.json()["exam_boards"] == ["OCR"]
    subject_id = created.json()["id"]
    level = admin_api.post(f"{S}/levels", {"subject": subject_id, "name": "GCSE"}, format="json")
    assert level.status_code == 201, level.json()
    listed = admin_api.get(f"{S}/subjects").json()
    [latin] = [x for x in listed if x["id"] == subject_id]
    assert [lvl["name"] for lvl in latin["levels"]] == ["GCSE"]

    admin_api.post(f"{S}/subjects/{subject_id}/archive")
    assert subject_id not in {x["id"] for x in admin_api.get(f"{S}/subjects").json()}
    archived = admin_api.get(f"{S}/subjects?include_archived=true").json()
    assert subject_id in {x["id"] for x in archived}
    with tenant_context(org):
        assert Level.objects.get(pk=level.json()["id"]).archived_at is not None
    admin_api.post(f"{S}/subjects/{subject_id}/restore")
    assert subject_id in {x["id"] for x in admin_api.get(f"{S}/subjects").json()}


def test_catalogue_is_read_only_without_manage(org):
    tutor = api_as(org, "tutor")
    assert tutor.get(f"{S}/subjects").status_code == 200
    assert tutor.post(f"{S}/subjects", {"name": "Art"}).status_code == 403


# --- tax rates --------------------------------------------------------------------------------


def test_only_one_default_tax_rate(org, admin_api):
    first = admin_api.post(
        f"{S}/tax-rates", {"name": "Exempt", "percent": "0", "is_default": True}
    ).json()
    second = admin_api.post(
        f"{S}/tax-rates", {"name": "VAT", "percent": "20", "is_default": True}
    ).json()
    rates = {r["id"]: r["is_default"] for r in admin_api.get(f"{S}/tax-rates").json()}
    assert rates == {first["id"]: False, second["id"]: True}
    bad = admin_api.post(f"{S}/tax-rates", {"name": "Odd", "percent": "120"})
    assert bad.status_code == 422


def test_tax_rates_need_rates_manage(org):
    coordinator = api_as(org, "coordinator")
    response = coordinator.post(f"{S}/tax-rates", {"name": "VAT", "percent": "20"})
    assert response.status_code == 403


# --- services (FR-06-2) -----------------------------------------------------------------------

SERVICE = {
    "name": "GCSE Maths 1:1",
    "pricing_unit": "per_hour",
    "charge_rate": gbp("40.00"),
    "pay_rate": gbp("25.00"),
    "default_duration_minutes": 60,
    "allowed_durations": [90, 60],
}


def test_create_service_with_rates_and_default_tax(org, admin_api):
    tax = TaxRateFactory(organisation=org, is_default=True)
    response = admin_api.post(f"{S}/services", SERVICE, format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["currency"] == "GBP"
    assert body["charge_rate"] == {"amount": "40.0000", "currency": "GBP"}
    assert body["allowed_durations"] == [60, 90]
    assert body["tax_rate"] == str(tax.pk)
    assert body["max_students"] == 1


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"pay_percent": "50"}, "pay_rate"),
        ({"pay_rate": {"amount": "25", "currency": "EUR"}}, "pay_rate"),
        ({"format": "small_group", "max_students": 1}, "max_students"),
        ({"allowed_durations": [30, 45]}, "default_duration_minutes"),
        ({"charge_rate": gbp("-1")}, "charge_rate"),
    ],
)
def test_service_validation(admin_api, change, field):
    response = admin_api.post(f"{S}/services", {**SERVICE, **change}, format="json")
    assert response.status_code == 422, response.json()
    assert field in response.json()["errors"]


def test_level_must_belong_to_subject(org, admin_api):
    level = LevelFactory(organisation=org)
    other = SubjectFactory(organisation=org)
    response = admin_api.post(
        f"{S}/services",
        {**SERVICE, "subject": str(other.pk), "level": str(level.pk)},
        format="json",
    )
    assert response.status_code == 422


def test_rate_change_flags_event(org):
    service = ServiceFactory(organisation=org)
    admin = api_as(org, "admin")
    response = admin.patch(
        f"{S}/services/{service.pk}", {"charge_rate": gbp("45.00")}, format="json"
    )
    assert response.status_code == 200, response.json()
    renamed = admin.patch(f"{S}/services/{service.pk}", {"name": "New name"}, format="json")
    assert renamed.status_code == 200
    with tenant_context(org):
        payloads = [
            e.payload["data"]
            for e in OutboxEvent.objects.filter(event_type="service.updated").order_by(
                "occurred_at"
            )
        ]
    assert payloads[0]["rate_changed"] is True
    assert payloads[1] == {"fields": ["name"], "rate_changed": False}


def test_rates_hidden_from_roles_without_view_permissions(org):
    service = ServiceFactory(organisation=org)
    tutor = api_as(org, "tutor").get(f"{S}/services/{service.pk}").json()
    assert "charge_rate" not in tutor
    assert "pay_rate" not in tutor
    coordinator = api_as(org, "coordinator").get(f"{S}/services/{service.pk}").json()
    assert "charge_rate" in coordinator
    assert "pay_rate" not in coordinator


def test_coordinator_cannot_change_rates(org):
    service = ServiceFactory(organisation=org)
    coordinator = api_as(org, "coordinator")
    response = coordinator.patch(
        f"{S}/services/{service.pk}", {"charge_rate": gbp("1.00")}, format="json"
    )
    assert response.status_code == 403


def test_price_in_another_currency_used_by_quote(org, admin_api):
    service = ServiceFactory(organisation=org)
    price = admin_api.post(
        f"{S}/services/{service.pk}/prices",
        {"charge_rate": {"amount": "50", "currency": "EUR"}, "pay_percent": "50"},
        format="json",
    )
    assert price.status_code == 200, price.json()
    student = StudentFactory(organisation=org)
    tutor = TutorProfileFactory(organisation=org)
    quote = admin_api.post(
        "/api/v1/rates/quote",
        {
            "service": str(service.pk),
            "duration_minutes": 90,
            "currency": "EUR",
            "students": [{"student": str(student.pk)}],
            "tutors": [{"tutor": str(tutor.pk)}],
        },
        format="json",
    )
    assert quote.status_code == 200, quote.json()
    body = quote.json()
    assert body["total_charge"] == {"amount": "75.00", "currency": "EUR"}
    assert body["total_pay"] == {"amount": "37.50", "currency": "EUR"}
    assert body["charges"][0]["client_id"] == str(student.client_id)


# --- quote API (FR-06-4) ----------------------------------------------------------------------


def test_quote_with_job_rate_and_trace(org, admin_api):
    service = ServiceFactory(organisation=org)
    student = StudentFactory(organisation=org)
    response = admin_api.post(
        "/api/v1/rates/quote",
        {
            "service": str(service.pk),
            "starts_at": "2026-11-02T16:00:00Z",
            "ends_at": "2026-11-02T17:30:00Z",
            "job_charge_rate": gbp("42.00"),
            "students": [{"student": str(student.pk)}],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    [line] = response.json()["charges"]
    assert line["amount"] == {"amount": "63.00", "currency": "GBP"}
    assert line["trace"] == ["job rate £42.00/h", "90 minutes"]


def test_quote_hides_sides_by_permission(org):
    service = ServiceFactory(organisation=org)
    student = StudentFactory(organisation=org)
    body = {
        "service": str(service.pk),
        "duration_minutes": 60,
        "students": [{"student": str(student.pk)}],
    }
    coordinator = api_as(org, "coordinator").post("/api/v1/rates/quote", body, format="json").json()
    assert "charges" in coordinator
    assert "pay" not in coordinator


def test_quote_unknown_or_foreign_student_is_404(org, other_org, admin_api):
    service = ServiceFactory(organisation=org)
    theirs = StudentFactory(organisation=other_org)
    response = admin_api.post(
        "/api/v1/rates/quote",
        {
            "service": str(service.pk),
            "duration_minutes": 60,
            "students": [{"student": str(theirs.pk)}],
        },
        format="json",
    )
    assert response.status_code == 404


def test_quote_needs_duration(org, admin_api):
    service = ServiceFactory(organisation=org)
    student = StudentFactory(organisation=org)
    response = admin_api.post(
        "/api/v1/rates/quote",
        {"service": str(service.pk), "students": [{"student": str(student.pk)}]},
        format="json",
    )
    assert response.status_code == 400


# --- locations, products, packages ------------------------------------------------------------


def test_location_with_address(org, admin_api):
    response = admin_api.post(
        f"{S}/locations",
        {
            "name": "Leeds Centre",
            "type": "centre",
            "address_input": {"line1": "1 Park Row", "city": "Leeds"},
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["address"]["city"] == "Leeds"
    online = admin_api.post(
        f"{S}/locations",
        {"name": "Zoom", "type": "online", "address_input": {"line1": "x"}},
        format="json",
    )
    assert online.status_code == 422


def test_products_and_packages(org, admin_api):
    product = admin_api.post(
        f"{S}/products",
        {"name": "Registration", "category": "registration", "price": gbp("30.00")},
        format="json",
    )
    assert product.status_code == 201, product.json()
    assert product.json()["currency"] == "GBP"
    service = ServiceFactory(organisation=org)
    package = admin_api.post(
        f"{S}/packages",
        {
            "name": "10 hours",
            "quantity_type": "hours",
            "quantity": "10",
            "price": gbp("380.00"),
            "validity_days": 180,
            "services": [str(service.pk)],
        },
        format="json",
    )
    assert package.status_code == 201, package.json()
    both = admin_api.post(
        f"{S}/packages",
        {
            "name": "Bad",
            "quantity_type": "lessons",
            "quantity": "5",
            "price": gbp("100.00"),
            "validity_days": 30,
            "valid_until": "2027-01-01",
        },
        format="json",
    )
    assert both.status_code == 422
    negative = admin_api.post(
        f"{S}/products", {"name": "Refund", "price": gbp("-5.00")}, format="json"
    )
    assert negative.status_code == 422


# --- tutor subjects link to the catalogue (E05 follow-up) -------------------------------------


def test_tutor_subjects_link_to_catalogue(org, tenant):
    maths = SubjectFactory(organisation=org, name="Maths")
    gcse = LevelFactory(organisation=org, subject=maths, name="GCSE")
    tutor = TutorProfileFactory(organisation=org)
    linked, free = people.set_tutor_subjects(
        tutor, [{"subject": "maths", "level": "gcse"}, {"subject": "Origami"}]
    )
    assert (linked.catalogue_subject, linked.catalogue_level) == (maths, gcse)
    assert free.catalogue_subject is None
    [by_id] = people.set_tutor_subjects(tutor, [{"level_id": str(gcse.pk)}])
    assert (by_id.subject, by_id.level, by_id.catalogue_level) == ("Maths", "GCSE", gcse)


# --- isolation ----------------------------------------------------------------------------------


class TestServiceIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/services"

    def make_object(self, organisation):
        return ServiceFactory(organisation=organisation)


class TestLocationIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/locations"

    def make_object(self, organisation):
        return LocationFactory(organisation=organisation)


class TestProductIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/products"

    def make_object(self, organisation):
        return ProductFactory(organisation=organisation)


class TestSubjectIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/subjects"

    def make_object(self, organisation):
        return SubjectFactory(organisation=organisation)


class TestTaxRateIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/tax-rates"

    def make_object(self, organisation):
        return TaxRateFactory(organisation=organisation)


def test_service_model_defaults(org, tenant):
    service = ServiceFactory(organisation=org)
    assert service.charge_rate.amount == Decimal("40")
    assert Service.objects.get(pk=service.pk).pay_rate.currency == "GBP"
