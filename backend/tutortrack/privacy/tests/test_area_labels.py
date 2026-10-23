"""Readable areas in the erasure and retention-run reports (follow-up to "The Register"):
every area a report can hold has a label, and the API sends them with the report."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.time import now
from tutortrack.privacy import erasure, registry, selectors
from tutortrack.privacy.models import RetentionRun

pytestmark = pytest.mark.django_db


def _labelled(key: str, label: str) -> bool:
    return bool(label.strip()) and label != key


def test_every_provider_and_step_has_a_label():
    # Fails when a provider is registered without a label, or the erasure engine writes a
    # new report key (next to the provider keys) without adding it to ERASURE_STEP_LABELS.
    keys = [p.key for p in registry.providers()] + ["files", "logins", "financial", "blocked"]
    assert len(keys) > 15  # the providers were discovered
    unlabelled = [k for k in keys if not _labelled(k, selectors.erasure_area_label(k))]
    assert not unlabelled, f"Give these erasure report areas a label: {unlabelled}"


def test_every_retention_category_has_a_label():
    keys = [c.key for c in registry.retention_categories()]
    assert keys
    unlabelled = [k for k in keys if not _labelled(k, selectors.retention_area_label(k))]
    assert not unlabelled, f"Give these retention categories a label: {unlabelled}"


def test_unknown_keys_show_as_they_are():
    assert selectors.erasure_area_label("gone_app") == "gone_app"
    assert selectors.retention_area_label("gone_category") == "gone_category"


def test_erasure_record_api_sends_area_labels(org, owner_api, family):
    with tenant_context(org):
        record = erasure.plan("people.student", str(family.student.pk))
        record.report = {
            "scheduling": {"anonymised": 2, "deleted": 0, "retained": 0, "notes": []},
            "billing": {"anonymised": 1, "deleted": 0, "retained": 3, "notes": []},
            "logins": {"revoked": 1},
        }
        record.save(update_fields=["report"])
    row = owner_api.get(f"/api/v1/erasures/{record.pk}").json()
    assert row["area_labels"] == {
        "scheduling": "Lessons",
        "billing": "Invoices and charges",
        "logins": "Logins ended",
    }


def test_retention_run_api_sends_area_labels(org, owner_api):
    category = registry.retention_categories()[0]
    with tenant_context(org):
        RetentionRun.objects.create(
            started_at=now(), report={category.key: {"due": 3, "done": 0, "days": 30}}
        )
    row = owner_api.get("/api/v1/retention-runs").json()["results"][0]
    assert row["area_labels"] == {category.key: str(category.label)}
