"""G6 (FR-29-3): consent ticked on public forms becomes E29 consent records."""

from __future__ import annotations

import json

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.leads import forms as lead_forms
from tutortrack.leads.models import Enquiry, Form
from tutortrack.privacy.models import ConsentRecord
from tutortrack.privacy.services import ensure_default_types

from .test_leads import ANSWERS, SCHEMA, form, submit  # noqa: F401 - the form fixture

pytestmark = pytest.mark.django_db


def with_consent_fields() -> dict:
    schema = json.loads(json.dumps(SCHEMA))
    schema["steps"][0]["fields"] += [
        {"key": "agree", "label": "I agree", "type": "consent", "required": True},
        {"key": "news", "label": "News", "type": "consent", "consent_key": "marketing-email"},
        {"key": "photos", "label": "Photos", "type": "consent", "consent_key": "photo-video"},
    ]
    return schema


def test_ticked_consent_fields_are_recorded_as_consent_records(org, form):  # noqa: F811
    with tenant_context(org):
        ensure_default_types()
        Form.objects.filter(pk=form.pk).update(schema=with_consent_fields())
    answers = {**ANSWERS, "agree": True, "news": True, "photos": False}
    response = submit(org, {"data": answers})
    assert response.status_code == 201, response.content
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
        records = ConsentRecord.objects.select_related("consent_type")
        mine = {r.consent_type.key for r in records.filter(subject_id=str(enquiry.contact_id))}
        assert mine == {"data-processing", "marketing-email"}
        record = records.get(consent_type__key="marketing-email")
        assert (record.method, record.granted, record.source) == ("form", True, "form:enquire")
        assert record.given_by_name == "Priya Patel"
        assert record.version == record.consent_type.version
        # An unticked box records nothing.
        assert not records.filter(consent_type__key="photo-video").exists()
        # data-processing applies to the children too (given by the parent).
        assert OutboxEvent.objects.filter(event_type="consent.granted").count() == 4


def test_photo_consent_on_a_form_is_recorded_for_the_children(org, form):  # noqa: F811
    with tenant_context(org):
        ensure_default_types()
        Form.objects.filter(pk=form.pk).update(schema=with_consent_fields())
    response = submit(org, {"data": {**ANSWERS, "agree": True, "photos": True}})
    assert response.status_code == 201, response.content
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
        photos = ConsentRecord.objects.filter(consent_type__key="photo-video")
        assert {r.subject_id for r in photos} == {str(s.pk) for s in enquiry.students.all()}
        assert all(r.on_behalf_of_child and r.subject_type == "people.student" for r in photos)


def test_unknown_consent_keys_never_block_a_submission(org, form):  # noqa: F811
    schema = with_consent_fields()
    schema["steps"][0]["fields"][-1]["consent_key"] = "removed-type"
    with tenant_context(org):
        Form.objects.filter(pk=form.pk).update(schema=schema)
    response = submit(org, {"data": {**ANSWERS, "agree": True, "photos": True}})
    assert response.status_code == 201, response.content
    with tenant_context(org):
        assert Enquiry.objects.exists()
        assert not ConsentRecord.objects.filter(source="form:enquire").exclude(
            consent_type__key="data-processing"
        )


def test_consent_fields_must_name_a_consent_key() -> None:
    schema = json.loads(json.dumps(SCHEMA))
    schema["steps"][0]["fields"].append(
        {"key": "agree", "label": "I agree", "type": "consent", "consent_key": "Bad Key!"}
    )
    with pytest.raises(BusinessRuleViolation):
        lead_forms.clean_schema(schema)
