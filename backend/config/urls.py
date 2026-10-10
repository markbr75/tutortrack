from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from tutortrack.comms.api.views import postmark_webhook, twilio_inbound, twilio_status
from tutortrack.core.api.health import healthz, readyz
from tutortrack.payments.api.views import stripe_webhook
from tutortrack.scheduling.api.views import ical_feed
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
    path("", include("tutortrack.comms.api.urls")),
    path("", include("tutortrack.portal.api.urls")),
    path("", include("tutortrack.subscriptions.api.urls")),
    path("", include("tutortrack.platform_admin.api.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
    path("ical/<str:token>.ics", ical_feed, name="ical-feed"),
    path("webhooks/stripe", stripe_webhook, name="stripe-webhook"),
    path("webhooks/stripe/platform", stripe_billing_webhook, name="stripe-billing-webhook"),
    path("webhooks/postmark", postmark_webhook, name="postmark-webhook"),
    path("webhooks/twilio/status", twilio_status, name="twilio-status"),
    path("webhooks/twilio/inbound", twilio_inbound, name="twilio-inbound"),
    # Temporal Web UI codec server (staff-only, E32 FR-32-9).
    path("temporal-codec/<slug:operation>", codec, name="temporal-codec"),
]
