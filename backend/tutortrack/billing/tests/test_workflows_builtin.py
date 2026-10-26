"""E33-T04: billing's built-in workflows: each organisation's settings become their first
version, the replaced schedules and settings are retired, and their steps work."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.automations.tests.test_catalogue import act
from tutortrack.billing import dunning, packages, services
from tutortrack.billing.models import (
    Charge,
    ClientLedgerEntry,
    InvoiceRun,
    LateFeeRule,
    PackagePurchase,
)
from tutortrack.billing.processes import (
    SCHEDULE_PROCESS,
    STATEMENT_PROCESS,
    dunning_workflow_id,
    request_workflow_id,
)
from tutortrack.billing.tests.test_billing import (
    complete,
    events_of,
    issued_invoice,
    lesson,
    local_today,
)
from tutortrack.billing.tests.test_phase2_workflows import active_package, client_  # noqa: F401
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import ScheduleLink, WorkflowLink
from tutortrack.core.time import now
from tutortrack.core.workflows.schedules import schedule_id
from tutortrack.tenancy import settings_service
from tutortrack.tenancy.models import Branch

pytestmark = pytest.mark.django_db

KEYS = {"invoicing_cycle", "payment_chasing", "payment_request_reminders", "monthly_statements"}


def install(org, **settings) -> dict[str, Automation]:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("billing", settings, allow_replaced=True)
        automations.install_builtins()
        return {a.builtin_key: a for a in Automation.objects.filter(builtin_key__in=KEYS)}


def kinds(steps) -> list[str]:
    """The steps in short: "wait 3" or the action."""
    return [f"wait {s['offset_days']}" if s["type"] == "wait" else s["action"] for s in steps]


# --- first versions from the settings ------------------------------------------------------


def test_with_the_default_settings_each_starts_as_the_default(org):
    installed = install(org)
    assert set(installed) == KEYS
    assert not any(a.edited for a in installed.values())
    on = {key for key, a in installed.items() if a.enabled}
    assert on == {"payment_chasing", "payment_request_reminders"}  # invoicing was "manual"
    assert kinds(installed["payment_chasing"].steps) == [
        "wait -3", "send_invoice_reminder", "wait 0", "send_invoice_reminder",
        "wait 3", "send_invoice_reminder", "wait 7", "send_invoice_reminder",
        "wait 14", "send_invoice_reminder", "late_fee", "wait 30", "send_invoice_reminder",
    ]  # fmt: skip
    assert installed["payment_chasing"].stop_when == [
        "invoice.paid", "invoice.voided", "invoice.written_off",
    ]  # fmt: skip
    assert installed["payment_chasing"].steps[0]["at"] == "09:00"
    with tenant_context(org):
        assert automations.builtin_notices() == []  # nothing on by default is off


def test_the_invoicing_cycle_takes_the_invoicing_settings(org):
    invoicing = install(org, **{
        "billing.invoice_schedule": "weekly", "billing.invoice_day": 3,
        "billing.review_days": 5, "billing.auto_issue": False, "billing.auto_send": False,
    })["invoicing_cycle"]  # fmt: skip
    assert invoicing.enabled
    assert invoicing.edited  # not the default, so a newer default won't overwrite it
    assert invoicing.subject_type == "branch"
    assert invoicing.trigger_config == {
        "subject": "branch", "frequency": "weekly", "weekday": 2, "time": "06:00",
        "start": "invoice_run.due",
    }  # fmt: skip
    assert invoicing.steps[0]["config"] == {
        "period": "schedule", "review_days": 5, "issue": "when_approved", "email": False,
    }  # fmt: skip

    monthly = install(OrgFactory(), **{"billing.invoice_schedule": "monthly",
                                       "billing.invoice_day": 25})["invoicing_cycle"]  # fmt: skip
    assert (monthly.trigger_config["frequency"], monthly.trigger_config["day"]) == ("monthly", 25)


def test_payment_chasing_takes_the_reminders_late_fee_rule_and_collections(org):
    with tenant_context(org):
        monthly = LateFeeRule.Recurrence.MONTHLY
        dunning.save_rule(None, kind="fixed", amount=Decimal("5"), days_overdue=10,
                          recurrence=monthly, max_applications=3)  # fmt: skip
    chasing = install(org, **{
        "billing.reminder_offsets": [7, 0], "billing.collections_after_days": 20,
    })["payment_chasing"]  # fmt: skip
    assert kinds(chasing.steps) == [
        "wait 0", "send_invoice_reminder", "wait 7", "send_invoice_reminder",
        "wait 10", "late_fee", "wait 20", "open_collections", "wait 40", "late_fee",
        "wait 70", "late_fee",
    ]  # fmt: skip
    assert chasing.enabled
    assert chasing.edited


def test_with_reminders_off_and_nothing_else_to_do_payment_chasing_starts_off(org):
    chasing = install(org, **{"billing.reminders_enabled": False})["payment_chasing"]
    assert not chasing.enabled
    assert kinds(chasing.steps) == ["wait 14", "late_fee"]  # applies once you add a rule
    with tenant_context(org):
        [notice] = automations.builtin_notices()
    assert (notice["name"], notice["notice"]) == ("Payment chasing", "off")
    assert "chase unpaid invoices yourself" in notice["message"]


def test_monthly_statements_take_the_statement_settings(org):
    statements = install(org, **{
        "billing.statement_schedule": "monthly", "billing.statement_day": 5,
    })["monthly_statements"]  # fmt: skip
    assert statements.enabled
    assert statements.trigger_config == {
        "subject": "client", "frequency": "monthly", "day": 5, "time": "07:00",
        "start": "statement.due",
    }  # fmt: skip
    assert kinds(statements.steps) == ["send_statement"]


# --- retiring what they replace ------------------------------------------------------------


def test_installing_removes_the_replaced_schedules(
    org, monkeypatch, django_capture_on_commit_callbacks
):
    deleted = []
    monkeypatch.setattr(  # Temporal's delete call
        "tutortrack.core.workflows.schedules.runtime.run",
        lambda coro: deleted.append(coro.__name__) or coro.close(),
    )
    with tenant_context(org):
        branch = Branch.objects.get(is_default=True)
        invoice_sid = schedule_id(SCHEDULE_PROCESS, org.pk, branch.pk)
        statement_sid = schedule_id(STATEMENT_PROCESS, org.pk)
        for sid, process in ((invoice_sid, SCHEDULE_PROCESS), (statement_sid, STATEMENT_PROCESS)):
            ScheduleLink.objects.create(schedule_id=sid, process=process)
    with django_capture_on_commit_callbacks(execute=True):
        install(org)
    with tenant_context(org):
        assert not ScheduleLink.objects.filter(
            schedule_id__in=[invoice_sid, statement_sid]
        ).exists()
    assert deleted.count("_each") == 2  # one delete each (other calls set up new schedules)


def test_replaced_settings_stay_readable_but_cant_be_changed(org, api):
    described = {d["key"]: d for d in api.get("/api/v1/settings/billing").json()["schema"]}
    assert described["billing.reminder_offsets"]["replaced_by"] == "payment_chasing"
    assert described["billing.invoice_schedule"]["replaced_by"] == "invoicing_cycle"
    assert described["billing.statement_day"]["replaced_by"] == "monthly_statements"
    assert "replaced_by" not in described["billing.review_days"]  # runs started by hand
    response = api.patch("/api/v1/settings/billing",
                         {"values": {"billing.reminder_offsets": [1]}}, format="json")  # fmt: skip
    assert response.status_code == 400
    assert "Workflows" in str(response.json())


def test_issued_invoices_and_payment_requests_no_longer_start_the_old_workflows(org, family):
    invoice = issued_invoice(org, family)
    with tenant_context(org):
        request = services.create_payment_request(
            client=family["client"], amount=invoice.balance_due, description="Deposit"
        )
    dispatch_batch()
    with tenant_context(org):
        ids = [dunning_workflow_id(org.pk, invoice.pk), request_workflow_id(org.pk, request.pk)]
        assert not WorkflowLink.objects.filter(workflow_id__in=ids).exists()


# --- the steps -------------------------------------------------------------------------------


def test_runs_from_the_invoicing_cycle_use_its_review_issue_and_email_choices(
    org, family, monkeypatch, django_capture_on_commit_callbacks
):
    sent = []
    monkeypatch.setattr(services, "_send_later", lambda org_id, invoice_id: sent.append(invoice_id))
    complete(org, lesson(org, family))
    today = local_today(org)
    with tenant_context(org):
        run, _ = services.create_run(
            period_start=today - timedelta(days=7), period_end=today, start_workflow=False,
            review_days=5, auto_issue=False, send_invoices=False,
        )  # fmt: skip
        stats = services.collect_run(run.pk)
        assert (stats["review_days"], stats["auto_issue"]) == (5, False)
        run.refresh_from_db()
        assert run.review_until > now() + timedelta(days=4)
        with django_capture_on_commit_callbacks(execute=True):
            services.issue_run(run.pk)
    assert events_of(org, "invoice_run.issued")[0]["issued"] == 1
    assert sent == []  # the cycle said not to email


def test_start_an_invoice_run_passes_the_cycles_choices_to_the_run(org):
    with tenant_context(org):
        branch = Branch.objects.get(is_default=True)
    config = {"period": "last_month", "review_days": 3, "issue": "after_review", "email": True}
    made = act(org, "start_invoice_run", "branch", branch, config)
    with tenant_context(org):
        run = InvoiceRun.objects.get(pk=made["invoice_run"])
    assert (run.review_days, run.auto_issue, run.send_invoices) == (3, True, True)
    plain = act(org, "start_invoice_run", "branch", branch, {"period": "this_month"}, step="b")
    with tenant_context(org):
        run = InvoiceRun.objects.get(pk=plain["invoice_run"])
    assert (run.review_days, run.auto_issue, run.send_invoices) == (None, None, None)  # settings


def test_payment_reminders_say_how_late_and_mark_the_invoice_overdue(org, family):
    invoice = issued_invoice(org, family)
    early = act(org, "send_invoice_reminder", "invoice", invoice)
    assert early["days_from_due"] == -14
    assert events_of(org, "invoice.overdue") == []
    with tenant_context(org):
        type(invoice).objects.filter(pk=invoice.pk).update(
            due_date=local_today(org) - timedelta(days=3)
        )
    late = act(org, "send_invoice_reminder", "invoice", invoice, step="b")
    assert late["days_from_due"] == 3
    assert sorted(e["offset_days"] for e in events_of(org, "invoice.reminder")) == [-14, 3]
    assert len(events_of(org, "invoice.overdue")) == 1
    with tenant_context(org):
        services.allocate_payment(invoice, invoice.balance_due)
    assert act(org, "send_invoice_reminder", "invoice", invoice, step="c") == {
        "skipped": "invoice already paid"
    }


def test_the_late_fee_step_applies_the_rule_each_time(org, family):
    invoice = issued_invoice(org, family)
    assert act(org, "late_fee", "invoice", invoice) == {"skipped": "there is no late fee rule"}
    with tenant_context(org):
        dunning.save_rule(None, kind="fixed", amount=Decimal("5"), days_overdue=14)
    assert act(org, "late_fee", "invoice", invoice, step="b") == {"late_fee": "applied"}
    assert act(org, "late_fee", "invoice", invoice, step="c") == {"late_fee": "applied"}
    with tenant_context(org):
        fees = Charge.objects.filter(kind=Charge.Kind.LATE_FEE).order_by("source_key")
        assert [c.source_key for c in fees] == [
            f"late_fee:{invoice.pk}:1", f"late_fee:{invoice.pk}:2",
        ]  # fmt: skip
        services.allocate_payment(invoice, invoice.balance_due)
    assert act(org, "late_fee", "invoice", invoice, step="d") == {"skipped": "invoice already paid"}
    # A set amount still works as before.
    second = issued_invoice(org, family)
    assert "charge" in act(org, "late_fee", "invoice", second, {"percent": 10}, step="e")


def test_statements_go_only_to_families_with_something_to_show(org, family):
    from tutortrack.automations.catalogue import statement_clients

    invoice = issued_invoice(org, family)
    today = local_today(org)
    with tenant_context(org):
        assert statement_clients(today) == []  # this month's activity is next month's
    with tenant_context(org):
        ClientLedgerEntry.objects.filter(client=family["client"]).update(
            occurred_at=now() - timedelta(days=today.day + 2)
        )
        statements = install(org)["monthly_statements"]
        assert automations.due_records(statements, today) == [str(invoice.client_id)]


def test_schedule_runs_dont_count_towards_the_hourly_limit(org, family):
    installed = install(org)
    with tenant_context(org):
        settings_service.update_settings("automations", {"automations.max_runs_per_hour": 1})
        branch = Branch.objects.get(is_default=True)
        cycle = installed["invoicing_cycle"]
        automations.set_enabled(cycle, True)
        cycle.refresh_from_db()
        for n in range(3):
            AutomationRun.objects.create(
                automation=cycle, version=cycle.versions.get(version=cycle.version),
                subject_type="branch", subject_id=f"x{n}", run_key=f"schedule:2026-10-0{n + 1}",
            )  # fmt: skip
        run = automations.prepare_run(cycle, subject_id=str(branch.pk), run_key="schedule:today")
        assert run is not None


def OrgFactory():
    from tutortrack.tenancy.tests.factories import OrganisationFactory

    return OrganisationFactory()


# --- package expiry reminder (E33 T06) -----------------------------------------------------


def package_reminder(org, **settings) -> Automation:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("billing", settings, allow_replaced=True)
        automations.install_builtins()
        return Automation.objects.get(builtin_key="package_expiry")


def expiring_in(org, purchase, days: int):
    with tenant_context(org):
        moment = now().replace(hour=12, minute=0, second=0, microsecond=0)
        PackagePurchase.objects.filter(pk=purchase.pk).update(
            expires_at=moment + timedelta(days=days)
        )
        return PackagePurchase.objects.get(pk=purchase.pk)


def test_the_package_reminder_takes_its_days_and_zero_switches_it_off(org):
    default = package_reminder(org)
    assert (default.enabled, default.edited) == (True, False)
    assert default.trigger_config["offset_days"] == [-14]
    with tenant_context(org):
        default.delete()
    assert package_reminder(org, **{"billing.package_expiry_reminder_days": 30}).edited
    with tenant_context(org):
        Automation.objects.filter(builtin_key="package_expiry").delete()
    off = package_reminder(org, **{"billing.package_expiry_reminder_days": 0})
    assert not off.enabled
    assert off.trigger_config["offset_days"] == [-14]
    with tenant_context(org), pytest.raises(ValidationError):
        settings_service.update_settings("billing", {"billing.package_expiry_reminder_days": 7})


def test_packages_are_reminded_once_per_expiry_date(org, client_, monkeypatch):  # noqa: F811
    reminder = package_reminder(org)
    due = expiring_in(org, active_package(org, client_, validity_days=60), 14)
    expiring_in(org, active_package(org, client_, validity_days=60), 20)
    started: list[AutomationRun] = []
    monkeypatch.setattr(automations, "launch", lambda run, **kw: started.append(run))
    with tenant_context(org):
        assert automations.fan_out(str(reminder.pk), on=now().date()) == 1
    assert [r.subject_id for r in started] == [str(due.pk)]
    assert act(org, "remind_package_expiry", "package", due) == {"reminded": str(due.pk)}
    act(org, "remind_package_expiry", "package", due, step="b")  # e.g. an old run as well
    assert len(events_of(org, "package.expiring")) == 1
    with tenant_context(org):
        packages.extend_package(due, until=due.expires_at + timedelta(days=30))
    assert act(org, "remind_package_expiry", "package", due, step="c") == {"reminded": str(due.pk)}
    assert len(events_of(org, "package.expiring")) == 2
