from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("developer/api-keys", v.ApiKeyViewSet, basename="developer-api-keys")
router.register("developer/oauth-apps", v.OAuthApplicationViewSet, basename="developer-oauth-apps")
router.register(
    "developer/connected-apps", v.ConnectedAppViewSet, basename="developer-connected-apps"
)
router.register("developer/sandboxes", v.SandboxViewSet, basename="developer-sandboxes")
router.register("webhook-endpoints", v.WebhookEndpointViewSet, basename="webhook-endpoints")
router.register("webhook-deliveries", v.WebhookDeliveryViewSet, basename="webhook-deliveries")

urlpatterns = [
    path("developer/scopes", v.ScopesView.as_view(), name="developer-scopes"),
    path("developer/overview", v.OverviewView.as_view(), name="developer-overview"),
    path("developer/marketplace", v.MarketplaceView.as_view(), name="developer-marketplace"),
    path("developer/openapi.json", v.PublicSchemaView.as_view(), name="developer-openapi"),
    path("developer/postman.json", v.PostmanView.as_view(), name="developer-postman"),
    path("developer/changelog", v.ChangelogView.as_view(), name="developer-changelog"),
    path(
        "developer/connectors/<slug:platform>",
        v.ConnectorView.as_view(),
        name="developer-connector",
    ),
    path("webhook-event-types", v.EventTypesView.as_view(), name="webhook-event-types"),
    path(
        "webhook-event-types/<str:event_type>/sample",
        v.EventSampleView.as_view(),
        name="webhook-event-sample",
    ),
    path("oauth/authorize", v.AuthorizeView.as_view(), name="oauth-authorize"),
    path("oauth/token", v.TokenView.as_view(), name="oauth-token"),
    path("oauth/revoke", v.RevokeView.as_view(), name="oauth-revoke"),
    *router.urls,
]
