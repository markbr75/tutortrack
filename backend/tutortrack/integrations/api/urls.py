from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register(
    "integrations/connections", v.IntegrationConnectionViewSet, basename="integration-connections"
)

urlpatterns = [
    path("integrations/providers", v.ProvidersView.as_view(), name="integration-providers"),
    path("integrations/oauth/start", v.OAuthStartView.as_view(), name="integration-oauth-start"),
    path(
        "integrations/oauth/callback",
        v.OAuthCallbackView.as_view(),
        name="integration-oauth-callback",
    ),
    path(
        "integrations/oauth/complete",
        v.OAuthCompleteView.as_view(),
        name="integration-oauth-complete",
    ),
    *router.urls,
]
