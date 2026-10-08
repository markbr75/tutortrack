"""Organisation and branch writes (E02). All mutations audit and publish domain events."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, flags
from tutortrack.core.context import require_organisation_id, tenant_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import is_valid_timezone, now

from . import events, slugs
from .countries import defaults_for
from .models import Branch, Organisation, OrganisationDomain

SLUG_REDIRECT_DAYS = 90

ORGANISATION_EDITABLE = frozenset(
    {
        "name", "legal_name", "business_type", "mode", "country", "default_currency",
        "timezone", "locale", "logo", "logo_id", "primary_colour", "contact_email",
        "contact_phone", "address", "company_number", "vat_number", "tax_number",
        "fiscal_year_start_month", "week_start_day", "date_format", "time_format",
    }
)  # fmt: skip
BRANCH_EDITABLE = frozenset(
    {
        "name", "code", "address", "timezone", "currency", "locale", "tax_settings",
        "branding", "email_sender_name", "email_sender_address", "invoice_prefix",
    }
)  # fmt: skip

MULTI_USER_TYPES = {
    Organisation.BusinessType.TEAM,
    Organisation.BusinessType.AGENCY,
    Organisation.BusinessType.CENTRE,
    Organisation.BusinessType.ONLINE,
}


def _check_timezone(value: str) -> None:
    if not is_valid_timezone(value):
        raise BusinessRuleViolation(
            _("Unknown timezone."), extra={"errors": {"timezone": [_("Unknown timezone.")]}}
        )


def mode_for(business_type: str) -> str:
    return Organisation.Mode.MULTI if business_type in MULTI_USER_TYPES else Organisation.Mode.SOLO


# --- organisations ------------------------------------------------------------------------------


@transaction.atomic
def create_organisation(
    *,
    name: str,
    owner: Any | None,
    country: str = "GB",
    slug: str | None = None,
    business_type: str = Organisation.BusinessType.SOLE_TRADER,
    timezone: str | None = None,
    currency: str | None = None,
    locale: str | None = None,
    status: str = Organisation.Status.TRIAL,
) -> Organisation:
    """Create a tenant with its default branch, settings and owner membership.

    Emits ``organisation.created`` (E04 starts the trial subscription from it) and
    ``branch.created``.
    """
    defaults = defaults_for(country)
    tz = timezone or defaults.timezone
    _check_timezone(tz)
    slug = slugs.validate_slug(slug) if slug else slugs.suggest_slug(name)
    try:
        with transaction.atomic():
            org = Organisation.objects.create(
                name=name.strip(),
                slug=slug,
                business_type=business_type,
                mode=mode_for(business_type),
                status=status,
                country=defaults.country,
                region=defaults.region,
                default_currency=(currency or defaults.currency).upper(),
                timezone=tz,
                locale=locale or defaults.locale,
                fiscal_year_start_month=defaults.fiscal_year_start_month,
                week_start_day=defaults.week_start_day,
                created_by=owner,
                contact_email=getattr(owner, "email", "") or "",
            )
    except IntegrityError as exc:  # lost a race for the slug
        raise slugs.InvalidSlug(_("This subdomain is already taken.")) from exc

    with tenant_context(org):
        audit.record(org, "create", {"name": [None, org.name], "slug": [None, org.slug]})
        publish(
            events.OrganisationCreated(
                subject_id=org.pk,
                name=org.name,
                slug=org.slug,
                business_type=org.business_type,
                country=org.country,
                owner_id=str(owner.pk) if owner is not None else None,
            ),
            organisation_id=org.pk,
        )
        create_branch(
            name=org.name,
            code="MAIN",
            is_default=True,
            timezone=org.timezone,
            currency=org.default_currency,
            locale=org.locale,
        )
        if owner is not None:
            from tutortrack.identity.models import Membership
            from tutortrack.identity.services import add_member

            add_member(owner, role=Membership.Role.OWNER)
    return org


@transaction.atomic
def update_organisation(organisation: Organisation, **changes: Any) -> Organisation:
    unknown = set(changes) - ORGANISATION_EDITABLE - {"slug"}
    if unknown:
        raise BusinessRuleViolation(f"Cannot change: {', '.join(sorted(unknown))}")
    if "timezone" in changes:
        _check_timezone(changes["timezone"])
    new_slug = changes.pop("slug", None)
    with tenant_context(organisation):
        if new_slug is not None and slugs.normalise(new_slug) != organisation.slug:
            change_slug(organisation, new_slug)
        if "business_type" in changes and "mode" not in changes:
            changes["mode"] = mode_for(changes["business_type"])
        with audit.track(organisation) as tracker:
            for field, value in changes.items():
                setattr(organisation, field, value)
            organisation.full_clean(exclude=["slug", "logo"])
            organisation.save()
        if tracker.entry is not None:
            publish(
                events.OrganisationUpdated(
                    subject_id=organisation.pk, fields=sorted(tracker.entry.changes)
                ),
                organisation_id=organisation.pk,
            )
    return organisation


@transaction.atomic
def change_slug(organisation: Organisation, new_slug: str) -> Organisation:
    """Rename the subdomain; the old one redirects for 90 days (FR-02-1)."""
    slug = slugs.validate_slug(new_slug, organisation=organisation)
    old = organisation.slug
    if slug == old:
        return organisation
    with tenant_context(organisation):
        # Moving back to a former slug: it is no longer a redirect.
        OrganisationDomain.objects.filter(organisation=organisation, hostname=slug).delete()
        OrganisationDomain.objects.update_or_create(
            hostname=old,
            defaults={
                "organisation": organisation,
                "type": OrganisationDomain.Type.SUBDOMAIN,
                "redirect_until": now() + timedelta(days=SLUG_REDIRECT_DAYS),
            },
        )
        with audit.track(organisation):
            organisation.slug = slug
            organisation.save(update_fields=["slug", "updated_at"])
        publish(
            events.OrganisationUpdated(subject_id=organisation.pk, fields=["slug"]),
            organisation_id=organisation.pk,
        )
    return organisation


# --- branches -----------------------------------------------------------------------------------


@transaction.atomic
def create_branch(*, name: str, code: str, is_default: bool = False, **fields: Any) -> Branch:
    """Create a branch in the organisation in context.

    Extra branches need the ``multi_branch`` feature (plan-gated in E04); the default
    branch is created at signup regardless.
    """
    if not is_default:
        flags.require("multi_branch")
    unknown = set(fields) - BRANCH_EDITABLE
    if unknown:
        raise BusinessRuleViolation(f"Unknown branch fields: {', '.join(sorted(unknown))}")
    org = Organisation.objects.get(pk=require_organisation_id())
    fields.setdefault("timezone", org.timezone)
    fields.setdefault("currency", org.default_currency)
    fields.setdefault("locale", org.locale)
    _check_timezone(fields["timezone"])
    code = code.strip().upper()
    if Branch.objects.filter(code=code).exists():
        raise BusinessRuleViolation(
            _("A branch with this code already exists."),
            extra={"errors": {"code": [_("A branch with this code already exists.")]}},
        )
    branch = Branch(name=name.strip(), code=code, is_default=is_default, **fields)
    branch.full_clean(exclude=["organisation"])
    branch.save()
    audit.record_create(branch)
    publish(
        events.BranchCreated(
            subject_id=branch.pk, name=branch.name, code=branch.code, is_default=is_default
        ),
        branch_id=branch.pk,
    )
    return branch


@transaction.atomic
def update_branch(branch: Branch, **changes: Any) -> Branch:
    unknown = set(changes) - BRANCH_EDITABLE
    if unknown:
        raise BusinessRuleViolation(f"Cannot change: {', '.join(sorted(unknown))}")
    if "timezone" in changes:
        _check_timezone(changes["timezone"])
    if "code" in changes:
        changes["code"] = str(changes["code"]).strip().upper()
        if Branch.objects.filter(code=changes["code"]).exclude(pk=branch.pk).exists():
            raise BusinessRuleViolation(
                _("A branch with this code already exists."),
                extra={"errors": {"code": [_("A branch with this code already exists.")]}},
            )
    with audit.track(branch) as tracker:
        for field, value in changes.items():
            setattr(branch, field, value)
        branch.full_clean(exclude=["organisation"])
        branch.save()
    if tracker.entry is not None:
        publish(
            events.BranchUpdated(subject_id=branch.pk, fields=sorted(tracker.entry.changes)),
            branch_id=branch.pk,
        )
    return branch


@transaction.atomic
def archive_branch(branch: Branch) -> Branch:
    if branch.is_default:
        raise BusinessRuleViolation(_("The default branch cannot be archived."))
    if branch.is_archived:
        return branch
    with audit.track(branch, action="archive"):
        branch.archive()
    publish(events.BranchArchived(subject_id=branch.pk), branch_id=branch.pk)
    return branch
