from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AuditEntryViewSet, FeaturesView, PlatformStatusView, StoredFileViewSet

router = SimpleRouter(trailing_slash=False)
router.register("audit", AuditEntryViewSet, basename="audit")
router.register("files", StoredFileViewSet, basename="files")

urlpatterns = [
    path("features", FeaturesView.as_view(), name="features"),
    path("status", PlatformStatusView.as_view(), name="platform-status"),
    *router.urls,
]
