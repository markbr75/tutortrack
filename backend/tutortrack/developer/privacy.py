"""API keys and app connections end when a person is erased (E27 data, E29 Part 2)."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.time import now
from tutortrack.privacy.registry import Person, Provider, Section, register

from .models import ApiKey, OAuthGrant


def export(person: Person) -> list[Section]:
    users = person.of("identity.user")
    keys = [
        {
            "id": str(k.pk),
            "name": k.name,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
            "revoked_at": k.revoked_at,
        }
        for k in ApiKey.objects.filter(user_id__in=users)
    ]
    grants = [
        {
            "id": str(g.pk),
            "application": g.application.name,
            "scopes": g.scopes,
            "revoked_at": g.revoked_at,
        }
        for g in OAuthGrant.objects.filter(user_id__in=users).select_related("application")
    ]
    return [
        Section("developer.api_keys", _("API keys"), keys),
        Section("developer.apps", _("Connected apps"), grants),
    ]


def revoke(person: Person) -> int:
    users = person.of("identity.user")
    if not users:
        return 0
    moment = now()
    count = ApiKey.objects.filter(user_id__in=users, revoked_at__isnull=True).update(
        revoked_at=moment
    )
    count += OAuthGrant.objects.filter(user_id__in=users, revoked_at__isnull=True).update(
        revoked_at=moment
    )
    return count


register(
    Provider(
        key="developer", label=gettext_lazy("API access"), export=export, revoke=revoke, order=95
    )
)
