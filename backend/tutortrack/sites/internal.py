"""Edge integration (FR-24-2): Caddy's on-demand TLS asks before issuing a certificate.

``GET /internal/tls/ask?domain=portal.example.com`` answers 200 only for verified custom
domains and the platform's own hostnames, so nobody can make the edge issue certificates
for arbitrary names. Not tenant-resolved (exempt in ``TenantMiddleware``)."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from tutortrack.tenancy.models import OrganisationDomain
from tutortrack.tenancy.resolution import site_subdomain_label


@require_GET
def tls_ask(request: HttpRequest) -> HttpResponse:
    host = request.GET.get("domain", "").strip().lower().rstrip(".")
    if not host or len(host) > 253:
        return HttpResponse(status=400)
    allowed = OrganisationDomain.objects.filter(
        hostname=host, type=OrganisationDomain.Type.CUSTOM, verified_at__isnull=False
    ).exists()
    if not allowed and site_subdomain_label(host) is not None:
        from tutortrack.tenancy.models import Organisation

        allowed = Organisation.objects.filter(slug=site_subdomain_label(host)).exists()
    return HttpResponse("ok" if allowed else "unknown", status=200 if allowed else 404)
