from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import BranchViewSet, OrganisationView, SettingsView

router = SimpleRouter(trailing_slash=False)
router.register("branches", BranchViewSet, basename="branches")

urlpatterns = [
    path("organisation", OrganisationView.as_view(), name="organisation"),
    path("settings/<slug:area>", SettingsView.as_view(), name="settings"),
    *router.urls,
]
