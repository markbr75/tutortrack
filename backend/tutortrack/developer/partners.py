"""Platform partner OAuth apps (Zapier, Make): created once per environment by
``manage.py ensure_partner_apps`` (and the dev seed). Their client secrets are printed once
for the platform team to enter in the partner's developer console."""

from __future__ import annotations

from dataclasses import dataclass

from . import connectors


@dataclass(frozen=True)
class Partner:
    key: str
    name: str
    description: str
    homepage_url: str
    redirect_uris: tuple[str, ...]


PARTNERS = (
    Partner(
        "zapier",
        "Zapier",
        "Connect TutorTrack to 6,000+ apps: new enquiries, completed lessons, paid invoices.",
        "https://zapier.com/apps/tutortrack",
        ("https://zapier.com/dashboard/auth/oauth/return/TutorTrackCLIAPI/",),
    ),
    Partner(
        "make",
        "Make",
        "Build visual scenarios with TutorTrack triggers, actions and searches.",
        "https://www.make.com/en/integrations/tutortrack",
        ("https://www.integromat.com/oauth/cb/app",),
    ),
)


def ensure_partner_apps() -> dict[str, str | None]:
    """Create missing partner apps. Returns ``{key: new secret or None if it existed}``."""
    from . import services
    from .models import OAuthApplication

    scopes = sorted(
        {a["scope"] for a in connectors.ACTIONS}
        | {s["scope"] for s in connectors.SEARCHES}
        | {"webhooks:read", "webhooks:write", "lessons:read", "invoices:read", "payments:read",
           "enquiries:read"}
    )  # fmt: skip
    out: dict[str, str | None] = {}
    for partner in PARTNERS:
        if OAuthApplication.objects.filter(partner_key=partner.key).exists():
            out[partner.key] = None
            continue
        _app, secret = services.register_application(
            name=partner.name,
            description=partner.description,
            homepage_url=partner.homepage_url,
            redirect_uris=list(partner.redirect_uris),
            allowed_scopes=scopes,
            owner_organisation_id=None,
            partner_key=partner.key,
            published=True,
        )
        out[partner.key] = secret
    return out
