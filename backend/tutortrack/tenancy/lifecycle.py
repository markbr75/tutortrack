"""Organisation lifecycle: close (owner) and suspend/reactivate (platform) (FR-02-8).

Closing records the decision and publishes ``organisation.closed``. The rest of the
process (data export, grace period with reopening, deletion per retention policy) is the
``OrganisationClosureWorkflow`` on Temporal (``tenancy/closure.py``), started from that
event; E04 cancels the subscription from the same event. ``request_reopen`` signals the
workflow during the grace period.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import tenant_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now

from . import events
from . import permissions as perms
from .models import Organisation


class ReauthenticationFailed(PermissionDenied):
    problem_type = "reauthentication-failed"
    title = "Please confirm your password"


@transaction.atomic
def close_organisation(
    organisation: Organisation,
    *,
    user: Any,
    password: str,
    confirm_slug: str,
    reason: str = "",
    export_requested: bool = True,
) -> Organisation:
    """Owner closes the account. Requires re-authentication and typing the subdomain."""
    organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)
    with tenant_context(organisation):
        if not has_perm(user, perms.CLOSE):
            raise PermissionDenied(_("Only the owner can close the account."))
        if not password or not user.check_password(password):
            raise ReauthenticationFailed()
        if confirm_slug.strip().lower() != organisation.slug:
            raise BusinessRuleViolation(
                _("Type your subdomain to confirm."),
                extra={"errors": {"confirm_slug": [_("Does not match.")]}},
            )
        if organisation.is_closed:
            return organisation
        with audit.track(organisation, action="close"):
            organisation.status = Organisation.Status.CANCELLED
            organisation.closed_at = now()
            organisation.save(update_fields=["status", "closed_at", "updated_at"])
        publish(
            events.OrganisationClosed(
                subject_id=organisation.pk,
                reason=reason[:500],
                export_requested=export_requested,
            ),
            organisation_id=organisation.pk,
        )
    return organisation


@transaction.atomic
def suspend_organisation(organisation: Organisation, *, reason: str) -> Organisation:
    """Platform action (non-payment from E04, abuse from E30): read-only for owners/admins."""
    if not reason.strip():
        raise BusinessRuleViolation(_("A reason is required."))
    organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)
    if organisation.is_closed:
        raise BusinessRuleViolation(_("Closed organisations cannot be suspended."))
    with tenant_context(organisation):
        if organisation.is_suspended:
            return organisation
        with audit.track(organisation, action="suspend"):
            organisation.status = Organisation.Status.SUSPENDED
            organisation.suspended_at = now()
            organisation.suspension_reason = reason.strip()[:500]
            organisation.save(
                update_fields=["status", "suspended_at", "suspension_reason", "updated_at"]
            )
        publish(
            events.OrganisationSuspended(subject_id=organisation.pk, reason=reason.strip()),
            organisation_id=organisation.pk,
        )
    return organisation


@transaction.atomic
def reactivate_organisation(
    organisation: Organisation, *, status: str = Organisation.Status.ACTIVE
) -> Organisation:
    """Lift a suspension (platform action, or E04 when the overdue invoice is paid)."""
    if status not in {Organisation.Status.ACTIVE, Organisation.Status.TRIAL}:
        raise BusinessRuleViolation("Reactivate to active or trial.")
    organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)
    if not organisation.is_suspended:
        raise BusinessRuleViolation(_("The organisation is not suspended."))
    with tenant_context(organisation):
        with audit.track(organisation, action="reactivate"):
            organisation.status = status
            organisation.suspended_at = None
            organisation.suspension_reason = ""
            organisation.save(
                update_fields=["status", "suspended_at", "suspension_reason", "updated_at"]
            )
        publish(
            events.OrganisationReactivated(subject_id=organisation.pk),
            organisation_id=organisation.pk,
        )
    return organisation


def request_reopen(organisation: Organisation) -> bool:
    """Platform action: reopen a closed account during its grace period. Returns False if
    the closure process has already finished (the data may be gone)."""
    from tutortrack.core.workflows import signal_now

    from .closure import closure_workflow_id

    if not organisation.is_closed:
        raise BusinessRuleViolation(_("The organisation is not closed."))
    return signal_now(closure_workflow_id(organisation.pk), "reactivate")


BILLING_STATUSES = {
    Organisation.Status.TRIAL,
    Organisation.Status.ACTIVE,
    Organisation.Status.PAST_DUE,
}


@transaction.atomic
def set_billing_status(organisation: Organisation, status: str) -> Organisation:
    """The subscription (E04) moves an operational organisation between trial, active and
    past due. Suspension and reactivation go through ``suspend_organisation`` and
    ``reactivate_organisation``; closed organisations are left alone."""
    if status not in BILLING_STATUSES:
        raise BusinessRuleViolation("Use suspend/reactivate for other statuses.")
    organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)
    if organisation.is_closed or organisation.is_suspended or organisation.status == status:
        return organisation
    with tenant_context(organisation), audit.track(organisation, action="billing_status"):
        organisation.status = status
        organisation.save(update_fields=["status", "updated_at"])
    return organisation


@transaction.atomic
def request_export(organisation: Organisation, *, reason: str) -> None:
    """Ask for a full data export (E28 builds it from ``organisation.export_requested``)."""
    from .closure import OrganisationExportRequested

    with tenant_context(organisation):
        audit.record(organisation, "export_requested", {"reason": [None, reason[:200]]})
        publish(
            OrganisationExportRequested(subject_id=organisation.pk, reason=reason[:200]),
            organisation_id=organisation.pk,
        )


@transaction.atomic
def close_for_platform(
    organisation: Organisation, *, reason: str, export_requested: bool = True
) -> Organisation:
    """Platform staff schedule deletion (e.g. at the owner's written request): the same
    closure process as an owner closing the account, without their password."""
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation(_("Give a reason."))
    organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)
    if organisation.is_closed:
        return organisation
    with tenant_context(organisation):
        with audit.track(organisation, action="close_by_platform"):
            organisation.status = Organisation.Status.CANCELLED
            organisation.closed_at = now()
            organisation.save(update_fields=["status", "closed_at", "updated_at"])
        publish(
            events.OrganisationClosed(
                subject_id=organisation.pk, reason=reason.strip()[:500],
                export_requested=export_requested,
            ),
            organisation_id=organisation.pk,
        )  # fmt: skip
    return organisation
