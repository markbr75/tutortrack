"""Self-serve signup (FR-02-6 step 1): user + organisation + verification email."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.identity import services as identity
from tutortrack.identity.models import User

from . import services
from .models import Organisation


class SignupRejected(BusinessRuleViolation):
    problem_type = "signup-rejected"
    title = "Signup could not be completed"


@dataclass(frozen=True)
class SignupResult:
    user: User
    organisation: Organisation
    created_user: bool


@transaction.atomic
def sign_up(
    *,
    business_name: str,
    country: str,
    user: Any | None = None,
    email: str = "",
    password: str = "",
    first_name: str = "",
    last_name: str = "",
    slug: str | None = None,
    business_type: str = Organisation.BusinessType.SOLE_TRADER,
    timezone: str | None = None,
) -> SignupResult:
    """Create the organisation (and, for new people, the user).

    ``user`` is an already signed-in person adding another organisation (FR-02-7); they
    are not asked for credentials again.
    """
    created_user = False
    if user is None:
        email = email.strip().lower()
        if User.objects.filter(email=email).exists():
            # Rate limiting and the captcha limit enumeration; the UX needs a clear answer.
            raise SignupRejected(
                _("An account with this email already exists. Sign in to add an organisation."),
                extra={"errors": {"email": [_("An account with this email already exists.")]}},
            )
        try:
            user = identity.create_user(
                email=email, password=password, first_name=first_name, last_name=last_name
            )
        except DjangoValidationError as exc:
            raise SignupRejected(
                _("Choose a stronger password."), extra={"errors": {"password": exc.messages}}
            ) from exc
        created_user = True

    organisation = services.create_organisation(
        name=business_name,
        owner=user,
        country=country,
        slug=slug,
        business_type=business_type,
        timezone=timezone,
    )
    with tenant_context(organisation):
        from .onboarding import start_onboarding

        start_onboarding(organisation)
    if user.email_verified_at is None:
        identity.send_verification_email(user)
    return SignupResult(user=user, organisation=organisation, created_user=created_user)
