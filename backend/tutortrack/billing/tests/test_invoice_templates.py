"""Invoice templates (ADR 0046): CRUD, the default, which template an invoice uses (job,
then family, then default), the frozen copy on issue, the editor's preview and branch
branding on documents."""

from __future__ import annotations

from typing import Any

import pytest

from tutortrack.billing import invoice_templates, pdf
from tutortrack.billing.models import Invoice, InvoiceTemplate
from tutortrack.billing.tests.test_billing import complete, lesson, make_job
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.models import Client

pytestmark = pytest.mark.django_db

URL = "/api/v1/invoice-templates"


def make(org, **fields: Any) -> InvoiceTemplate:
    with tenant_context(org):
        return invoice_templates.create_template(**{"name": "Standard", **fields})


class TestInvoiceTemplateIsolation(TenantIsolationTestMixin):
    list_url = URL

    def make_object(self, organisation):
        return make(organisation)


def test_templates_are_created_edited_and_audited_and_the_first_is_the_default(org, finance):
    first = finance.post(URL, {"name": "Standard"}, format="json")
    assert first.status_code == 201, first.json()
    assert (first.json()["is_default"], first.json()["style"]) == (True, "classic")
    second = finance.post(
        URL, {"name": "Music", "style": "modern", "accent_colour": "#7C3AED"}, format="json"
    )
    assert second.json()["is_default"] is False
    # Making another the default moves it.
    finance.patch(f"{URL}/{second.json()['id']}", {"is_default": True}, format="json")
    rows = {row["name"]: row["is_default"] for row in finance.get(URL).json()}
    assert rows == {"Music": True, "Standard": False}
    with tenant_context(org):
        assert AuditEntry.objects.filter(object_id=second.json()["id"], action="update").exists()


def test_bad_settings_are_refused_beside_the_field(finance):
    colour = finance.post(URL, {"name": "X", "accent_colour": "purple"}, format="json")
    assert colour.status_code == 400  # refused by the serializer, before it reaches CSS
    assert "accent_colour" in colour.json()["errors"]
    logo = finance.post(URL, {"name": "X", "logo_mode": "own"}, format="json")
    assert logo.status_code == 422
    assert "logo" in logo.json()["errors"]


def test_only_people_who_manage_templates_can_change_them(org):
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.post(URL, {"name": "X"}, format="json").status_code == 403


def test_an_invoice_uses_the_jobs_then_the_familys_then_the_default_template(org, family):
    standard = make(org)
    music = make(org, name="Music", style="modern")
    tutoring = make(org, name="Tutoring", style="compact")
    job = make_job(org, family, "pay_as_you_go")
    complete(org, lesson(org, family, job=job))
    with tenant_context(org):
        from tutortrack.billing import services

        draft = services.create_draft(family["client"])
        assert invoice_templates.template_for_invoice(draft) == standard
        client = Client.objects.get(pk=family["client"].pk)
        client.invoice_template = tutoring
        client.save()
        draft.refresh_from_db()
        assert invoice_templates.template_for_invoice(draft) == tutoring
        job.invoice_template = music
        job.save()
        assert invoice_templates.template_for_invoice(draft) == music


def test_an_issued_invoice_keeps_the_look_it_was_sent_with(org, finance, family):
    template = make(org, title="Tax invoice", show_student=False, intro="Thanks!")
    complete(org, lesson(org, family))
    draft = finance.post(
        "/api/v1/invoices", {"client": str(family["client"].pk)}, format="json"
    ).json()
    issued = finance.post(f"/api/v1/invoices/{draft['id']}/issue").json()
    sent_with = issued["billing_snapshot"]["template"]
    assert (sent_with["title"], sent_with["columns"]["student"]) == ("Tax invoice", False)
    with tenant_context(org):
        invoice_templates.update_template(template, title="Receipt", show_student=True)
        invoice = Invoice.objects.get(pk=draft["id"])
        assert invoice_templates.invoice_layout(invoice)["title"] == "Tax invoice"
    assert finance.get(f"/api/v1/invoices/{draft['id']}/pdf").content.startswith(b"%PDF")


def test_invoices_issued_before_templates_keep_their_wording(org, family):
    with tenant_context(org):
        invoice = Invoice(
            client=family["client"],
            status=Invoice.Status.ISSUED,
            billing_snapshot={"payment_instructions": "Pay by cheque", "footer": "Old footer"},
        )
        look = invoice_templates.invoice_layout(invoice)
    assert (look["style"], look["payment_instructions"], look["footer"]) == (
        "classic",
        "Pay by cheque",
        "Old footer",
    )


def test_the_preview_draws_unsaved_settings(org, finance):
    response = finance.post(
        f"{URL}/preview",
        {
            "style": "modern",
            "title": "Tax invoice",
            "trading_name": "Bright Minds Music",
            "intro": "Thank you for learning with us.",
            "show_student": False,
            "show_tutor": False,
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    html = response.json()["html"]
    assert 'class="style-modern"' in html
    assert "Tax invoice" in html
    assert "Bright Minds Music" in html
    assert "Thank you for learning with us." in html
    assert "<th>Student</th>" not in html
    assert "Nia Adeyemi" not in html
    with tenant_context(org):
        assert not InvoiceTemplate.objects.exists()  # nothing saved
    unsafe = finance.post(f"{URL}/preview", {"accent_colour": "red}body{x"}, format="json")
    assert unsafe.status_code == 400
    blank_name = finance.post(f"{URL}/preview", {"name": ""}, format="json")
    assert blank_name.status_code == 200
    sample = finance.post(f"{URL}/preview-pdf", {"style": "compact"}, format="json")
    assert sample["Content-Type"] == "application/pdf"
    assert sample.content.startswith(b"%PDF")


def test_families_and_jobs_choose_a_template_from_their_own_organisation(
    org, other_org, finance, family
):
    mine = make(org)
    theirs = make(other_org)
    client_url = f"/api/v1/clients/{family['client'].pk}"
    manager = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    chosen = manager.patch(client_url, {"invoice_template": str(mine.pk)}, format="json")
    assert chosen.status_code == 200, chosen.json()
    assert chosen.json()["invoice_template"] == str(mine.pk)
    other = manager.patch(client_url, {"invoice_template": str(theirs.pk)}, format="json")
    assert other.status_code == 400
    job = make_job(org, family, "pay_as_you_go")
    picked = manager.patch(
        f"/api/v1/jobs/{job.pk}", {"invoice_template": str(mine.pk)}, format="json"
    )
    assert picked.status_code == 200, picked.json()
    # Deleting the template sends both back to the default.
    assert finance.delete(f"{URL}/{mine.pk}").status_code == 204
    with tenant_context(org):
        assert Client.objects.get(pk=family["client"].pk).invoice_template_id is None


def test_documents_use_the_branchs_brand_kit(org, family, monkeypatch):
    from tutortrack.core import branding

    asked: list[Any] = []
    real = branding.for_documents

    def spy(organisation_id, branch_id=None):
        asked.append(branch_id)
        return real(organisation_id, branch_id)

    monkeypatch.setattr(branding, "for_documents", spy)
    complete(org, lesson(org, family))
    with tenant_context(org):
        from tutortrack.billing import services

        draft = services.create_draft(family["client"])
        pdf.invoice_pdf(draft)
    assert asked == [draft.branch_id]
