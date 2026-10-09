"""Security headers (FR-29-1).

``SecurityHeadersMiddleware`` adds, to every response:

* ``Content-Security-Policy``: API/JSON responses get a lock-down policy
  (``default-src 'none'; frame-ancestors 'none'``). HTML pages served by Django (admin, the
  browsable API, emails previews) get a nonce-based policy; templates use
  ``request.csp_nonce`` for any inline ``<script>``. Widget endpoints (E24) may be framed.
* ``Permissions-Policy`` (camera/microphone/geolocation off; payment for Stripe Elements).
* ``Cross-Origin-Opener-Policy`` and ``X-Content-Type-Options``.

The single-page apps are static files from CloudFront; their CSP is set there
(``infra/terraform/frontend.tf``). HSTS, secure cookies and X-Frame-Options come from
Django's SecurityMiddleware/clickjacking settings (``config/settings/prod.py``).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

GetResponse = Callable[[HttpRequest], HttpResponse]

API_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PERMISSIONS_POLICY = (
    'camera=(), microphone=(), geolocation=(), usb=(), payment=(self "https://js.stripe.com")'
)


def html_policy(nonce: str, *, frameable: bool = False) -> str:
    extra_scripts = " ".join(getattr(settings, "CSP_EXTRA_SCRIPT_SRC", []))
    extra_connect = " ".join(getattr(settings, "CSP_EXTRA_CONNECT_SRC", []))
    directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' {extra_scripts}".strip(),
        # Django admin uses inline style attributes; styles can't execute code.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        f"connect-src 'self' {extra_connect}".strip(),
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors *" if frameable else "frame-ancestors 'none'",
    ]
    return "; ".join(directives)


class SecurityHeadersMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        nonce = secrets.token_urlsafe(18)
        request.csp_nonce = nonce  # type: ignore[attr-defined]
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            content_type = response.get("Content-Type", "")
            frameable = request.path.startswith(tuple(settings.FRAMEABLE_PATH_PREFIXES))
            response["Content-Security-Policy"] = (
                html_policy(nonce, frameable=frameable)
                if content_type.startswith("text/html")
                else API_POLICY
            )
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response
