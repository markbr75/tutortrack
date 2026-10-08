from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AuditEntryViewSet, FeaturesView, StoredFileViewSet

router = SimpleRouter(trailing_slash=False)
router.register("audit", AuditEntryViewSet, basename="audit")
router.register("files", StoredFileViewSet, basename="files")

urlpatterns = [
    path("features", FeaturesView.as_view(), name="features"),
    *router.urls,
]
