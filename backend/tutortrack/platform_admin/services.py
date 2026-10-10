"""Platform console actions (E30 FR-30-1/2). Each one runs inside the organisation's tenant
context and goes through the owning app's services, which audit it (the actor is the
staff member), so the organisation's own audit log shows what support did."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, flags
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.models import FeatureFlag, FeatureFlagOverride, OutboxEvent
from tutortrack.tenancy.models import Organisation


def organisation(pk: Any) -> Organisation:
    org = Organisation.objects.filter(pk=pk).first()
    if org is None:
        raise NotFound()
    return org


def extend_trial(org: Organisation, *, days: int, reason: str) -> Any:
    from tutortrack.subscriptions import services as subscriptions

    with tenant_context(org):
        return subscriptions.extend_trial(days, reason=reason)


def set_override(org: Organisation, *, user: Any, **values: Any) -> Any:
    from tutortrack.subscriptions import services as subscriptions

    if len((values.get("reason") or "").strip()) < 3:
        raise BusinessRuleViolation(_("Give a reason for the override."))
    with tenant_context(org), transaction.atomic():
        return subscriptions.set_override(user=user, **values)


def remove_override(org: Organisation, key: str) -> None:
    from tutortrack.subscriptions import services as subscriptions

    with tenant_context(org), transaction.atomic():
        subscriptions.remove_override(key)


def suspend(org: Organisation, *, reason: str) -> Organisation:
    from tutortrack.tenancy import lifecycle

    return lifecycle.suspend_organisation(org, reason=reason)


def unsuspend(org: Organisation) -> Organisation:
    """Lift a suspension back to what the subscription says (trial or active)."""
    from tutortrack.subscriptions.models import Subscription
    from tutortrack.tenancy import lifecycle

    with tenant_context(org):
        subscription = Subscription.objects.first()
    trialing = subscription is not None and subscription.status == "trialing"
    return lifecycle.reactivate_organisation(
        org, status=Organisation.Status.TRIAL if trialing else Organisation.Status.ACTIVE
    )


def change_plan(org: Organisation, *, plan: str, interval: str, note: str, activate: bool) -> Any:
    from tutortrack.subscriptions import services as subscriptions

    with tenant_context(org):
        return subscriptions.admin_set_plan(plan, interval, note=note, activate=activate)


def resend_owner_verification(org: Organisation) -> int:
    from tutortrack.identity.models import Membership
    from tutortrack.identity.services import send_verification_email

    with tenant_context(org):
        owners = Membership.objects.filter(
            role=Membership.Role.OWNER, status=Membership.Status.ACTIVE,
            user__email_verified_at__isnull=True,
        ).select_related("user")  # fmt: skip
        sent = 0
        for membership in owners:
            send_verification_email(membership.user)
            sent += 1
        return sent


def request_export(org: Organisation, *, reason: str) -> None:
    from tutortrack.tenancy import lifecycle

    lifecycle.request_export(org, reason=reason or "platform request")


def schedule_deletion(org: Organisation, *, reason: str, confirm_slug: str) -> Organisation:
    from tutortrack.tenancy import lifecycle

    if confirm_slug.strip().lower() != org.slug:
        raise BusinessRuleViolation(
            _("Type the organisation's subdomain to confirm."),
            extra={"errors": {"confirm_slug": [_("Does not match.")]}},
        )
    return lifecycle.close_for_platform(org, reason=reason)


def start_support_session(
    org: Organisation, *, staff: Any, membership_id: Any, reason: str, ticket: str, write: bool
) -> str:
    """Returns the single-use link that opens the organisation as that member."""
    from tutortrack.identity import support
    from tutortrack.identity.models import Membership

    with tenant_context(org):
        membership = Membership.objects.select_related("user").filter(pk=membership_id).first()
        if membership is None:
            raise NotFound()
        _session, raw = support.start_session(
            staff=staff, membership=membership, reason=reason, ticket=ticket, write=write
        )
    return f"{org.base_url}/api/v1/support/enter?token={raw}"


# --- feature flags (T03) ------------------------------------------------------------------------


FLAG_FIELDS = {"description", "enabled_globally", "plan_keys", "rollout_percent"}


@transaction.atomic
def save_flag(key: str, **values: Any) -> FeatureFlag:
    unknown = set(values) - FLAG_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown flag fields: {', '.join(sorted(unknown))}")
    if "rollout_percent" in values and not 0 <= int(values["rollout_percent"]) <= 100:
        raise BusinessRuleViolation(_("Rollout is a percentage from 0 to 100."))
    flag, _created = FeatureFlag.objects.update_or_create(key=key, defaults=values)
    audit.record(flag, "platform_flag", {k: [None, v] for k, v in values.items()})
    flags.invalidate_cache()
    return flag


@transaction.atomic
def set_flag_override(
    key: str, organisation_id: Any, *, enabled: bool, expires_at: datetime | None, reason: str
) -> FeatureFlagOverride:
    flag = FeatureFlag.objects.filter(key=key).first()
    if flag is None:
        raise NotFound()
    organisation(organisation_id)
    override, _created = FeatureFlagOverride.objects.update_or_create(
        flag=flag, organisation_id=organisation_id,
        defaults={"enabled": enabled, "expires_at": expires_at, "reason": reason[:255]},
    )  # fmt: skip
    flags.invalidate_cache()
    return override


@transaction.atomic
def remove_flag_override(key: str, organisation_id: Any) -> None:
    FeatureFlagOverride.objects.filter(flag__key=key, organisation_id=organisation_id).delete()
    flags.invalidate_cache()


# --- dead letters (T04) -------------------------------------------------------------------------


def replay(event_ids: list[Any]) -> int:
    """Put dead-lettered events back in the outbox queue."""
    from tutortrack.core.db import PLATFORM_DB_ALIAS
    from tutortrack.core.events.dispatcher import replay_dead_letter

    count = 0
    events = OutboxEvent.objects.using(PLATFORM_DB_ALIAS).filter(
        pk__in=event_ids, dead_lettered_at__isnull=False
    )
    for event in events:
        with transaction.atomic(using=PLATFORM_DB_ALIAS):
            replay_dead_letter(event)
        count += 1
    return count
