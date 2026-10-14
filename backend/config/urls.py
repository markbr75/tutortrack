from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from tutortrack.calendar_sync.api.webhooks import google_calendar, microsoft_graph
from tutortrack.comms.api.phase2_views import inbound_email as inbox_email
from tutortrack.comms.api.views import postmark_webhook, twilio_inbound, twilio_status
from tutortrack.core.api.health import healthz, readyz
from tutortrack.leads.api.views import inbound_email
from tutortrack.payments.api.views import gocardless_webhook, paypal_webhook, stripe_webhook
from tutortrack.privacy.api.compliance_views import security_txt
from tutortrack.scheduling.api.views import ical_feed
from tutortrack.sites.internal import tls_ask
from tutortrack.subscriptions.api.views import stripe_billing_webhook
from tutortrack.workflows.api.views import codec

api_v1: list[URLPattern | URLResolver] = [
    path("", include("tutortrack.core.api.urls")),
    path("", include("tutortrack.tenancy.api.urls")),
    path("", include("tutortrack.identity.api.urls")),
    path("", include("tutortrack.workflows.api.urls")),
    path("", include("tutortrack.privacy.api.urls")),
    path("", include("tutortrack.people.api.urls")),
    path("", include("tutortrack.crm.api.urls")),
    path("", include("tutortrack.catalogue.api.urls")),
    path("", include("tutortrack.jobs.api.urls")),
    path("", include("tutortrack.scheduling.api.urls")),
    path("", include("tutortrack.delivery.api.urls")),
    path("", include("tutortrack.billing.api.urls")),
    path("", include("tutortrack.payments.api.urls")),
    path("", include("tutortrack.payroll.api.urls")),
    path("", include("tutortrack.leads.api.urls")),
    path("", include("tutortrack.recruitment.api.urls")),
    path("", include("tutortrack.matching.api.urls")),
    path("", include("tutortrack.automations.api.urls")),
    path("", include("tutortrack.reporting.api.urls")),
    path("", include("tutortrack.integrations.api.urls")),
    path("", include("tutortrack.calendar_sync.api.urls")),
    path("", include("tutortrack.developer.api.urls")),
    path("", include("tutortrack.accounting.api.urls")),
    path("", include("tutortrack.migration.api.urls")),
    path("", include("tutortrack.comms.api.urls")),
    path("", include("tutortrack.portal.api.urls")),
    path("", include("tutortrack.subscriptions.api.urls")),
    path("", include("tutortrack.sites.api.urls")),
    path("", include("tutortrack.courses.api.urls")),
    path("", include("tutortrack.growth.api.urls")),
    path("", include("tutortrack.learning.api.urls")),
    path("", include("tutortrack.platform_admin.api.urls")),
    path("", include("tutortrack.success.api.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path(".well-known/security.txt", security_txt, name="security-txt"),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
    path("ical/<str:token>.ics", ical_feed, name="ical-feed"),
    path("webhooks/stripe", stripe_webhook, name="stripe-webhook"),
    path("webhooks/gocardless", gocardless_webhook, name="gocardless-webhook"),
    path("webhooks/paypal", paypal_webhook, name="paypal-webhook"),
    path("webhooks/stripe/platform", stripe_billing_webhook, name="stripe-billing-webhook"),
    path("webhooks/postmark", postmark_webhook, name="postmark-webhook"),
    path("webhooks/inbound-email", inbound_email, name="inbound-email"),
    path("webhooks/twilio/status", twilio_status, name="twilio-status"),
    path("webhooks/twilio/inbound", twilio_inbound, name="twilio-inbound"),
    path("webhooks/inbound/email", inbox_email, name="inbox-inbound-email"),
    path("webhooks/google-calendar", google_calendar, name="google-calendar-webhook"),
    path("webhooks/microsoft-graph", microsoft_graph, name="microsoft-graph-webhook"),
    # Caddy on-demand TLS "ask" endpoint for custom domains (E24).
    path("internal/tls/ask", tls_ask, name="tls-ask"),
    # Temporal Web UI codec server (staff-only, E32 FR-32-9).
    path("temporal-codec/<slug:operation>", codec, name="temporal-codec"),
]
