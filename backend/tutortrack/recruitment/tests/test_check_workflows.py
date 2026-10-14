"""E18-T11: ``BackgroundCheckWorkflow``: polling until complete, the invitation expiring,
cancellation, a webhook-style ``updated`` signal, and replay of recorded histories."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import background_checks as checks_service
from tutortrack.recruitment import compliance
from tutortrack.recruitment.check_processes import BackgroundCheckWorkflow, check_workflow_id
from tutortrack.recruitment.checks.fake import FakeChecks
from tutortrack.recruitment.models import BackgroundCheck

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
RECORD = bool(os.environ.get("RECORD_WORKFLOW_HISTORIES"))


@pytest.fixture(autouse=True)
def _fake_checks():
    FakeChecks.reset()
    yield
    FakeChecks.reset()


def request(org, provider: str = "ucheck", **kwargs: Any) -> tuple[BackgroundCheck, str]:
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin").user
        tutor = TutorProfileFactory(
            organisation=org, status="active", date_of_birth=date(1990, 5, 17)
        )
        compliance.ensure_requirement_types()
        with transaction.atomic():  # the workflow starts on commit
            check = checks_service.request_check(
                tutor, provider=provider, user=admin, consent=True, **kwargs
            )
    return check, check_workflow_id(org.pk, check.pk)


def wait_external(org, check: BackgroundCheck) -> str:
    for _ in range(400):
        with tenant_context(org):
            check.refresh_from_db()
        if check.external_id:
            return check.external_id
    raise AssertionError("never initiated")


def test_polls_until_the_check_completes(org, temporal_env):
    check, wid = request(org)
    external = wait_external(org, check)
    FakeChecks.advance(external, "completed", "clear")  # found on the next 6-hourly poll
    assert temporal_env.result(wid) == "completed"
    with tenant_context(org):
        check.refresh_from_db()
    assert (check.status, check.result) == ("completed", "clear")
    if RECORD:
        (HISTORIES / "BackgroundCheckWorkflow-completed.json").write_text(
            temporal_env.history_json(wid)
        )


def test_invitation_expires_when_the_tutor_never_finishes(org, temporal_env):
    check, wid = request(org)
    wait_external(org, check)
    assert temporal_env.result(wid) == "expired"
    with tenant_context(org):
        check.refresh_from_db()
    assert check.status == "expired"
    if RECORD:
        (HISTORIES / "BackgroundCheckWorkflow-expired.json").write_text(
            temporal_env.history_json(wid)
        )


def test_cancelling_ends_the_workflow(org, temporal_env):
    check, wid = request(org)
    wait_external(org, check)
    with tenant_context(org), transaction.atomic():
        from tutortrack.core.models import WorkflowLink

        assert WorkflowLink.objects.filter(workflow_id=wid).exists()
        checks_service.cancel(check, user=None)
    assert temporal_env.result(wid) == "cancelled"


def test_updated_signal_fetches_at_once(org, temporal_env):
    check, wid = request(org, provider="checkr")
    external = wait_external(org, check)
    FakeChecks.advance(external, "completed", "consider")
    with tenant_context(org), transaction.atomic():
        checks_service._signal(check, "updated")
    assert temporal_env.result(wid) == "completed"
    with tenant_context(org):
        check.refresh_from_db()
    assert check.result == "consider"


@pytest.mark.parametrize("prefix", ["BackgroundCheckWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[BackgroundCheckWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
