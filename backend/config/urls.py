from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from tutortrack.core.api.health import healthz, readyz

api_v1: list[URLPattern | URLResolver] = [
    path("", include("tutortrack.core.api.urls")),
    path("", include("tutortrack.tenancy.api.urls")),
    path("", include("tutortrack.identity.api.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
]
